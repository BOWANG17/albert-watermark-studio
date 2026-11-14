"""预览后台渲染线程。

把「裁剪 → 缩略 → 文字水印 → 平铺 → 图片水印 → 信息条」整条预览
渲染链路搬到 QThread 后台执行，主线程只负责：
    - 收集当前所有参数
    - 把参数快照丢给 worker
    - 收到 result 后把 QPixmap 贴到预览标签

这样任何滑块拖动 / 文字输入都不会阻塞 UI 线程。

取消策略：每个 worker 带一个自增序号。主线程在发起新渲染前，
把上一代 worker 标记为取消；worker 在每帧渲染前检查取消标志，
若已被新任务取代则直接丢弃结果，避免「旧结果覆盖新结果」的闪烁。
"""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QThread, Signal

from ..core.crop import CropSpec, apply_crop
from ..core.exif import read_exif, exif_summary
from ..core.info_bar import InfoBarStyle, COLOR_SCHEMES, BRAND_LOGOS, add_info_bar
from ..core.watermark import (
    ImageWatermark,
    TextWatermark,
    add_image_watermark,
    add_text_watermark,
    add_tiled_watermark,
)


class PreviewWorker(QThread):
    """单次预览渲染线程（一次渲染即结束，非循环）。"""

    # 渲染完成：携带本次任务的序号和结果图
    # 注意：不能叫 finished，否则会覆盖 QThread 内建的 finished 信号，
    # 导致线程结束清理逻辑失效。
    result_ready = Signal(int, object)

    def __init__(
        self,
        seq: int,
        img: Image.Image,
        img_path: str,
        preview_scale: float,
        params: dict,
        parent=None,
    ):
        super().__init__(parent)
        self._seq = seq
        self._img = img
        self._img_path = img_path
        self._preview_scale = preview_scale
        self._params = params
        self._cancelled = False

    def cancel(self):
        """标记取消（主线程调用）。被取消的 worker 不再 emit 结果。"""
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        try:
            result = self._render()
        except Exception:
            # 渲染失败静默丢弃，避免刷屏；下一帧会自动重试
            return
        if not self._cancelled:
            self.result_ready.emit(self._seq, result)

    def _render(self) -> Image.Image:
        p = self._params
        # 先裁剪，再加水印
        ratio = p["crop_ratio"]
        out = apply_crop(self._img, CropSpec(ratio=ratio))
        if self._cancelled:
            return out

        thumb = out.copy()
        # 固定高清基准（短边 1200px），显示端再按预览框尺寸 fit 缩放。
        # 保证放大查看细节时不模糊，也避免缩得太小丢细节。
        thumb.thumbnail((1200, 1200), Image.LANCZOS)

        if p["text_enabled"] and p["text_wm"] is not None:
            thumb = add_text_watermark(thumb, p["text_wm"])
        if p["tiled"] is not None:
            thumb = add_tiled_watermark(
                thumb,
                text=p["tiled"]["text"],
                font_path=p["tiled"]["font_path"],
                size_permille=p["tiled"]["size_permille"],
                opacity=p["tiled"]["opacity"],
                rotation=p["tiled"]["rotation"],
                spacing_permille=p["tiled"]["spacing_permille"],
                color=p["tiled"]["color"],
            )
        if p["image_wm"] is not None:
            thumb = add_image_watermark(thumb, p["image_wm"])
        if p["info_bar_style"] is not None and self._img_path:
            thumb = self._render_info_bar(thumb, p["info_bar_style"])
        return thumb

    def _render_info_bar(self, img: Image.Image, style: InfoBarStyle) -> Image.Image:
        ex = read_exif(self._img_path)
        fields = {
            "model": ex.get("model", ""),
            "lens": ex.get("lens", ""),
            "focal": ex.get("focal", ""),
            "fnumber": ex.get("fnumber", ""),
            "exposure": ex.get("exposure", ""),
            "iso": ex.get("iso", ""),
            "params": exif_summary(self._img_path),
            "datetime": ex.get("datetime", ""),
            "location": style.location or "",
            "signature": style.signature,
        }
        return add_info_bar(img, style, fields)


class GalleryThumbWorker(QThread):
    """画廊模版缩略图后台渲染线程。

    切换文件时，8 个模版缩略图（信息条 ×6 + 水印 ×2）原本在主线程同步渲染，
    单个信息条约 150ms，8 个合计 ~700ms，是切换文件卡顿的主因。
    这里把它们搬到后台线程逐个渲染，每完成一个 emit 一张 PIL 图，
    主线程只负责转 QPixmap 并 setPixmap（转图/贴图很快，不阻塞）。

    取消策略：与 PreviewWorker 一致，用 cancel() 标记；新一批渲染发起前，
    主线程取消旧 worker，旧 worker 检查标志后提前退出。
    """

    # (模版 key, PIL Image)
    thumb_ready = Signal(str, object)
    # 全部渲染结束（含被取消提前退出）
    all_done = Signal()

    def __init__(
        self,
        img: Image.Image,
        fields: dict,
        text: str,
        font_path: str,
        demo_logo_path: str,
        tkeys: list[str],
        parent=None,
    ):
        super().__init__(parent)
        self._img = img
        self._fields = fields
        self._text = text
        self._font_path = font_path
        self._demo_logo_path = demo_logo_path
        self._tkeys = tkeys
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            for tkey in self._tkeys:
                if self._cancel:
                    return
                out = self._render_one(tkey)
                if out is not None and not self._cancel:
                    self.thumb_ready.emit(tkey, out)
        finally:
            self.all_done.emit()

    def _render_one(self, tkey: str):
        """渲染单个模版缩略图，返回 PIL Image 或 None。"""
        img = self._img.copy()
        base = 500
        img.thumbnail((base, base), Image.LANCZOS)

        if tkey.startswith("info:"):
            layout = tkey.split(":", 1)[1]
            if layout == "none":
                return img
            style = InfoBarStyle(layout=layout)
            style.apply_scheme(COLOR_SCHEMES["白底黑字"])
            style.apply_logo(BRAND_LOGOS["α 符号"])
            return add_info_bar(img, style, self._fields)
        if tkey == "wm:text":
            wm = TextWatermark(
                text=self._text or "© 我的名字",
                font_path=self._font_path,
                size_permille=48, opacity=0.8, color=(255, 255, 255),
                stroke_width=2, stroke_color=(0, 0, 0),
                position="右下", margin_permille=24,
            )
            return add_text_watermark(img, wm)
        if tkey == "wm:image":
            wm = ImageWatermark(
                watermark_path=self._demo_logo_path,
                scale=0.15, opacity=0.85,
                position="左下", margin_permille=24,
            )
            return add_image_watermark(img, wm)
        return img
