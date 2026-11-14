"""摄影信息条（EXIF 信息卡）渲染。

在照片四周加边框，并在底部/侧边加一条信息栏，栏内排版：
相机型号、拍摄参数、日期、地点、署名、品牌 Logo（α 或文字字标）。

只依赖 Pillow，不 import GUI 库。

支持的版型（layout 模式）：
- "three_col"  ：左中右三段式（左=型号+日期，中=α，右=参数+署名）
- "left_logo"  ：α 在最左端，左=型号+参数，右=地点+日期（模板A）
- "center"     ：全居中（SONY 字标 + 参数 + 地点日期 三行居中）（模板B）
- "corner_sign"：无信息条，仅边框 + 照片右下角署名/地点（模板D）
- "left_panel" ：左图右文参数表（照片在左，右侧留白区纵向排参数表）
- "month_title"：月份大标题 + 左下角品牌 logo（杂志封面式）

设计约定：
- 版型由 InfoBarStyle 的一组参数决定，可组合出多种变体。
- 所有尺寸按「照片短边千分比」缩放，保证不同分辨率下比例一致。
- α 符号用衬线字体斜体渲染；SONY/FUJIFILM 字标用无衬线加宽字距渲染。
- 统一模版引擎：布局骨架（layout）+ 品牌 logo（BRAND_LOGOS）+ 配色（COLOR_SCHEMES）
  三者正交，自由组合，替代多套写死的预设。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageOps


# 字体路径（macOS 系统字体，正式版打包进 assets）
FONT_SANS = "/System/Library/Fonts/Hiragino Sans GB.ttc"          # 冬青黑（无衬线）
FONT_SERIF = "/System/Library/Fonts/Supplemental/Songti.ttc"      # 宋体（衬线，α 用它）

# 素材目录（贴图 logo，兼容开发/打包两种模式）
from ..resources import resource_path

_ICON_DIR = resource_path("assets", "icons")
ALPHA_BLACK = str(_ICON_DIR / "alpha-black-trim.png")       # 黑色 α（手写体+方框）
ALPHA_ORANGE = str(_ICON_DIR / "alpha-orange-trim.png")     # 橙色 α
SONY_WORDMARK_BLACK = str(_ICON_DIR / "sony-wordmark-trim.png")   # 黑色 SONY 字标
SONY_WORDMARK_WHITE = str(_ICON_DIR / "sony-wordmark-white.png")  # 白色 SONY 字标

# 品牌 logo 贴图（统一模版引擎用）：界面名 -> PNG 路径
# 每个品牌一个透明底 PNG，含原始品牌色（如 Leica 红标、Nikon 黄标）。
BRAND_LOGOS = {
    "α 符号": str(_ICON_DIR / "alpha-black-trim.png"),
    "SONY": str(_ICON_DIR / "sony-wordmark-white.png"),
    "Sony α": str(_ICON_DIR / "sony-alpha.png"),
    "Canon": str(_ICON_DIR / "canon.png"),
    "Nikon": str(_ICON_DIR / "nikon.png"),
    "FUJIFILM": str(_ICON_DIR / "fujifilm.png"),
    "Hasselblad": str(_ICON_DIR / "hasselblad.png"),
    "Leica": str(_ICON_DIR / "leica.png"),
    "Insta360": str(_ICON_DIR / "insta360.png"),
    "DJI": str(_ICON_DIR / "dji.png"),
    "Ricoh": str(_ICON_DIR / "ricoh.png"),
    "Lumix": str(_ICON_DIR / "lumix.png"),
}


# 各布局的 logo 显示空间约束（占照片短边千分比）。
# 依据参考截图测算：logo 按「最大宽度」约束缩放（fit-in-box），
# 扁长文字 logo（Hasselblad/FUJIFILM）与方块 logo（Nikon/Leica）都能适配。
#   - logo_max_w : logo 内容最大宽度（占短边千分比）
#   - logo_max_h : logo 内容最大高度（占短边千分比）；None 表示仅按宽度约束
LOGO_BOX = {
    "three_col":   dict(max_w=200, max_h=80),    # 中间 logo：HASSELBLAD 约 20% 宽
    "left_logo":   dict(max_w=130, max_h=70),    # 左端 logo：FUJIFILM 约 12-13% 宽
    "center":      dict(max_w=120, max_h=90),    # 居中 logo：圆标直径约 8-9%
    "left_panel":  dict(max_w=120, max_h=60),    # 右侧栏底部 logo
    "month_title": dict(max_w=130, max_h=80),    # 左下角 logo：圆标直径约 11-12%
    "corner_sign": dict(max_w=0, max_h=0),       # 无 logo
}


# 配色方案（统一模版引擎用）：界面名 -> (信息栏背景, 主文字, 次文字, logo色, 分隔线色)
# logo_color 仅对字体渲染的品牌字标有效；PNG 贴图保留自身颜色，不受影响。
COLOR_SCHEMES = {
    "白底黑字": dict(
        bar_bg=(255, 255, 255),
        text_primary=(0, 0, 0),
        text_secondary=(150, 150, 150),
        logo_color=(0, 0, 0),
        divider_color=(200, 200, 200),
    ),
    "深灰底白字": dict(
        bar_bg=(40, 40, 40),
        text_primary=(255, 255, 255),
        text_secondary=(170, 170, 170),
        logo_color=(255, 255, 255),
        divider_color=(90, 90, 90),
    ),
    "米白底黑字": dict(
        bar_bg=(245, 244, 240),
        text_primary=(0, 0, 0),
        text_secondary=(130, 130, 130),
        logo_color=(0, 0, 0),
        divider_color=(205, 203, 198),
    ),
    "纯黑底白字": dict(
        bar_bg=(0, 0, 0),
        text_primary=(255, 255, 255),
        text_secondary=(160, 160, 160),
        logo_color=(255, 255, 255),
        divider_color=(60, 60, 60),
    ),
}


@dataclass
class InfoBarStyle:
    """信息条版型参数。"""

    # 布局模式
    layout: str = "three_col"   # three_col / left_logo / center / corner_sign / left_panel / month_title

    # 配色
    bar_bg: Tuple[int, int, int] = (255, 255, 255)        # 信息栏背景（corner_sign 时是边框色）
    text_primary: Tuple[int, int, int] = (0, 0, 0)        # 主文字（型号/参数/地点）
    text_secondary: Tuple[int, int, int] = (150, 150, 150)  # 次要文字（日期/署名）
    logo_color: Tuple[int, int, int] = (0, 0, 0)          # α Logo / 字标颜色

    # Logo
    show_alpha: bool = True           # 是否显示 α 符号
    alpha_text: str = "α"             # logo 文本（无 alpha_image 时用字体渲染）
    logo_font: str = FONT_SERIF      # logo 字体
    brand_text: str = ""              # 字标文本（如 "SONY" / "FUJIFILM"），非空则替代 α
    alpha_image: str = ""             # α 贴图路径（PNG，优先于字体渲染）
    brand_image: str = ""             # 字标贴图路径（PNG，优先于 brand_text 字体渲染）
    logo_image: str = ""              # 统一 logo 贴图路径（apply_logo 设置，渲染函数按需用）
    logo_scale: int = 60              # 贴图 logo 高度（占短边千分比）
    brand_scale: int = 90             # 品牌字标贴图高度（占短边千分比），
                                      # 单独控制 SONY/FUJIFILM 字标大小（扁长形需更大高度）
    logo_y_shift: float = 0.0         # logo 垂直偏移（占 logo 高度的比例，负=上移），
                                      # 用于补偿 α 造型（右上角标+左下 α）重心偏下的观感

    # 分隔线
    show_divider: bool = True
    divider_color: Tuple[int, int, int] = (200, 200, 200)

    # 字号（占短边千分比）
    size_title: int = 34             # 型号/地点/参数 主字号
    size_small: int = 24             # 日期/署名 次字号
    size_alpha: int = 60             # α 字号
    size_brand: int = 44             # SONY/FUJIFILM 字标字号
    size_month: int = 90             # month_title 布局的月份大标题字号

    # month_title 布局专用
    month_name: str = ""             # 月份名（如 "September"），空则从 datetime 自动提取
    year_text: str = ""              # 年份（如 "2020"），空则从 datetime 自动提取

    # 边框（照片四周白边）
    frame_permille: int = 30         # 四周白边宽度（千分比）
    bar_permille: int = 110          # 信息栏高度（千分比）

    # 署名（corner_sign 用）
    signature: str = ""              # 如 "Foto by Vika Kirillova"
    signature_size: int = 30         # 署名字号（千分比）

    # 地点（手动填写，GPS 反查成本高，多数照片没有地点）
    location: str = ""               # 如 "Gdańsk, Poland"

    # corner_sign 独有：署名/地点文字组的自由位置微调
    # 偏移量占照片短边千分比，正=向右/向下，负=向左/向上。
    corner_shift_x: int = 0          # 水平偏移（千分比）
    corner_shift_y: int = 0          # 垂直偏移（千分比）

    def __post_init__(self):
        pass

    def apply_scheme(self, scheme: dict) -> "InfoBarStyle":
        """套用一套配色方案（COLOR_SCHEMES 的一项），返回 self 便于链式调用。"""
        for key in ("bar_bg", "text_primary", "text_secondary", "logo_color", "divider_color"):
            if key in scheme:
                setattr(self, key, scheme[key])
        return self

    def apply_logo(self, logo_path: str) -> "InfoBarStyle":
        """统一设置品牌 logo 贴图。根据布局决定映射到 alpha_image 或 brand_image。

        - center / month_title 布局用 brand_image（居中大 logo / 左下角 logo）
        - 其余布局用 alpha_image（信息条内的 logo）
        统一用 logo_image 字段承载，渲染函数按需读取。
        """
        self.logo_image = logo_path
        # 兼容旧字段：让各渲染函数无需改动即可读取
        self.alpha_image = logo_path
        self.brand_image = logo_path
        self.show_alpha = bool(logo_path)
        return self


def _px(base: int, permille: int) -> int:
    return max(1, round(base * permille / 1000))


def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _draw_text(draw, xy, text, font, fill, anchor="ls"):
    try:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)
    except (TypeError, ValueError):
        draw.text(xy, text, font=font, fill=fill)


def _text_w(font, text) -> int:
    if not text:
        return 0
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _draw_brand(draw, xy, text, font, fill, spacing_permille, base, anchor="mm"):
    """绘制带加宽字距的品牌字标（如 SONY）。"""
    if not text:
        return
    spacing = _px(base, spacing_permille)
    # 逐字符绘制，手动加字距
    total_w = 0
    widths = []
    for ch in text:
        w = _text_w(font, ch)
        widths.append(w)
        total_w += w
    total_w += spacing * (len(text) - 1)

    # 从 anchor 计算起点
    if anchor == "mm":
        start_x = xy[0] - total_w // 2
    elif anchor == "lm":
        start_x = xy[0]
    elif anchor == "rm":
        start_x = xy[0] - total_w
    else:
        start_x = xy[0]

    # 逐字画（用中线锚点 mm 的语义：传入 xy 是文字垂直中线）
    asc, desc = font.getmetrics()
    y = xy[1] - (asc + desc) // 2
    cur_x = start_x
    for ch, w in zip(text, widths):
        draw.text((cur_x, y), ch, font=font, fill=fill)
        cur_x += w + spacing


def _load_logo_image(path: str) -> Optional[Image.Image]:
    """加载贴图 logo（PNG，RGBA）。失败返回 None。"""
    if not path:
        return None
    try:
        img = Image.open(path)
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        return img
    except Exception:
        return None


def _content_centroid(logo: Image.Image):
    """返回 logo 非透明像素的质心 (cx, cy)，用于视觉居中补偿。"""
    a = logo.getchannel("A")
    w, h = logo.size
    sx = sy = cnt = 0
    # 降采样以提速（大步长，误差可忽略）
    step = max(1, min(w, h) // 256)
    for y in range(0, h, step):
        for x in range(0, w, step):
            if a.getpixel((x, y)) > 10:
                sx += x
                sy += y
                cnt += 1
    if cnt == 0:
        return w / 2, h / 2
    return sx / cnt, sy / cnt


def _trim_content(logo: Image.Image) -> Image.Image:
    """裁掉透明边，返回内容 bbox 内的子图。无透明内容时原样返回。"""
    bbox = logo.getchannel("A").getbbox()
    if bbox:
        return logo.crop(bbox)
    return logo


def _paste_logo(canvas, logo: Image.Image, center_xy, target_h, anchor="mm",
                trim_content=True, centroid_align=False):
    """把 logo 贴图贴到画布上（按目标**高度**等比缩放，保留旧接口语义）。

    Args:
        canvas: 目标画布
        logo: RGBA logo 图
        center_xy: 贴图中心点（或锚点，视 anchor）
        target_h: 目标高度（像素）
        anchor: "mm" 中心 / "lm" 左中 / "rm" 右中
        trim_content: 是否先裁掉透明边（内容 bbox），使内容真正居中。
        centroid_align: 是否按内容质心（而非几何中心）对齐 center_xy。
    """
    if logo is None:
        return
    if trim_content:
        logo = _trim_content(logo)

    # 按目标高度等比缩放
    ratio = target_h / logo.height
    new_w = max(1, round(logo.width * ratio))
    new_h = target_h
    logo_resized = logo.resize((new_w, new_h), Image.LANCZOS)

    _paste_resized(canvas, logo_resized, center_xy, anchor, centroid_align)


def _paste_logo_fit(canvas, logo: Image.Image, center_xy, box_w, box_h,
                    anchor="mm", trim_content=True, max_h=None):
    """把 logo 贴图贴到画布上，**在指定矩形框内等比缩放（fit-in-box）**。

    这是修复「扁长文字 logo 超出显示空间」的核心：
    - box_w / box_h 定义 logo 允许占据的最大矩形（像素）。
    - logo 内容（裁透明边后）等比缩放，同时满足「宽 <= box_w 且 高 <= box_h」，
      取其中较小的缩放系数，保证绝不超出显示空间、不变形。
    - 可再传 max_h 单独收紧高度上限（如信息条高度有限时）。

    Args:
        canvas: 目标画布
        logo: RGBA logo 图
        center_xy: 锚点坐标（含义由 anchor 决定）
        box_w: 允许的最大宽度（像素）
        box_h: 允许的最大高度（像素）
        anchor: "mm" 中心 / "lm" 左中 / "rm" 右中
        trim_content: 是否裁掉透明边
        max_h: 可选，更严格的高度上限（像素），优先于 box_h
    """
    if logo is None:
        return
    if trim_content:
        logo = _trim_content(logo)

    if max_h is not None:
        box_h = min(box_h, max_h)

    # 等比缩放：同时满足宽高上限，取更小系数
    ratio_w = box_w / logo.width
    ratio_h = box_h / logo.height
    ratio = min(ratio_w, ratio_h)
    new_w = max(1, round(logo.width * ratio))
    new_h = max(1, round(logo.height * ratio))
    logo_resized = logo.resize((new_w, new_h), Image.LANCZOS)

    _paste_resized(canvas, logo_resized, center_xy, anchor, centroid_align=False)


def _paste_resized(canvas, logo_resized: Image.Image, center_xy, anchor="mm",
                   centroid_align=False):
    """按已缩放的 logo 计算粘贴坐标并贴图。"""
    new_w, new_h = logo_resized.size

    if anchor == "mm":
        x = center_xy[0] - new_w // 2
        y = center_xy[1] - new_h // 2
    elif anchor == "lm":
        x = center_xy[0]
        y = center_xy[1] - new_h // 2
    elif anchor == "rm":
        x = center_xy[0] - new_w
        y = center_xy[1] - new_h // 2
    else:
        x, y = center_xy

    if centroid_align:
        cx, cy = _content_centroid(logo_resized)
        off_y_ratio = cy / logo_resized.height - 0.5
        y -= round(new_h * off_y_ratio)

    canvas.paste(logo_resized, (x, y), logo_resized)


def add_info_bar(img: Image.Image, style: InfoBarStyle,
                 fields: Optional[dict] = None) -> Image.Image:
    """给照片加边框 + 信息条，返回新图。"""
    img = ImageOps.exif_transpose(img).convert("RGB")
    fields = fields or {}

    w, h = img.size
    base = min(w, h)

    model = fields.get("model", "")
    params = fields.get("params", "")
    dt = fields.get("datetime", "")
    location = fields.get("location", "")
    signature = fields.get("signature", "") or style.signature

    # 分派到具体布局
    if style.layout == "corner_sign":
        return _render_corner_sign(img, style, fields)
    if style.layout == "center":
        return _render_center(img, style, fields)
    if style.layout == "left_logo":
        return _render_left_logo(img, style, fields)
    if style.layout == "left_panel":
        return _render_left_panel(img, style, fields)
    if style.layout == "month_title":
        return _render_month_title(img, style, fields)
    # 默认 three_col
    return _render_three_col(img, style, fields)


# ---------------------------------------------------------------------------
# 各版型渲染实现
# ---------------------------------------------------------------------------

def _make_canvas(img, style, extra_h=0):
    """创建带边框的画布，extra_h 为额外底部高度（信息栏）。"""
    w, h = img.size
    base = min(w, h)
    frame = _px(base, style.frame_permille)
    canvas_w = w + frame * 2
    canvas_h = h + frame * 2 + extra_h
    canvas = Image.new("RGB", (canvas_w, canvas_h), style.bar_bg)
    canvas.paste(img, (frame, frame))
    return canvas, frame, base


def _render_three_col(img, style, fields):
    """左中右三段式：左=型号+日期，中=logo，右=参数+署名。"""
    w, h = img.size
    base = min(w, h)
    bar = _px(base, style.bar_permille)
    canvas, frame, base = _make_canvas(img, style, extra_h=bar)

    draw = ImageDraw.Draw(canvas)
    bar_top = frame + h
    canvas_w = canvas.width

    f_title = _load_font(FONT_SANS, _px(base, style.size_title))
    f_small = _load_font(FONT_SANS, _px(base, style.size_small))

    pad = _px(base, style.frame_permille)
    # 信息条「视觉区域」= 底部白边 frame + 信息栏 bar，内容垂直居中于这整片区域
    bar_total = bar + frame
    bar_mid_y = bar_top + bar_total // 2

    # 用真实字高（asc+desc）计算两行文字块，让左右两段各自垂直居中于信息栏
    title_asc, title_desc = f_title.getmetrics()
    small_asc, small_desc = f_small.getmetrics()
    title_h = title_asc + title_desc
    small_h = small_asc + small_desc
    gap = _px(base, 12)
    block_h = title_h + gap + small_h
    block_top = bar_top + (bar_total - block_h) // 2
    y_main = block_top + title_h // 2
    y_sub = block_top + title_h + gap + small_h // 2

    model = fields.get("model", "")
    params = fields.get("params", "")
    dt = fields.get("datetime", "")
    signature = fields.get("signature", "") or style.signature

    # 左段
    left_x = pad
    _draw_text(draw, (left_x, y_main), model, f_title, style.text_primary, anchor="lm")
    if dt:
        _draw_text(draw, (left_x, y_sub), dt, f_small, style.text_secondary, anchor="lm")

    # 中段 logo（fit-in-box：按最大宽度约束缩放，扁长文字 logo 不超宽）
    alpha_x = canvas_w // 2
    logo_w = 0  # 实际 logo 宽度，供分隔线定位
    if style.show_alpha:
        logo_img = _load_logo_image(style.alpha_image)
        if logo_img is not None:
            box = LOGO_BOX["three_col"]
            max_w = _px(base, box["max_w"])
            max_h = _px(base, box["max_h"])
            _paste_logo_fit(canvas, logo_img, (alpha_x, bar_mid_y), max_w, max_h,
                            anchor="mm")
            # 反推实际内容宽度（裁边后），用于分隔线避让
            trimmed = _trim_content(logo_img)
            ratio = min(max_w / trimmed.width, max_h / trimmed.height)
            logo_w = max(1, round(trimmed.width * ratio))
        else:
            f_alpha = _load_font(style.logo_font, _px(base, style.size_alpha))
            _draw_text(draw, (alpha_x, bar_mid_y), style.alpha_text, f_alpha,
                       style.logo_color, anchor="mm")

    # 分隔线：仅当 logo 是窄型（方块/α）时才画，且位置按 logo 实际宽度避让。
    # 文字型扁长 logo（宽高比大）不画分隔线，避免小竖线干扰 logo 显示。
    if style.show_divider and logo_w > 0:
        logo_img2 = _load_logo_image(style.alpha_image)
        trimmed2 = _trim_content(logo_img2) if logo_img2 else None
        aspect = (trimmed2.width / trimmed2.height) if trimmed2 else 1.0
        if aspect < 3.0:  # 仅窄型 logo 保留分隔线
            line_x = alpha_x + logo_w // 2 + _px(base, 20)
            line_top = bar_top + bar_total // 4
            line_bot = bar_top + bar_total * 3 // 4
            draw.line([(line_x, line_top), (line_x, line_bot)],
                      fill=style.divider_color, width=max(1, _px(base, 2)))

    # 右段
    if params:
        _draw_text(draw, (canvas_w - pad, y_main), params, f_title,
                   style.text_primary, anchor="rm")
    if signature:
        _draw_text(draw, (canvas_w - pad, y_sub), signature, f_small,
                   style.text_secondary, anchor="rm")

    return canvas


def _render_left_logo(img, style, fields):
    """模板A：α 在最左端，左=型号(粗)+参数，右=地点(粗)+日期(灰)，无分隔线。"""
    w, h = img.size
    base = min(w, h)
    bar = _px(base, style.bar_permille)
    canvas, frame, base = _make_canvas(img, style, extra_h=bar)

    draw = ImageDraw.Draw(canvas)
    bar_top = frame + h
    canvas_w = canvas.width

    f_title = _load_font(FONT_SANS, _px(base, style.size_title))
    f_small = _load_font(FONT_SANS, _px(base, style.size_small))

    pad = _px(base, style.frame_permille)
    # 信息条「视觉区域」= 底部白边 frame + 信息栏 bar，内容垂直居中于这整片区域
    bar_total = bar + frame
    bar_mid_y = bar_top + bar_total // 2

    model = fields.get("model", "")
    params = fields.get("params", "")
    dt = fields.get("datetime", "")
    location = fields.get("location", "")

    # 用真实字高（asc+desc）计算两行文字块，并让整个块垂直居中于信息栏
    title_asc, title_desc = f_title.getmetrics()
    small_asc, small_desc = f_small.getmetrics()
    title_h = title_asc + title_desc
    small_h = small_asc + small_desc
    gap = _px(base, 12)
    block_h = title_h + gap + small_h
    block_top = bar_top + (bar_total - block_h) // 2
    # 第一行/第二行的垂直中线（anchor 用 mm）
    y_main = block_top + title_h // 2
    y_sub = block_top + title_h + gap + small_h // 2

    # α Logo 在最左端，垂直居中于信息栏（fit-in-box 按最大宽度约束，
    # 扁长文字 logo 不超宽；用 logo_y_shift 做微调补偿造型重心偏移）
    left_x = pad
    if style.show_alpha:
        logo_img = _load_logo_image(style.alpha_image)
        if logo_img is not None:
            box = LOGO_BOX["left_logo"]
            max_w = _px(base, box["max_w"])
            max_h = _px(base, box["max_h"])
            y_shift = round(_px(base, box["max_h"]) * style.logo_y_shift)
            _paste_logo_fit(canvas, logo_img, (left_x, bar_mid_y + y_shift),
                            max_w, max_h, anchor="lm")
            # 反推实际内容宽度，用于让文字右移避让 logo
            trimmed = _trim_content(logo_img)
            ratio = min(max_w / trimmed.width, max_h / trimmed.height)
            left_x += max(1, round(trimmed.width * ratio)) + _px(base, 20)
        else:
            f_alpha = _load_font(style.logo_font, _px(base, style.size_alpha))
            _draw_text(draw, (left_x, bar_mid_y), style.alpha_text, f_alpha,
                       style.logo_color, anchor="lm")
            left_x += _px(base, style.size_alpha) + _px(base, 20)

    # 左段：型号（主）+ 参数（次）
    _draw_text(draw, (left_x, y_main), model, f_title, style.text_primary, anchor="lm")
    if params:
        _draw_text(draw, (left_x, y_sub), params, f_small, style.text_secondary, anchor="lm")

    # 右段：地点（主）+ 日期（次）
    if location:
        _draw_text(draw, (canvas_w - pad, y_main), location, f_title,
                   style.text_primary, anchor="rm")
    if dt:
        _draw_text(draw, (canvas_w - pad, y_sub), dt, f_small,
                   style.text_secondary, anchor="rm")

    return canvas


def _render_center(img, style, fields):
    """模板B：全居中，SONY字标(衬线+宽字距) + 参数 + 地点日期，三行居中，深灰底白字。"""
    w, h = img.size
    base = min(w, h)

    model = fields.get("model", "")
    params = fields.get("params", "")
    dt = fields.get("datetime", "")
    location = fields.get("location", "")

    brand = style.brand_text or model or ""
    brand_img = _load_logo_image(style.brand_image)
    f_brand = _load_font(style.logo_font, _px(base, style.size_brand))
    f_param = _load_font(FONT_SANS, _px(base, style.size_title))
    f_small = _load_font(FONT_SANS, _px(base, style.size_small))

    # 三行内容（从上到下）
    loc_date = "  ".join(x for x in (location, dt) if x)
    lines = []
    if brand_img is not None:
        lines.append(("__BRAND_IMG__", None, None, "image"))
    elif brand:
        lines.append((brand, f_brand, style.logo_color, "brand"))
    if params:
        lines.append((params, f_param, style.text_primary, "text"))
    if loc_date:
        lines.append((loc_date, f_small, style.text_secondary, "text"))

    # 每行高度
    line_heights = []
    for text, fnt, _c, kind in lines:
        if kind == "image":
            # 居中 logo：按 fit-in-box 约束计算实际高度（宽<=120‰ 且 高<=90‰）
            box = LOGO_BOX["center"]
            trimmed = _trim_content(brand_img) if brand_img else None
            if trimmed:
                max_w = _px(base, box["max_w"])
                max_h = _px(base, box["max_h"])
                ratio = min(max_w / trimmed.width, max_h / trimmed.height)
                line_heights.append(max(1, round(trimmed.height * ratio)))
            else:
                line_heights.append(_px(base, style.brand_scale))
        else:
            asc, desc = fnt.getmetrics()
            line_heights.append(asc + desc)

    # 行距 + 上下留白（让信息栏高度能完整容纳内容，避免图标贴顶）
    line_gap = _px(base, 26)
    pad_v = _px(base, 24)
    content_h = sum(line_heights) + line_gap * (len(lines) - 1)

    # 栏高：至少 bar_permille*1.5，但若内容更高则用「内容 + 上下留白」
    bar_min = _px(base, int(style.bar_permille * 1.5))
    bar = max(bar_min, content_h + pad_v * 2)

    canvas, frame, base = _make_canvas(img, style, extra_h=bar)

    draw = ImageDraw.Draw(canvas)
    bar_top = frame + h
    canvas_w = canvas.width
    cx = canvas_w // 2

    # 顶部起点：让文字块在「底部白边 + 信息栏」整片区域内垂直居中
    bar_total = bar + frame
    cur_y = bar_top + (bar_total - content_h) // 2

    for i, (text, fnt, color, kind) in enumerate(lines):
        lh = line_heights[i]
        mid_y = cur_y + lh // 2
        if kind == "image":
            box = LOGO_BOX["center"]
            max_w = _px(base, box["max_w"])
            max_h = _px(base, box["max_h"])
            _paste_logo_fit(canvas, brand_img, (cx, mid_y), max_w, max_h, anchor="mm")
        elif kind == "brand":
            _draw_brand(draw, (cx, mid_y), text, fnt, color,
                        spacing_permille=style.size_brand // 2, base=base, anchor="mm")
        else:
            _draw_text(draw, (cx, mid_y), text, fnt, color, anchor="mm")
        cur_y += lh + line_gap

    return canvas


def _render_corner_sign(img, style, fields):
    """模板D：米白边框 + 照片右下角署名/地点（压在照片上）。

    右下角从上到下依次：地点（可选）、署名。文字右对齐，往右下靠拢，
    但保留协调的右内边距与下边距，避免贴死边缘。
    """
    w, h = img.size
    base = min(w, h)
    frame = _px(base, style.frame_permille)
    # 底部边框加宽（模板D底部更宽，留出署名区）
    frame_bottom = _px(base, style.frame_permille * 2)

    canvas_w = w + frame * 2
    canvas_h = h + frame + frame_bottom
    canvas = Image.new("RGB", (canvas_w, canvas_h), style.bar_bg)
    canvas.paste(img, (frame, frame))

    draw = ImageDraw.Draw(canvas)

    signature = fields.get("signature", "") or style.signature
    location = fields.get("location", "")

    f_sig = _load_font(FONT_SANS, _px(base, style.signature_size))
    f_loc = _load_font(FONT_SANS, _px(base, style.size_small))

    sig_asc, sig_desc = f_sig.getmetrics()
    loc_asc, loc_desc = f_loc.getmetrics()

    # 美观边距：右下角留一个协调的「L 形」呼吸空间
    # 右内边距 = 署名字号，下边距 = 署名字号 * 1.6（略大于右，符合右下角视觉习惯）
    right_margin = _px(base, style.signature_size)
    bottom_margin = _px(base, int(style.signature_size * 1.6))

    # 用户自由微调偏移（corner_sign 独有）：正=向右/向下
    # 注意：不能用 _px（它内部 max(1,...) 会把负值钳成 1），这里需要保留负号。
    shift_x = round(base * style.corner_shift_x / 1000)
    shift_y = round(base * style.corner_shift_y / 1000)

    # 文字右对齐基准点：照片右边缘往左缩进 right_margin，再叠加水平偏移
    right_x = frame + w - right_margin + shift_x

    # 两行间距
    gap = _px(base, 8)

    # 地点在署名上方（若有）
    if location:
        loc_baseline = frame + h - bottom_margin - (sig_asc + sig_desc) - gap + shift_y
        _draw_text(draw, (right_x, loc_baseline), location, f_loc,
                   style.text_secondary, anchor="rs")
    sig_baseline = frame + h - bottom_margin + shift_y
    if signature:
        _draw_text(draw, (right_x, sig_baseline), signature, f_sig,
                   style.text_primary, anchor="rs")

    return canvas


def _render_left_panel(img, style, fields):
    """左图右文参数表：照片在左，右侧留白区纵向排参数。

    右侧自上而下分组：
    - TakenAt / Location（日期、地点）
    - 分隔线
    - Focal / Aperture / Shutter / ISO（参数）
    - 分隔线
    - PhotoBy / ShotOn（署名、器材）
    标签浅灰右对齐，值深色左对齐，两列结构。底部品牌 logo（水平居中，fit-in-box）。
    """
    w, h = img.size
    base = min(w, h)

    model = fields.get("model", "")
    focal = fields.get("focal", "")
    fnumber = fields.get("fnumber", "")
    exposure = fields.get("exposure", "")
    iso = fields.get("iso", "")
    dt = fields.get("datetime", "")
    location = fields.get("location", "")
    signature = fields.get("signature", "") or style.signature

    # 日期简化为 "2019/04/13" 形式（去掉时分秒）
    dt = _simplify_datetime(dt)

    f_label = _load_font(FONT_SANS, _px(base, style.size_small))
    f_value = _load_font(FONT_SANS, _px(base, style.size_title))

    # 组装参数行：[(标签, 值), ...]
    groups = [
        [("TakenAt", dt), ("Location", location)],
        [("Focal", focal), ("Aperture", fnumber), ("Shutter", exposure), ("ISO", iso)],
        [("PhotoBy", signature), ("ShotOn", model)],
    ]
    groups = [[(lab, val) for lab, val in g if val] for g in groups]
    groups = [g for g in groups if g]

    # 动态计算面板宽度：标签最大宽 + 值最大宽 + 间距
    label_max_w = 0
    value_max_w = 0
    for g in groups:
        for lab, val in g:
            label_max_w = max(label_max_w, _text_w(f_label, lab))
            value_max_w = max(value_max_w, _text_w(f_value, val))
    col_gap = _px(base, 24)          # 标签与值之间间距
    panel_inner_w = label_max_w + col_gap + value_max_w

    frame = _px(base, style.frame_permille)
    panel_pad = _px(base, 36)        # 面板左右内边距

    panel_w = panel_inner_w + panel_pad * 2
    canvas_w = w + frame * 2 + panel_w
    canvas_h = h + frame * 2
    canvas = Image.new("RGB", (canvas_w, canvas_h), style.bar_bg)
    canvas.paste(img, (frame, frame))

    draw = ImageDraw.Draw(canvas)

    px0 = frame + w + panel_pad       # 面板内容左边界
    px1 = canvas_w - panel_pad        # 面板内容右边界
    mid_x = px0 + label_max_w + col_gap  # 标签/值分界（左标签右值）

    label_asc, label_desc = f_label.getmetrics()
    value_asc, value_desc = f_value.getmetrics()
    line_h = max(label_asc + label_desc, value_asc + value_desc)
    gap = _px(base, 18)           # 行距
    group_gap = _px(base, 40)     # 组间距

    # 底部 logo 占用高度（fit-in-box），参数表上方留出 logo 区
    logo_img = _load_logo_image(style.brand_image or style.logo_image)
    logo_box_h = 0
    if logo_img is not None:
        box = LOGO_BOX["left_panel"]
        # logo 允许最大宽度 = 面板内容宽度的 60%（参考截图：约占右侧栏 60%）
        max_w = _px(base, box["max_w"])
        max_h = _px(base, box["max_h"])
        trimmed = _trim_content(logo_img)
        ratio = min(max_w / trimmed.width, max_h / trimmed.height)
        logo_box_h = max(1, round(trimmed.height * ratio))

    # 计算参数表总高度（不含 logo），整体垂直居中于「参数表 + logo 区」
    total_h = 0
    for g in groups:
        total_h += line_h * len(g) + gap * (len(g) - 1) + group_gap
    total_h -= group_gap

    # logo 与参数表之间的间距
    logo_gap = _px(base, 30)
    logo_total = logo_box_h + logo_gap if logo_box_h else 0

    # 整块（参数表 + logo）在面板垂直居中
    content_total = total_h + logo_total
    y = frame + (canvas_h - frame * 2 - content_total) // 2 + line_h // 2

    for gi, g in enumerate(groups):
        for lab, val in g:
            _draw_text(draw, (mid_x, y), lab, f_label, style.text_secondary, anchor="rm")
            _draw_text(draw, (mid_x + col_gap, y), val, f_value, style.text_primary, anchor="lm")
            y += line_h + gap
        if gi < len(groups) - 1:
            y += group_gap // 2 - gap
            line_y = y - line_h // 2 - gap // 2
            draw.line([(px0, line_y), (px1, line_y)],
                      fill=style.divider_color, width=max(1, _px(base, 2)))
            y += group_gap // 2

    # 底部品牌 logo（水平居中于面板，fit-in-box 保证不超宽）
    if logo_img is not None:
        box = LOGO_BOX["left_panel"]
        max_w = _px(base, box["max_w"])
        max_h = _px(base, box["max_h"])
        logo_cx = (px0 + px1) // 2
        logo_cy = y + logo_gap + logo_box_h // 2
        _paste_logo_fit(canvas, logo_img, (logo_cx, logo_cy), max_w, max_h,
                        anchor="mm")

    return canvas


def _render_month_title(img, style, fields):
    """月份大标题式（杂志封面）：照片下方留白区，月份大标题 + 年份 + 参数，
    左下角品牌 logo。

    布局（下方信息栏，自上而下）：
    - 月份（大号，如 "September"）
    - 年份（强调色，如红色）
    - 参数行（f/5.6 75mm 1/8s ISO100）
    - 器材 / 地点 / 署名（小字右对齐）
    左下角品牌 logo（fit-in-box，不超显示空间）。
    """
    w, h = img.size
    base = min(w, h)

    model = fields.get("model", "")
    params = fields.get("params", "")
    dt = fields.get("datetime", "")
    location = fields.get("location", "")
    signature = fields.get("signature", "") or style.signature

    # 从日期提取月份（英文月份名）和年份
    month_name = style.month_name or ""
    year_text = style.year_text or ""
    if not month_name and dt:
        month_name = _month_from_datetime(dt)
    if not year_text and dt:
        year_text = _year_from_datetime(dt)

    f_month = _load_font(FONT_SANS, _px(base, style.size_month))
    f_year = _load_font(FONT_SANS, _px(base, style.size_small))
    f_param = _load_font(FONT_SANS, _px(base, style.size_title))
    f_small = _load_font(FONT_SANS, _px(base, style.size_small))

    # 信息栏高度：容纳标题+年份+参数+小字
    month_asc, month_desc = f_month.getmetrics()
    small_asc, small_desc = f_small.getmetrics()
    title_h = month_asc + month_desc
    small_h = small_asc + small_desc

    line_gap = _px(base, 20)
    pad_v = _px(base, 30)
    content_h = title_h + small_h + _px(base, style.size_title) + small_h + line_gap * 3
    bar = max(_px(base, style.bar_permille * 2), content_h + pad_v * 2)

    canvas, frame, base = _make_canvas(img, style, extra_h=bar)
    draw = ImageDraw.Draw(canvas)
    bar_top = frame + h
    canvas_w = canvas.width
    pad = _px(base, style.frame_permille)

    # 左侧：月份 + 年份
    left_x = pad
    cur_y = bar_top + pad_v
    if month_name:
        _draw_text(draw, (left_x, cur_y), month_name, f_month,
                   style.text_primary, anchor="lt")
        cur_y += title_h + line_gap
    if year_text:
        _draw_text(draw, (left_x, cur_y), year_text, f_year,
                   style.logo_color, anchor="lt")
        cur_y += small_h + line_gap

    # 右侧：参数 + 器材/地点/署名
    right_x = canvas_w - pad
    if params:
        _draw_text(draw, (right_x, bar_top + pad_v + title_h // 2), params, f_param,
                   style.text_primary, anchor="rm")
    # 器材/地点/署名（右对齐三行）
    meta_lines = [x for x in (model, location, signature) if x]
    meta_y = bar_top + pad_v + title_h + line_gap + small_h // 2
    for line in meta_lines:
        _draw_text(draw, (right_x, meta_y), line, f_small,
                   style.text_secondary, anchor="rm")
        meta_y += small_h + _px(base, 8)

    # 左下角品牌 logo（fit-in-box：圆标直径约 11-12% 短边，文字 logo 按同宽度约束）
    logo_img = _load_logo_image(style.brand_image or style.logo_image)
    if logo_img is not None:
        box = LOGO_BOX["month_title"]
        max_w = _px(base, box["max_w"])
        max_h = _px(base, box["max_h"])
        logo_x = pad + _px(base, 10)   # 略向右缩进，避免贴边/出界
        logo_y = bar_top + bar - pad_v  # 信息栏底部（左中对齐）
        _paste_logo_fit(canvas, logo_img, (logo_x, logo_y), max_w, max_h,
                        anchor="lm")

    return canvas


_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _month_from_datetime(dt: str) -> str:
    """从日期字符串提取英文月份名。支持 '2023:09:19 12:00:00'、'2019/04/13' 等格式。"""
    import re
    m = re.search(r"(\d{4})[:\-/](\d{1,2})[:\-/](\d{1,2})", dt)
    if m:
        month = int(m.group(2))
        if 1 <= month <= 12:
            return _MONTH_NAMES[month - 1]
    return ""


def _year_from_datetime(dt: str) -> str:
    """从日期字符串提取年份。支持 '2023:09:19'、'2019/04/13' 等格式。"""
    import re
    m = re.search(r"(\d{4})[:\-/](\d{1,2})[:\-/](\d{1,2})", dt)
    if m:
        return m.group(1)
    return ""


def _simplify_datetime(dt: str) -> str:
    """把 EXIF 日期简化为 '2019/04/13' 形式，去掉时分秒（参数表里更简洁）。"""
    import re
    m = re.search(r"(\d{4})[:\-/](\d{1,2})[:\-/](\d{1,2})", dt)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return dt


def make_fields(model="", params="", datetime="", location="", signature="",
                focal="", fnumber="", exposure="", iso="") -> dict:
    """便捷构造 fields dict。"""
    return {
        "model": model,
        "params": params,
        "datetime": datetime,
        "location": location,
        "signature": signature,
        "focal": focal,
        "fnumber": fnumber,
        "exposure": exposure,
        "iso": iso,
    }
