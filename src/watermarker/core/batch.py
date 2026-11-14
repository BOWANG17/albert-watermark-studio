"""批量处理：任务队列 + 进度回调 + 失败清单。

设计要点：
- 单张失败不中断整批，错误记入失败清单
- 通过回调函数报告进度，与"是否多线程"解耦
  （命令行版同步跑；GUI 版把这个函数放进 QThread 跑，回调转成信号）
- 水印图片只加载一次，循环里复用（避免每张图重复读盘）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Union

from PIL import Image

from .crop import CropSpec, apply_crop
from .image_io import open_image, save_image
from .info_bar import (
    BRAND_LOGOS,
    COLOR_SCHEMES,
    InfoBarStyle,
    add_info_bar,
)
from .exif import read_exif, exif_summary
from .watermark import (
    ImageWatermark,
    TextWatermark,
    add_image_watermark,
    add_text_watermark,
    add_tiled_watermark,
)

# 进度回调签名：(当前序号, 总数, 当前文件名)
ProgressCallback = Callable[[int, int, str], None]

# 界面布局名 -> 布局值（与 ui 层 LAYOUT_CHOICES 一致，core 层自包含、不反向依赖 ui）
_LAYOUT_NAME_TO_VALUE = {
    "不启用": None,
    "左 α Logo": "left_logo",
    "居中字标": "center",
    "三段式": "three_col",
    "右下署名": "corner_sign",
    "左图右文参数表": "left_panel",
    "月份大标题": "month_title",
}


def _build_info_bar_style_from_dict(d: dict) -> Optional[InfoBarStyle]:
    """从参数字典重建 InfoBarStyle（core 层，不依赖 GUI）。

    参数来自 MainWindow._collect_params_dict()，键名保持一致。
    布局值优先读 info_layout_value（core 值），否则按界面名映射（兼容旧预设）。
    """
    layout_value = d.get("info_layout_value")
    if layout_value is None:
        layout_value = _LAYOUT_NAME_TO_VALUE.get(d.get("info_layout", "不启用"))
    if layout_value is None:
        return None

    style = InfoBarStyle(layout=layout_value)

    # 配色
    scheme_name = d.get("info_scheme", "白底黑字")
    scheme = COLOR_SCHEMES.get(scheme_name, COLOR_SCHEMES["白底黑字"])
    style.apply_scheme(scheme)

    # 品牌 logo
    brand_name = d.get("info_brand", "α 符号")
    logo_path = BRAND_LOGOS.get(brand_name, "")
    style.apply_logo(logo_path)

    # 各布局的 logo 尺寸微调（与 ui 层 _current_info_bar_style 一致）
    if layout_value in ("center", "month_title", "left_panel"):
        style.brand_scale = 90
    if layout_value == "left_logo":
        style.logo_scale = 80

    # 署名 / 地点
    style.signature = (d.get("info_signature", "") or "").strip()
    style.location = (d.get("info_location", "") or "").strip()

    # corner_sign 位置微调
    style.corner_shift_x = int(d.get("corner_shift_x", 0))
    style.corner_shift_y = int(d.get("corner_shift_y", 0))
    return style


def _unique_path(path: Path) -> Path:
    """返回一个不覆盖已有文件的路径。

    若目标文件已存在，则在文件名后追加 -1、-2 …，直到找到空闲名。
    这样同一张图套用不同版型/素材导出到同一目录时，各版本都能保留。
    """
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    n = 1
    while True:
        candidate = path.with_name(f"{stem}-{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


@dataclass
class BatchResult:
    """一次批量处理的结果。"""
    total: int = 0
    succeeded: list[Path] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (文件名, 错误信息)

    @property
    def ok_count(self) -> int:
        return len(self.succeeded)

    @property
    def fail_count(self) -> int:
        return len(self.failed)


def process_batch(
    files: list[Union[str, Path]],
    output_dir: Union[str, Path],
    text_wm: Optional[TextWatermark] = None,
    image_wm: Optional[ImageWatermark] = None,
    crop_ratio: Optional[tuple[int, int]] = None,
    tiled: Optional[dict] = None,
    output_suffix: str = "_wm",
    quality: int = 92,
    output_format: Optional[str] = None,
    keep_exif: bool = False,
    info_bar_style: Optional[InfoBarStyle] = None,
    per_image_params: Optional[dict[str, dict]] = None,
    progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> BatchResult:
    """批量加水印（可选先裁剪、平铺、信息条）。

    Args:
        files: 输入图片路径列表
        output_dir: 输出目录（原图不会被覆盖）
        text_wm: 全局文字水印参数（可为 None）
        image_wm: 全局图片水印参数（可为 None）
        crop_ratio: 全局裁剪比例 (宽, 高)，None 表示不裁剪
        tiled: 全局平铺水印参数字典，None 表示不启用
        output_suffix: 输出文件名后缀
        quality: JPEG 保存质量
        output_format: 强制输出格式 "jpg"/"png"，None 时按原扩展名
        keep_exif: 是否保留原图 EXIF（默认不保留，避免泄露 GPS 等隐私）
        info_bar_style: 全局信息条版型参数（InfoBarStyle），None 表示不启用
        per_image_params: 每图独立参数 dict[路径 -> 参数字典]。存在时该图优先用
            自身参数（独立文字/图片水印、裁剪、平铺、信息条、格式/质量/EXIF），
            否则用全局参数。用于「多图独立模版」。
        progress: 进度回调
        should_cancel: 返回 True 时中止，供 GUI 取消按钮使用

    Returns:
        BatchResult
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = BatchResult(total=len(files))

    # 图片水印只加载一次，循环复用（全局默认图片水印）
    wm_img_cache: Optional[Image.Image] = None
    if image_wm is not None and image_wm.watermark_path:
        wm_img_cache = Image.open(image_wm.watermark_path).convert("RGBA")

    for i, f in enumerate(files):
        if should_cancel is not None and should_cancel():
            break

        f = Path(f)
        name = f.name
        try:
            # 逐图参数：该图有独立快照则优先用，否则用全局参数
            pp = (per_image_params or {}).get(str(f))
            _text_wm = text_wm
            _image_wm = image_wm
            _crop_ratio = crop_ratio
            _tiled = tiled
            _quality = quality
            _output_format = output_format
            _keep_exif = keep_exif
            _info_bar_style = info_bar_style

            if pp is not None:
                _text_wm = _build_text_wm_from_dict(pp) if pp.get("text_enabled", True) else None
                _image_wm = _build_image_wm_from_dict(pp)
                _crop_ratio = _crop_ratio_from_name(pp.get("crop", "不裁剪"))
                _tiled = _build_tiled_from_dict(pp)
                _quality = int(pp.get("quality", quality))
                fmt_name = pp.get("format", "原格式")
                _output_format = None if fmt_name == "原格式" else fmt_name.lower()
                _keep_exif = pp.get("keep_exif", keep_exif)
                _info_bar_style = _build_info_bar_style_from_dict(pp)

            img = open_image(f)
            exif = img.info.get("exif") if _keep_exif else None

            # 先裁剪，再加水印（顺序：裁剪 → 文字 → 平铺 → 图片 → 信息条）
            out = apply_crop(img, CropSpec(ratio=_crop_ratio))
            if _text_wm is not None and _text_wm.text:
                out = add_text_watermark(out, _text_wm)
            if _tiled:
                out = add_tiled_watermark(
                    out,
                    text=_tiled.get("text", ""),
                    font_path=_tiled.get("font_path", ""),
                    size_permille=_tiled.get("size_permille", 40),
                    opacity=_tiled.get("opacity", 0.15),
                    rotation=_tiled.get("rotation", -30.0),
                    spacing_permille=_tiled.get("spacing_permille", 300),
                    color=_tiled.get("color", (255, 255, 255)),
                )
            if _image_wm is not None:
                # 独立参数的图片水印可能路径不同，需单独加载
                if pp is not None and _image_wm.watermark_path != (image_wm.watermark_path if image_wm else ""):
                    _wm_img_cache = Image.open(_image_wm.watermark_path).convert("RGBA")
                else:
                    _wm_img_cache = wm_img_cache
                out = add_image_watermark(out, _image_wm, wm_img=_wm_img_cache)

            # 信息条（摄影 EXIF 版型）—— 最后加，且放在独立的最外层边框上
            if _info_bar_style is not None:
                ex = read_exif(f)
                params = exif_summary(f)
                fields = {
                    "model": ex.get("model", ""),
                    "lens": ex.get("lens", ""),
                    "focal": ex.get("focal", ""),
                    "fnumber": ex.get("fnumber", ""),
                    "exposure": ex.get("exposure", ""),
                    "iso": ex.get("iso", ""),
                    "params": params,
                    "datetime": ex.get("datetime", ""),
                    "location": _info_bar_style.location or "",
                    "signature": _info_bar_style.signature,
                }
                out = add_info_bar(out, _info_bar_style, fields)

            dst = output_dir / f"{f.stem}{output_suffix}{f.suffix}"
            # 强制输出格式时，扩展名与 save_image 内部保持一致
            if _output_format is not None:
                dst = dst.with_suffix("." + _output_format.lower().lstrip("."))
            # 防覆盖：同一张图套用不同版型/素材时，已存在则自动加序号
            dst = _unique_path(dst)
            save_image(out, dst, quality=_quality, fmt=_output_format,
                       exif=exif if _keep_exif else None)
            result.succeeded.append(dst)
        except Exception as e:  # noqa: BLE001 —— 单张失败不中断
            result.failed.append((name, str(e)))

        if progress is not None:
            progress(i + 1, len(files), name)

    return result


# ---------- 逐图参数 -> 水印对象（core 层纯函数，供 per_image_params 使用） ----------

def _crop_ratio_from_name(name: str) -> Optional[tuple[int, int]]:
    """裁剪比例名 -> (宽, 高) 比例，'不裁剪' 返回 None。"""
    from .crop import RATIOS
    return RATIOS.get(name)


def _build_text_wm_from_dict(d: dict) -> Optional[TextWatermark]:
    """从参数字典重建文字水印对象。"""
    text = d.get("text", "")
    if not text:
        return None
    font = d.get("font", "")
    # font 存的是界面名（FONT_MAP 的 key），core 层需要路径。这里由调用方保证
    # 传入 font_path 或可解析的名称；为稳妥，优先用 font_path 键。
    font_path = d.get("font_path", "") or font
    color = d.get("color", [255, 255, 255])
    if isinstance(color, (list, tuple)) and len(color) == 3:
        color = tuple(int(x) for x in color)
    else:
        color = (255, 255, 255)
    return TextWatermark(
        text=text,
        font_path=font_path,
        size_permille=int(d.get("size_permille", 36)),
        opacity=float(d.get("opacity", 0.7)),
        color=color,
        stroke_width=int(d.get("stroke_width", 1)) if d.get("stroke", True) else 0,
        stroke_color=(0, 0, 0) if sum(color) > 384 else (255, 255, 255),
        position=d.get("position", "右下"),
        margin_permille=int(d.get("margin", 24)),
        rotation=float(d.get("rotation", 0)),
    )


def _build_image_wm_from_dict(d: dict) -> Optional[ImageWatermark]:
    """从参数字典重建图片水印对象。"""
    if not d.get("image_enabled", False):
        return None
    logo_path = d.get("logo_path", "")
    if not logo_path:
        return None
    return ImageWatermark(
        watermark_path=logo_path,
        scale=0.15,
        opacity=0.85,
        position="左下",
        margin_permille=24,
    )


def _build_tiled_from_dict(d: dict) -> Optional[dict]:
    """从参数字典重建平铺水印参数字典。"""
    if not d.get("tiled_enabled", False):
        return None
    text = d.get("text", "")
    if not text:
        return None
    color = d.get("color", [255, 255, 255])
    if isinstance(color, (list, tuple)) and len(color) == 3:
        color = tuple(int(x) for x in color)
    return {
        "text": text,
        "font_path": d.get("font_path", "") or d.get("font", ""),
        "size_permille": int(d.get("size_permille", 40)),
        "opacity": 0.15,
        "rotation": -30.0,
        "spacing_permille": int(d.get("tiled_spacing", 300)),
        "color": color,
    }
