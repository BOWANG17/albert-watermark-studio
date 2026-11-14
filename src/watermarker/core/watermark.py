"""水印合成核心逻辑。

本模块只依赖 Pillow，**不 import 任何 GUI 库**。
这是项目最重要的架构约定：core 层与 ui 层彻底分离，
以后想换界面框架（或复刻移动版），这里的代码原样搬走即可。

设计要点：
- 水印必须画在独立的透明 RGBA 图层上，再用 alpha_composite 合成。
  直接在原图上 draw.text() 会无视 alpha 通道（透明度失效）。
- 测量文字尺寸用 textbbox()（textsize() 已废弃，且对中文不准）。
- 位置用"九宫格 + 边距"描述，字号/边距按图片尺寸比例缩放，
  保证同一套参数在 1000px 和 6000px 的图上都好看。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps

# 九宫格位置，键为位置名，值为 (水平对齐, 垂直对齐)
# 水平: 'l'左 'c'中 'r'右；垂直: 't'上 'm'中 'b'下
Position = Literal[
    "左上", "中上", "右上",
    "左中", "正中", "右中",
    "左下", "中下", "右下",
]

# 内部对齐坐标
_ALIGN = {
    "左上": ("l", "t"), "中上": ("c", "t"), "右上": ("r", "t"),
    "左中": ("l", "m"), "正中": ("c", "m"), "右中": ("r", "m"),
    "左下": ("l", "b"), "中下": ("c", "b"), "右下": ("r", "b"),
}


@dataclass
class TextWatermark:
    """文字水印参数。字号为"占图片短边的千分比"，例如 36 表示 3.6%。"""

    text: str = ""
    font_path: str = ""          # 字体文件绝对路径（必须，Pillow 不认系统字体名）
    size_permille: int = 36      # 字号：占短边的千分比
    opacity: float = 0.7         # 不透明度 0.0 ~ 1.0
    color: Tuple[int, int, int] = (255, 255, 255)   # RGB
    stroke_width: int = 1        # 描边宽度，保证浅色照片上也看得清
    stroke_color: Tuple[int, int, int] = (0, 0, 0)  # 描边颜色
    position: Position = "右下"
    margin_permille: int = 24    # 边距：占短边的千分比
    rotation: float = 0.0        # 旋转角度（度），0 表示不旋转


@dataclass
class ImageWatermark:
    """图片/Logo 水印参数。scale 为"占原图宽度的比例"。"""

    watermark_path: str = ""
    scale: float = 0.15          # 水印宽度 / 原图宽度
    opacity: float = 0.8
    position: Position = "右下"
    margin_permille: int = 24


def _px(base_short_edge: int, permille: int) -> int:
    """把千分比换算成像素，至少 1px。"""
    return max(1, round(base_short_edge * permille / 1000))


def _position_xy(content_w: int, content_h: int,
                 img_w: int, img_h: int,
                 position: Position, margin: int) -> Tuple[int, int]:
    """根据九宫格位置 + 边距，算出内容左上角坐标。"""
    ha, va = _ALIGN[position]
    if ha == "l":
        x = margin
    elif ha == "c":
        x = (img_w - content_w) // 2
    else:  # 'r'
        x = img_w - content_w - margin
    if va == "t":
        y = margin
    elif va == "m":
        y = (img_h - content_h) // 2
    else:  # 'b'
        y = img_h - content_h - margin
    return x, y


def add_text_watermark(
    img: Image.Image,
    wm: TextWatermark,
    font: Optional[ImageFont.FreeTypeFont] = None,
) -> Image.Image:
    """返回加了文字水印的新图（不改动原图）。"""
    base = ImageOps.exif_transpose(img).convert("RGBA")
    base_short = min(base.size)

    if font is None:
        size = _px(base_short, wm.size_permille)
        font = ImageFont.truetype(wm.font_path, size)

    # ① 独立透明图层，画水印
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # ② textbbox 拿到真实包围盒（含字形内边距），textsize 已废弃且对中文不准
    box = draw.textbbox((0, 0), wm.text, font=font)
    tw = box[2] - box[0]
    th = box[3] - box[1]

    alpha = int(255 * wm.opacity)
    margin = _px(base_short, wm.margin_permille)
    x, y = _position_xy(tw, th, base.width, base.height, wm.position, margin)
    # 扣掉包围盒偏移，让文字"看起来"正好在预期位置
    x -= box[0]
    y -= box[1]

    fill = wm.color + (alpha,)
    stroke = wm.stroke_color + (alpha // 2,)

    # ③ 需要旋转时，先在独立小图层上画字再旋转，避免整图旋转
    if wm.rotation:
        txt_layer = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        td = ImageDraw.Draw(txt_layer)
        td.text((x, y), wm.text, font=font, fill=fill,
                stroke_width=wm.stroke_width, stroke_fill=stroke)
        txt_layer = txt_layer.rotate(wm.rotation, resample=Image.BICUBIC,
                                     center=(x + tw / 2, y + th / 2))
        layer = Image.alpha_composite(layer, txt_layer)
    else:
        draw.text((x, y), wm.text, font=font, fill=fill,
                  stroke_width=wm.stroke_width, stroke_fill=stroke)

    # ④ 合成
    out = Image.alpha_composite(base, layer)
    return out


def add_image_watermark(
    img: Image.Image,
    wm: ImageWatermark,
    wm_img: Optional[Image.Image] = None,
) -> Image.Image:
    """返回加了图片/Logo 水印的新图。"""
    base = ImageOps.exif_transpose(img).convert("RGBA")
    base_short = min(base.size)

    if wm_img is None:
        wm_img = Image.open(wm.watermark_path).convert("RGBA")
    else:
        wm_img = wm_img.convert("RGBA")

    # 按原图宽度等比缩放水印
    target_w = max(1, round(base.width * wm.scale))
    ratio = target_w / wm_img.width
    target_h = max(1, round(wm_img.height * ratio))
    wm_img = wm_img.resize((target_w, target_h), Image.LANCZOS)

    # 调整透明度
    alpha = wm_img.split()[3].point(
        lambda p: int(p * wm.opacity)
    )
    wm_img.putalpha(alpha)

    margin = _px(base_short, wm.margin_permille)
    x, y = _position_xy(target_w, target_h,
                        base.width, base.height, wm.position, margin)
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    out.alpha_composite(base)
    out.alpha_composite(wm_img, (x, y))
    return out


def add_tiled_watermark(
    img: Image.Image,
    text: str,
    font_path: str,
    size_permille: int = 40,
    opacity: float = 0.15,
    rotation: float = -30.0,
    spacing_permille: int = 300,
    color: Tuple[int, int, int] = (255, 255, 255),
    stroke_width: int = 0,
    stroke_color: Tuple[int, int, int] = (0, 0, 0),
) -> Image.Image:
    """平铺水印：整张图斜排重复文字，用于防截图/防泄密。"""
    base = ImageOps.exif_transpose(img).convert("RGBA")
    base_short = min(base.size)
    size = _px(base_short, size_permille)
    font = ImageFont.truetype(font_path, size)

    box = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font)
    tw = box[2] - box[0]
    th = box[3] - box[1]
    spacing = _px(base_short, spacing_permille)

    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    alpha = int(255 * opacity)
    fill = color + (alpha,)
    stroke = stroke_color + (alpha // 2,)

    y = -base.height
    while y < base.height:
        x = -base.width
        while x < base.width:
            draw.text((x, y), text, font=font, fill=fill,
                      stroke_width=stroke_width, stroke_fill=stroke)
            x += tw + spacing
        y += th + spacing

    if rotation:
        layer = layer.rotate(rotation, resample=Image.BICUBIC, expand=True)
        layer = layer.crop((0, 0, base.width, base.height))
        # 居中裁剪
        lw, lh = layer.size
        if (lw, lh) != base.size:
            layer = layer.resize(base.size, Image.LANCZOS)

    out = Image.alpha_composite(base, layer)
    return out
