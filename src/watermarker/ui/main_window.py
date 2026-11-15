"""主窗口：三栏布局 + 完整参数面板 + 批量导出。

布局：
- 左：文件列表（支持拖拽导入）
- 中：实时预览
- 右：参数面板（水印设置[文字/图片水印/版式] + 模版 + 导出设置）
- 底：导出栏（输出目录 + 导出按钮 + 进度条 + 取消）+ 预设保存/加载

架构约定：ui 层只做"取值 → 调 core → 刷新预览"，不做图像处理。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
    Qt,
)
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core import config as cfg
from ..core.crop import RATIOS
from ..core.exif import read_exif, exif_summary
from ..core.image_io import open_image, list_images
from ..core.info_bar import (
    BRAND_LOGOS,
    COLOR_SCHEMES,
    InfoBarStyle,
    add_info_bar,
)
from ..core.watermark import (
    ImageWatermark,
    TextWatermark,
    add_image_watermark,
    add_text_watermark,
)
from .worker import ExportWorker
from .preview_worker import PreviewWorker, GalleryThumbWorker
from .icons import icon as _icon
from ..resources import resource_path

FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"

# 图片文件扩展名（拖拽导入时过滤）
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}

# 九宫格位置（顺序与 3x3 网格对应，供可视化位置选择器使用）
POSITIONS = ["左上", "中上", "右上", "左中", "正中", "右中", "左下", "中下", "右下"]

# 字体映射：界面名 -> 字体文件路径
#   前两个是 macOS 系统字体（绝对路径）；后四个是打包进 App 的开源字体（resource_path 定位）。
#   跨平台：macOS 用系统字体；Windows/Linux 时前两个回退到开源字体（MiSans 无衬线 / 思源宋体衬线）。
import sys as _sys
if _sys.platform == "darwin":
    _SANS_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"
    _SERIF_PATH = "/System/Library/Fonts/Supplemental/Songti.ttc"
else:
    _SANS_PATH = str(resource_path("assets", "fonts", "MiSans-Regular.ttf"))
    _SERIF_PATH = str(resource_path("assets", "fonts", "SourceHanSerifCN-Regular.otf"))

FONT_MAP = {
    "冬青黑体 (Hiragino Sans GB)": _SANS_PATH,
    "宋体 (Songti)": _SERIF_PATH,
    "MiSans 常规": str(resource_path("assets", "fonts", "MiSans-Regular.ttf")),
    "MiSans 粗体": str(resource_path("assets", "fonts", "MiSans-Bold.ttf")),
    "思源宋体 常规": str(resource_path("assets", "fonts", "SourceHanSerifCN-Regular.otf")),
    "思源宋体 粗体": str(resource_path("assets", "fonts", "SourceHanSerifCN-Bold.otf")),
}

# ===== 统一模版引擎：布局骨架 + 品牌 logo + 配色方案 三者正交，自由组合 =====

# 布局骨架：界面名 -> layout 值（info_bar.py 的渲染函数）
LAYOUT_CHOICES = {
    "不启用": None,
    "左 α Logo": "left_logo",        # α 在左，左=型号+参数，右=地点+日期
    "居中字标": "center",             # 全居中，logo+参数+地点日期三行
    "三段式": "three_col",            # 左中右三段式，中=logo
    "右下署名": "corner_sign",        # 无信息条，右下角署名/地点
    "左图右文参数表": "left_panel",    # 照片在左，右侧纵向参数表
    "月份大标题": "month_title",      # 杂志封面式，月份大标题+左下logo
}

# 每个布局骨架支持的自定义字段（动态显示/隐藏署名、地点输入框）
# 依据 info_bar.py 各渲染函数实际读取的字段：
#   - left_logo / center / month_title  用 location，不用 signature
#   - three_col                         用 signature，不用 location
#   - corner_sign                       用 signature + location
#   - left_panel                        用 signature + location（PhotoBy/ShotOn + Location）
LAYOUT_FIELD_SUPPORT = {
    None: {"signature": False, "location": False},
    "left_logo": {"signature": False, "location": True},
    "center": {"signature": False, "location": True},
    "three_col": {"signature": True, "location": False},
    "corner_sign": {"signature": True, "location": True},
    "left_panel": {"signature": True, "location": True},
    "month_title": {"signature": True, "location": True},
}


def _map_old_layout(old_name: str) -> str:
    """把旧版型名（A·左αLogo 等）映射到新布局骨架名，用于兼容旧预设文件。"""
    mapping = {
        "A · 左 α Logo": "左 α Logo",
        "B · 居中 SONY": "居中字标",
        "C · 三段式 α": "三段式",
        "D · 右下署名": "右下署名",
    }
    return mapping.get(old_name, "不启用")


# 模版画廊定义：分组名 -> [(显示名, 模板 key)]
# 模板 key 约定：
#   - "info:<layout>" 表示信息条模版（layout 为 info_bar 的布局值）
#   - "wm:text" / "wm:image" 表示水印模版（文字水印 / 图片水印）
TEMPLATE_GROUPS = [
    ("信息条模版", [
        ("左 α Logo", "info:left_logo"),
        ("居中字标", "info:center"),
        ("三段式", "info:three_col"),
        ("右下署名", "info:corner_sign"),
        ("左图右文参数表", "info:left_panel"),
        ("月份大标题", "info:month_title"),
    ]),
    ("水印模版", [
        ("文字水印", "wm:text"),
        ("图片水印", "wm:image"),
    ]),
]


# 默认参数（一键恢复默认用）。值需与 _build_params_panel 中各控件初始值一致。
DEFAULT_PARAMS = {
    "text_enabled": False,
    "text": "© 我的名字",
    "size_permille": 36,
    "opacity": 0.7,         # 不透明度（0~1，与 _collect_params_dict 一致）
    "color": (255, 255, 255),
    "stroke": True,
    "stroke_width": 1,
    "rotation": 0,
    "margin": 24,
    "position": "右下",
    "image_enabled": False,
    "logo_path": "",
    "tiled_enabled": False,
    "tiled_spacing": 300,
    "crop": "不裁剪",
    "info_layout": "不启用",
    "info_brand": "α 符号",
    "info_scheme": "白底黑字",
    "info_signature": "",
    "info_location": "",
    "corner_shift_x": 0,
    "corner_shift_y": 0,
    "format": "原格式",
    "quality": 92,
    "keep_exif": True,
}


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    """把 Pillow 图转成 Qt 可显示的 QPixmap。

    注意：Pillow 13 移除了 Image.stride 属性，这里显式计算每行字节数。
    """
    if img.mode == "RGBA":
        fmt = QImage.Format_RGBA8888
        raw = img.tobytes("raw", "RGBA")
    else:
        img = img.convert("RGB")
        fmt = QImage.Format_RGB888
        raw = img.tobytes("raw", "RGB")

    channels = 4 if fmt == QImage.Format_RGBA8888 else 3
    qimg = QImage(raw, img.width, img.height, img.width * channels, fmt)
    return QPixmap.fromImage(qimg.copy())  # 深拷贝，防止 raw 被回收


def _make_badge_pixmap() -> QPixmap:
    """生成文件列表的「已单独设置模版」徽标（一个实心小圆点 + 外圈）。

    用程序绘制而非资源文件，避免引入图标依赖；颜色用主题强调蓝 #5B8DEF。
    """
    from PySide6.QtGui import QPainter, QPen
    dpr = 2  # 2x 高分辨率，适配 Retina
    size = 12 * dpr
    pm = QPixmap(size, size)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    center = size / 2
    # 外圈（浅色描边，深色背景下更醒目）
    p.setPen(QPen(QColor(255, 255, 255, 200), 1.0 * dpr))
    p.setBrush(QColor("#5B8DEF"))
    r = 4.5 * dpr
    p.drawEllipse(int(center - r), int(center - r), int(r * 2), int(r * 2))
    p.end()
    return pm


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Albert水印工坊")

        # 初始尺寸：按屏幕可用区域兜底，避免底部伸出到 Dock 被挡住
        screen = self.screen() or QApplication.primaryScreen()
        avail = screen.availableGeometry()  # 已扣除菜单栏和 Dock 的可用区域
        w = min(1180, avail.width())
        h = min(760, avail.height())
        self.resize(w, h)
        # 给窗口设一个最小尺寸（够用即可，别太大导致无法上下缩放）
        self.setMinimumSize(900, 520)

        self._img: Image.Image | None = None
        self._img_path: str = ""
        self._files: list[str] = []       # 所有已加载图片的完整路径
        self._logo_path: str = ""         # 图片水印路径
        self._worker: ExportWorker | None = None
        self._output_dir: str = self._default_output_dir()  # 默认输出目录（自动创建）
        self._text_color: tuple[int, int, int] = (255, 255, 255)  # 当前文字颜色
        self._preview_zoom: float = 1.0  # 预览缩放因子（相对「适应窗口」，1.0=完整显示）
        self._light_theme: bool = False  # 当前是否浅色主题

        # 预览后台渲染相关
        self._preview_worker: PreviewWorker | None = None
        self._preview_seq: int = 0        # 预览任务序号，用于丢弃过时结果
        self._preview_workers: list[PreviewWorker] = []  # 持有所有活跃 worker 引用，防止线程运行中被 GC
        self._preview_full_img: Image.Image | None = None  # 缓存的完整预览图（fit 缩放用）

        # 画廊缩略图后台渲染相关（切换文件时不阻塞主线程）
        self._gallery_worker: GalleryThumbWorker | None = None
        # 画廊缩略图 fit 防抖：窗口缩放时 resize 高频触发，合并后统一重新 fit，
        # 避免每帧都对 8 张缩略图做 SmoothTransformation 缩放造成卡顿
        self._thumb_fit_timer = QTimer(self)
        self._thumb_fit_timer.setSingleShot(True)
        self._thumb_fit_timer.setInterval(60)
        self._thumb_fit_timer.timeout.connect(self._fit_all_thumbs)
        # 防抖定时器：文字输入/滑块拖动后延迟刷新，避免每敲一个字都重算
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._on_preview_edit)

        # 当前选中的布局（由中间模版画廊维护，替代原「布局骨架」下拉框）
        self._layout_name = "不启用"

        # 每图独立参数：dict[文件路径 -> 参数字典]。默认所有图继承当前全局参数，
        # 只有对某张图单独改过的参数才写入独立快照；切换文件时保存/恢复。
        self._per_image_params: dict[str, dict] = {}
        self._last_img_path: str = ""  # 上次选中的图路径，用于切换时保存快照

        # 文件列表徽标：标记「已单独设置模版」的图（程序生成的小圆点，避免依赖资源文件）
        self._badge_pixmap = _make_badge_pixmap()

        self._build_ui()
        self._connect()

        # 初始化模版字段显示（默认"不启用"时隐藏署名/地点）
        self._update_info_bar_fields()

        # 初始化画廊卡片（空状态占位；导入图片后刷新缩略图）
        self._populate_gallery()

        # 编辑面板默认隐藏
        self._editor_visible = False
        self.editor_panel.hide()

        # 文件列表空状态提示随列表尺寸变化
        self.file_list.installEventFilter(self)
        # 预览框尺寸变化时重新 fit（窗口缩放/编辑面板滑入滑出）
        self.preview.installEventFilter(self)

        # 启用拖拽导入（整个窗口可接收拖入的图片）
        self.setAcceptDrops(True)

    # ---------- 事件 ----------
    def eventFilter(self, obj, event):
        """文件列表空状态跟随尺寸；预览框/缩略图尺寸变化时重新 fit。"""
        from PySide6.QtCore import QEvent
        if obj is self.file_list and event.type() == QEvent.Resize:
            self.file_list_empty.setGeometry(self.file_list.rect())
        elif obj is self.preview and event.type() == QEvent.Resize:
            # 预览框尺寸变了，重新按新尺寸 fit（若已有缓存预览图）
            if getattr(self, "_preview_full_img", None):
                self._fit_preview_to_window()
        elif obj is self.gallery_scroll and event.type() == QEvent.Resize:
            # 画廊可视宽度变化（编辑面板滑入/滑出、窗口缩放）→ 防抖后统一 fit
            self._thumb_fit_timer.start()
        elif event.type() == QEvent.Resize:
            # 画廊缩略图 label 尺寸变化：防抖后重新 fit（找对应卡片）
            for card in self.template_cards.values():
                if obj is card._thumb_label and card._full_pm is not None:
                    self._thumb_fit_timer.start()
                    break
        return super().eventFilter(obj, event)

    def _fit_all_thumbs(self):
        """重新 fit 所有已渲染缩略图（防抖合并后的统一入口）。"""
        for card in self.template_cards.values():
            if card._full_pm is not None and not card._full_pm.isNull():
                self._fit_thumb(card)

    # ---------- 主题切换 ----------
    def _toggle_theme(self):
        """在深色/浅色主题间切换，并同步图标、预览区颜色。"""
        self._light_theme = not self._light_theme
        app = QApplication.instance()
        from ..app import _load_theme
        _load_theme(app, light=self._light_theme)

        # 更新预览区背景色（浅色用半透明白，深色用半透明深灰，模拟毛玻璃）
        if self._light_theme:
            self.preview.setStyleSheet(
                "background: rgba(255,255,255,0.45); color:#888; "
                "border: 1px solid rgba(0,0,0,0.05); border-radius:10px;")
            self.theme_btn.setText("深色")
        else:
            self.preview.setStyleSheet(
                "background: rgba(30,30,30,0.55); color:#888; "
                "border: 1px solid rgba(255,255,255,0.06); border-radius:10px;")
            self.theme_btn.setText("浅色")

        # 重设图标颜色（浅色主题用深色图标，深色主题用浅色图标）
        self._apply_icons()

        # 无图片时，空状态提示文字颜色随主题适配
        if self._img is None:
            self.preview.setText(self._empty_preview_html())

    def _apply_icons(self):
        """按当前主题重设所有按钮图标颜色。"""
        color = "#2A2A2A" if self._light_theme else "#E6E6E6"
        export_color = "#1C3A6B" if self._light_theme else "#FFFFFF"

        self.open_btn.setIcon(_icon("image", color=color))
        self.add_btn.setIcon(_icon("add", color=color))
        self.folder_btn.setIcon(_icon("folder", color=color))
        self.remove_btn.setIcon(_icon("trash", color=color))
        self.up_btn.setIcon(_icon("up", color=color))
        self.down_btn.setIcon(_icon("down", color=color))
        self.clear_btn.setIcon(_icon("clear", color=color))
        self.zoom_out_btn.setIcon(_icon("zoom_out", color=color))
        self.zoom_in_btn.setIcon(_icon("zoom_in", color=color))
        self.zoom_fit_btn.setIcon(_icon("zoom_fit", color=color))
        self.output_btn.setIcon(_icon("export_dir", color=color))
        self.cancel_btn.setIcon(_icon("cancel", color=color))
        self.export_btn.setIcon(_icon("export", color=export_color))
        self.theme_btn.setIcon(_icon("moon", color=color))
        self.info_btn.setIcon(_icon("info", color=color))

    def _show_settings(self):
        """打开「关于 / 开源字体授权」对话框。"""
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()

    # ---------- 界面搭建 ----------
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("mainRoot")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # 主体三栏
        body = QHBoxLayout()

        # ① 左：文件列表
        left = QVBoxLayout()
        self.open_btn = QPushButton("选择图片…")
        self.open_btn.setIcon(_icon("image"))
        self.add_btn = QPushButton("追加图片…")
        self.add_btn.setIcon(_icon("add"))
        self.folder_btn = QPushButton("选择文件夹…")
        self.folder_btn.setIcon(_icon("folder"))
        left.addWidget(self.open_btn)
        left.addWidget(self.add_btn)
        left.addWidget(self.folder_btn)

        # 列表管理行：移除 / 上移 / 下移 / 清空
        manage_row = QHBoxLayout()
        self.remove_btn = QPushButton("移除")
        self.remove_btn.setIcon(_icon("trash"))
        self.up_btn = QPushButton("")
        self.up_btn.setIcon(_icon("up"))
        self.up_btn.setToolTip("上移")
        self.down_btn = QPushButton("")
        self.down_btn.setIcon(_icon("down"))
        self.down_btn.setToolTip("下移")
        self.clear_btn = QPushButton("清空")
        self.clear_btn.setIcon(_icon("clear"))
        for b in (self.remove_btn, self.up_btn, self.down_btn, self.clear_btn):
            manage_row.addWidget(b)
        left.addLayout(manage_row)

        self.file_list = QListWidget()
        left.addWidget(self.file_list)

        # 文件列表空状态（覆盖提示，有文件时隐藏）
        self.file_list_empty = QLabel("尚未添加图片\n点「选择图片」或拖入文件夹")
        self.file_list_empty.setObjectName("emptyHint")
        self.file_list_empty.setAlignment(Qt.AlignCenter)
        self.file_list_empty.setWordWrap(True)
        self.file_list_empty.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.file_list_empty.setParent(self.file_list)
        self.file_list_empty.setGeometry(self.file_list.rect())
        self.file_list_empty.show()

        # ② 中：模版画廊（上下滑动选择模版，单击进入编辑）
        mid = self._build_template_gallery()

        # ③ 右：编辑详情面板（默认隐藏，点击模版卡片时滑入显示）
        right = self._build_editor_panel()

        body.addLayout(left, 1)
        body.addLayout(mid, 4)
        body.addWidget(right, 0)  # 编辑面板用固定宽度 + 动画控制，不用 stretch
        root.addLayout(body, 1)

        # 底部：导出栏
        root.addLayout(self._build_export_bar())

    def _build_template_gallery(self) -> QVBoxLayout:
        """中间模版画廊：按分组展示每个模版的预览缩略图卡片，上下滚动选择。

        每个卡片 = 用第一张导入图渲染的缩略图（无名字，靠图本身传达模版样式）。
        缩略图铺满中间区域宽度、按真实比例自适应高度（横图矮、竖图高），大小不一但都完整显示。
        点击缩略图呼出右侧编辑面板。
        """
        mid = QVBoxLayout()

        # 顶部标题 + 提示（限宽居中）
        title = QLabel("选择模版")
        title.setObjectName("galleryTitle")
        title.setAlignment(Qt.AlignCenter)
        mid.addWidget(title)

        hint = QLabel("单击缩略图进入编辑 · 预览使用导入的第一张图片")
        hint.setObjectName("galleryHint")
        hint.setAlignment(Qt.AlignCenter)
        mid.addWidget(hint)

        # 画廊滚动区（卡片流，占满中间区域宽度，缩略图按实际宽度自适应 fit）
        self.gallery_scroll = QScrollArea()
        self.gallery_scroll.setObjectName("galleryScroll")
        self.gallery_scroll.setWidgetResizable(True)
        self.gallery_scroll.setFrameShape(QScrollArea.NoFrame)
        self.gallery_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        gallery_content = QWidget()
        gallery_content.setObjectName("galleryContent")
        self.gallery_layout = QVBoxLayout(gallery_content)
        self.gallery_layout.setContentsMargins(4, 4, 4, 4)
        self.gallery_layout.setSpacing(12)
        self.gallery_layout.addStretch(1)

        self.gallery_scroll.setWidget(gallery_content)
        # 画廊可视宽度变化时（如编辑面板滑入滑出），主动重新 fit 所有缩略图
        self.gallery_scroll.installEventFilter(self)
        mid.addWidget(self.gallery_scroll, 1)

        # 卡片字典：模板 key -> 卡片 widget（用于后续刷新缩略图/选中态）
        self.template_cards: dict[str, QWidget] = {}
        return mid

    def _build_editor_panel(self) -> QWidget:
        """右侧编辑详情面板：实时预览 + 参数编辑区（默认隐藏，点卡片滑入）。"""
        # 外层容器：用于控制显示/隐藏和滑入动画
        self.editor_panel = QWidget()
        self.editor_panel.setObjectName("editorPanel")
        # 用 maximumWidth 做滑入动画：初始宽度 0，显示时动画到目标宽度
        self.editor_panel.setMinimumWidth(0)
        self.editor_panel.setMaximumWidth(0)
        editor_lay = QVBoxLayout(self.editor_panel)
        editor_lay.setContentsMargins(0, 0, 0, 0)
        editor_lay.setSpacing(0)

        # 顶部：标题栏（当前模版名 + 关闭按钮）
        header = QHBoxLayout()
        self.editor_title = QLabel("编辑")
        self.editor_title.setObjectName("editorTitle")
        self.editor_close_btn = QPushButton("✕")
        self.editor_close_btn.setObjectName("editorCloseBtn")
        self.editor_close_btn.setToolTip("收起编辑面板")
        self.editor_close_btn.setFixedSize(28, 28)
        self.editor_close_btn.setCursor(Qt.PointingHandCursor)
        header.addWidget(self.editor_title)
        header.addStretch()
        header.addWidget(self.editor_close_btn)
        editor_lay.addLayout(header)

        # 中部：实时预览
        self.preview = QLabel("")
        self.preview.setObjectName("previewPane")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setTextFormat(Qt.RichText)
        self.preview.setText(self._empty_preview_html())
        self.preview.setMinimumSize(360, 160)
        self.preview.setStyleSheet(
            "background: rgba(30, 30, 30, 0.55); color:#888; "
            "border: 1px solid rgba(255,255,255,0.06); border-radius:10px;")
        editor_lay.addWidget(self.preview, 3)

        # 预览缩放控件
        zoom_row = QHBoxLayout()
        self.zoom_out_btn = QPushButton("")
        self.zoom_out_btn.setIcon(_icon("zoom_out"))
        self.zoom_out_btn.setToolTip("缩小")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.zoom_label.setMinimumWidth(48)
        self.zoom_in_btn = QPushButton("")
        self.zoom_in_btn.setIcon(_icon("zoom_in"))
        self.zoom_in_btn.setToolTip("放大")
        self.zoom_fit_btn = QPushButton("适应窗口")
        self.zoom_fit_btn.setIcon(_icon("zoom_fit"))
        zoom_row.addStretch()
        zoom_row.addWidget(self.zoom_out_btn)
        zoom_row.addWidget(self.zoom_label)
        zoom_row.addWidget(self.zoom_in_btn)
        zoom_row.addWidget(self.zoom_fit_btn)
        zoom_row.addStretch()
        editor_lay.addLayout(zoom_row)

        # 底部：参数编辑区（复用原有 params panel）
        self.params_scroll = self._build_params_panel()
        editor_lay.addWidget(self.params_scroll, 5)

        return self.editor_panel

    # ---------- 模版画廊 ----------
    def _populate_gallery(self):
        """构建画廊卡片（每个模版一张卡片：缩略图 + 名称）。"""
        # 清空旧的卡片（除了末尾的 stretch）
        for key, card in list(self.template_cards.items()):
            self.gallery_layout.removeWidget(card)
            card.deleteLater()
        self.template_cards.clear()

        for group_name, templates in TEMPLATE_GROUPS:
            # 分组标题
            group_label = QLabel(group_name)
            group_label.setObjectName("galleryGroupLabel")
            self.gallery_layout.insertWidget(self.gallery_layout.count() - 1, group_label)

            for name, tkey in templates:
                card = self._build_template_card(name, tkey)
                self.template_cards[tkey] = card
                self.gallery_layout.insertWidget(self.gallery_layout.count() - 1, card)

        # 立即尝试渲染缩略图（若已有第一张图）
        self._refresh_gallery_thumbs()

    def _build_template_card(self, name: str, tkey: str) -> QWidget:
        """构建单张模版卡片：只有缩略图（无名字），点击缩略图呼出编辑面板。

        缩略图按卡片实际宽度自适应 fit：横图铺满宽度（矮）、竖图铺满宽度（高），
        大小不一但都完整显示。
        """
        card = QWidget()
        card.setObjectName("templateCard")
        card.setCursor(Qt.PointingHandCursor)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(0)

        # 缩略图标签：占满卡片宽度，图片按真实比例 fit 显示
        thumb = QLabel("")
        thumb.setObjectName("templateThumb")
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setMinimumHeight(80)
        # 关键：水平方向用 Ignored 策略，让 label 忽略 pixmap 的 sizeHint 宽度，
        # 跟随父容器收缩（否则 pixmap 会撑大 gallery_content 导致横向溢出、不重新 fit）
        thumb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        thumb.setTextFormat(Qt.RichText)
        thumb.setText('<div style="color:#888; font-size:12px;">导入图片后显示预览</div>')
        lay.addWidget(thumb)

        # 保存引用，供刷新缩略图
        card._thumb_label = thumb
        card._full_pm = None  # 缓存的完整清晰缩略图（fit 缩放用）
        card._tkey = tkey

        # 缩略图尺寸变化时重新 fit（画廊宽度随窗口变化）
        thumb.installEventFilter(self)

        # 点击缩略图呼出编辑面板（整张卡片也可点击）
        thumb.mousePressEvent = lambda e, k=tkey, n=name: self._on_template_clicked(k, n)
        card.mousePressEvent = lambda e, k=tkey, n=name: self._on_template_clicked(k, n)
        return card

    def _on_template_clicked(self, tkey: str, name: str):
        """点击模版卡片：联动选中对应参数，并滑出右侧编辑面板。"""
        # 联动选中对应参数（信息条模版 → 切换布局；水印模版 → 启用水印、清信息条）
        if tkey.startswith("info:"):
            layout = tkey.split(":", 1)[1]
            layout_name = "不启用" if layout == "none" else self._layout_name_from_value(layout)
            if layout_name in LAYOUT_CHOICES:
                self._layout_name = layout_name
                self._update_info_bar_fields()
            # 聚焦「模版」编辑区
            self._focus_section("模版")
        elif tkey == "wm:text":
            # 文字水印模版：启用文字水印，并清除信息条布局（避免残留叠加）
            self._layout_name = "不启用"
            self._update_info_bar_fields()
            self.text_enabled.setChecked(True)
            self._focus_section("水印设置")
        elif tkey == "wm:image":
            # 图片水印模版：启用图片水印，并清除信息条布局
            self._layout_name = "不启用"
            self._update_info_bar_fields()
            self.image_enabled.setChecked(True)
            self._focus_section("水印设置")

        # 高亮当前卡片
        self._highlight_card(tkey)

        # 滑出编辑面板
        self._show_editor(name)
        # 模板点击是低频单次操作，直接同步写入当前图快照 + 刷新预览，
        # 不走防抖定时器（否则用户点完模板立即切图/导出时，快照可能因
        # 120ms 防抖未到期而丢失，导致多图不同模板导出成同一种——bug）。
        self._on_preview_edit()

    def _layout_name_from_value(self, layout: str) -> str:
        """布局值 -> 界面名（LAYOUT_CHOICES 反向查找）。"""
        for name, val in LAYOUT_CHOICES.items():
            if val == layout:
                return name
        return "不启用"

    def _highlight_card(self, tkey: str):
        """高亮选中的模版卡片，取消其他卡片高亮。"""
        for k, card in self.template_cards.items():
            if k == tkey:
                card.setProperty("selected", True)
            else:
                card.setProperty("selected", False)
            card.style().unpolish(card)
            card.style().polish(card)

    def _show_editor(self, name: str):
        """滑出右侧编辑面板（带呼出动画），默认适应窗口完整显示预览。"""
        self.editor_title.setText(name)
        if not self._editor_visible:
            self._editor_visible = True
            # 弹出编辑面板时，预览默认「适应窗口」完整显示（fit 到预览框）
            self._preview_zoom = 1.0
            self.zoom_label.setText("适应窗口")
            self.editor_panel.show()
            self._animate_editor(0, self._editor_width())

    def _hide_editor(self):
        """收起右侧编辑面板。"""
        if self._editor_visible:
            self._editor_visible = False
            self._animate_editor(self.editor_panel.maximumWidth(), 0,
                                 on_done=self.editor_panel.hide)

    def _editor_width(self) -> int:
        """编辑面板目标宽度（约等于右侧参数面板宽度）。"""
        return 460

    def _animate_editor(self, start_w: int, end_w: int, on_done=None):
        """编辑面板宽度滑入/滑出动画。"""
        self._editor_anim = QPropertyAnimation(self.editor_panel, b"maximumWidth")
        self._editor_anim.setDuration(220)
        self._editor_anim.setStartValue(start_w)
        self._editor_anim.setEndValue(end_w)
        self._editor_anim.setEasingCurve(QEasingCurve.OutCubic)
        if on_done is not None:
            self._editor_anim.finished.connect(on_done)
        self._editor_anim.start()

    def _refresh_gallery_thumbs(self):
        """用第一张导入图在后台渲染所有模版缩略图（不阻塞主线程）。

        8 个模版逐个渲染，每完成一个通过信号回传一张 PIL 图，
        主线程转 QPixmap 并贴到对应卡片（转图/贴图很快，几乎无感）。
        渲染前取消上一批未完成的 worker，避免旧图覆盖新图。
        """
        if self._img is None:
            return
        # 取消上一批
        if self._gallery_worker is not None:
            self._gallery_worker.cancel()
            self._gallery_worker = None

        # 快照渲染所需的全部输入（worker 只读这些，不碰 UI）
        fields = self._thumb_fields()
        text = self.text_edit.text()
        font_path = FONT_MAP[self.font_combo.currentText()]
        demo_logo = str(resource_path("assets", "icons", "alpha-orange.png"))
        tkeys = list(self.template_cards.keys())

        worker = GalleryThumbWorker(
            img=self._img,
            fields=fields,
            text=text,
            font_path=font_path,
            demo_logo_path=demo_logo,
            tkeys=tkeys,
        )
        worker.thumb_ready.connect(self._on_gallery_thumb_ready)
        worker.all_done.connect(lambda w=worker: self._on_gallery_done(w))
        self._gallery_worker = worker
        worker.start()

    def _on_gallery_thumb_ready(self, tkey: str, pil_img: Image.Image):
        """收到一张后台渲染好的缩略图：转 QPixmap 并贴到对应卡片。"""
        card = self.template_cards.get(tkey)
        if card is None:
            return
        pm = pil_to_qpixmap(pil_img)
        card._full_pm = pm  # 缓存完整高清图，供 resize 时重新 fit
        self._fit_thumb(card)

    def _on_gallery_done(self, worker: GalleryThumbWorker):
        """画廊缩略图渲染结束，清理引用。"""
        if self._gallery_worker is worker:
            self._gallery_worker = None
        worker.deleteLater()

    def _fit_thumb(self, card: QWidget):
        """把缓存的完整缩略图按画廊实际可视宽度等比缩放（fit-in-width）。

        横图铺满宽度（矮）、竖图铺满宽度（高），保持真实长宽比，完整显示。
        目标宽度优先取画廊可视宽度（减去卡片/边距），保证缩略图始终贴合
        画廊当前宽度（编辑面板滑入滑出、窗口缩放时都能正确自适应）。
        """
        thumb = card._thumb_label
        pm = card._full_pm
        if pm is None or pm.isNull():
            return
        # 目标宽度：画廊可视宽度 - 左右边距（4px margin × 2 + 卡片 6px margin × 2）
        tw = self.gallery_scroll.viewport().width() - 20
        # 兜底：若画廊尚未布局完成，退回用 label 自身宽度
        if tw <= 0:
            tw = thumb.width()
        if tw <= 0:
            return
        # 按宽度等比缩放（高度自适应，保持真实比例）
        target_h = max(1, round(pm.height() * tw / pm.width()))
        thumb.setPixmap(pm.scaled(
            tw, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ))
        # 让 label 高度跟随图片高度，避免上下留白
        thumb.setMinimumHeight(target_h)
        thumb.setMaximumHeight(target_h)

    def _thumb_fields(self) -> dict:
        """画廊缩略图用的模拟字段（EXIF 缺失时用占位示例，保证布局可预览）。"""
        if self._img_path:
            ex = read_exif(self._img_path)
        else:
            ex = {}
        return {
            "model": ex.get("model", "") or "ILCE-6300",
            "params": exif_summary(self._img_path) if self._img_path else "35mm f/2.8 1/200s ISO100",
            "datetime": ex.get("datetime", "") or "2023.09.19",
            "location": self.info_loc_edit.text().strip() or "London",
            "signature": self.info_sig_edit.text().strip() or "© 我的名字",
            "focal": ex.get("focal", "") or "35mm",
            "fnumber": ex.get("fnumber", "") or "f/2.8",
            "exposure": ex.get("exposure", "") or "1/200s",
            "iso": ex.get("iso", "") or "100",
        }

    def _build_params_panel(self) -> QWidget:
        """右侧参数面板：按语义分组为可折叠 section（自定义折叠容器）。

        分组（自上而下）：
        1. 水印设置    —— 文字水印 + 图片水印 + 版式（合并为一个分组，内部子标题分区）
        2. 模版        —— 版型/署名/地点/位置微调
        3. 导出设置    —— 格式/质量/EXIF/预设
        """
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 折叠分组的容器布局（标题 + 内容交替排列）
        self._sections_layout = QVBoxLayout()
        self._sections_layout.setContentsMargins(0, 0, 0, 0)
        self._sections_layout.setSpacing(0)
        lay.addLayout(self._sections_layout)

        # ① 水印设置（合并：文字水印 + 图片水印 + 版式）
        sec_watermark = self._add_section("水印设置")

        # ---- 文字水印 ----
        sec_watermark.addWidget(self._subsection_label("文字水印"))
        self.text_enabled = QCheckBox("启用文字水印")
        self.text_enabled.setChecked(False)
        sec_watermark.addWidget(self.text_enabled)
        sec_watermark.addWidget(self._field_label("文字内容"))
        self.text_edit = QLineEdit("© 我的名字")
        sec_watermark.addWidget(self.text_edit)
        sec_watermark.addWidget(self._field_label("字体"))
        self.font_combo = QComboBox()
        self.font_combo.addItems(list(FONT_MAP.keys()))
        sec_watermark.addWidget(self.font_combo)
        sec_watermark.addWidget(self._field_label("字号"))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(10, 100)
        self.size_slider.setValue(36)
        sec_watermark.addWidget(self.size_slider)
        sec_watermark.addWidget(self._field_label("透明度"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(70)
        sec_watermark.addWidget(self.opacity_slider)

        color_row = QHBoxLayout()
        color_row.addWidget(self._field_label("颜色"))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(28, 28)
        self.color_btn.setToolTip("点击选择文字颜色")
        color_row.addWidget(self.color_btn)
        self.color_hex_label = QLabel("#FFFFFF")
        color_row.addWidget(self.color_hex_label)
        color_row.addStretch()
        self.stroke_check = QCheckBox("描边")
        self.stroke_check.setChecked(True)
        color_row.addWidget(self.stroke_check)
        sec_watermark.addLayout(color_row)
        self._sync_color_btn()

        stroke_row = QHBoxLayout()
        stroke_row.addWidget(self._field_label("描边粗细"))
        self.stroke_spin = QSpinBox()
        self.stroke_spin.setRange(0, 10)
        self.stroke_spin.setValue(1)
        stroke_row.addWidget(self.stroke_spin)
        stroke_row.addStretch()
        sec_watermark.addLayout(stroke_row)

        # ---- 图片水印 ----
        sec_watermark.addWidget(self._subsection_label("图片水印"))
        self.image_enabled = QCheckBox("启用图片水印 (Logo)")
        sec_watermark.addWidget(self.image_enabled)
        self.logo_btn = QPushButton("选择 Logo 图片…")
        self.logo_btn.setEnabled(False)
        sec_watermark.addWidget(self.logo_btn)
        self.logo_label = QLabel("未选择")
        self.logo_label.setWordWrap(True)
        sec_watermark.addWidget(self.logo_label)

        self.tiled_enabled = QCheckBox("平铺水印 (防泄密)")
        sec_watermark.addWidget(self.tiled_enabled)
        tiled_row = QHBoxLayout()
        tiled_row.addWidget(self._field_label("间距"))
        self.tiled_spacing_slider = QSlider(Qt.Horizontal)
        self.tiled_spacing_slider.setRange(100, 800)
        self.tiled_spacing_slider.setValue(300)
        tiled_row.addWidget(self.tiled_spacing_slider, 1)
        sec_watermark.addLayout(tiled_row)

        # ---- 版式 ----
        sec_watermark.addWidget(self._subsection_label("版式"))
        sec_watermark.addWidget(self._field_label("位置"))
        self.position_grid = self._build_position_grid()
        sec_watermark.addWidget(self.position_grid)

        rot_row = QHBoxLayout()
        rot_row.addWidget(self._field_label("旋转"))
        self.rotation_slider = QSlider(Qt.Horizontal)
        self.rotation_slider.setRange(-90, 90)
        self.rotation_slider.setValue(0)
        rot_row.addWidget(self.rotation_slider, 1)
        self.rotation_label = QLabel("0°")
        self.rotation_label.setMinimumWidth(36)
        rot_row.addWidget(self.rotation_label)
        sec_watermark.addLayout(rot_row)

        margin_row = QHBoxLayout()
        margin_row.addWidget(self._field_label("边距"))
        self.margin_slider = QSlider(Qt.Horizontal)
        self.margin_slider.setRange(0, 200)
        self.margin_slider.setValue(24)
        margin_row.addWidget(self.margin_slider, 1)
        self.margin_label = QLabel("24")
        self.margin_label.setMinimumWidth(36)
        margin_row.addWidget(self.margin_label)
        sec_watermark.addLayout(margin_row)

        sec_watermark.addWidget(self._field_label("比例裁剪"))
        self.crop_combo = QComboBox()
        self.crop_combo.addItems(list(RATIOS.keys()))
        self.crop_combo.setCurrentText("不裁剪")
        sec_watermark.addWidget(self.crop_combo)

        # ② 模版（统一模版引擎：布局由中间画廊选择，这里仅保留品牌 logo + 配色方案）
        sec_template = self._add_section("模版")

        sec_template.addWidget(self._field_label("品牌 Logo"))
        self.brand_combo = QComboBox()
        self.brand_combo.addItems(list(BRAND_LOGOS.keys()))
        self.brand_combo.setCurrentText("α 符号")
        sec_template.addWidget(self.brand_combo)

        sec_template.addWidget(self._field_label("配色方案"))
        self.scheme_combo = QComboBox()
        self.scheme_combo.addItems(list(COLOR_SCHEMES.keys()))
        self.scheme_combo.setCurrentText("白底黑字")
        sec_template.addWidget(self.scheme_combo)

        self.sig_row = QWidget()
        sig_row = QHBoxLayout(self.sig_row)
        sig_row.setContentsMargins(0, 0, 0, 0)
        sig_row.addWidget(self._field_label("署名"))
        self.info_sig_edit = QLineEdit("")
        self.info_sig_edit.setPlaceholderText("如：Foto by 我的名字")
        sig_row.addWidget(self.info_sig_edit, 1)
        sec_template.addWidget(self.sig_row)

        self.loc_row = QWidget()
        loc_row = QHBoxLayout(self.loc_row)
        loc_row.setContentsMargins(0, 0, 0, 0)
        loc_row.addWidget(self._field_label("地点"))
        self.info_loc_edit = QLineEdit("")
        self.info_loc_edit.setPlaceholderText("如：Gdańsk, Poland（无 GPS 时手动填）")
        loc_row.addWidget(self.info_loc_edit, 1)
        sec_template.addWidget(self.loc_row)

        # 版型D独有：署名/地点位置自由微调
        self.corner_shift_row = QWidget()
        cshift = QVBoxLayout(self.corner_shift_row)
        cshift.setContentsMargins(0, 0, 0, 0)
        cshift.setSpacing(6)
        cshift.addWidget(QLabel("位置微调（版型D独有）"))

        hx_row = QHBoxLayout()
        hx_row.addWidget(self._field_label("水平"))
        self.corner_shift_x_slider = QSlider(Qt.Horizontal)
        self.corner_shift_x_slider.setRange(-150, 150)
        self.corner_shift_x_slider.setValue(0)
        hx_row.addWidget(self.corner_shift_x_slider, 1)
        self.corner_shift_x_label = QLabel("0")
        self.corner_shift_x_label.setMinimumWidth(32)
        hx_row.addWidget(self.corner_shift_x_label)
        cshift.addLayout(hx_row)

        vy_row = QHBoxLayout()
        vy_row.addWidget(self._field_label("垂直"))
        self.corner_shift_y_slider = QSlider(Qt.Horizontal)
        self.corner_shift_y_slider.setRange(-150, 150)
        self.corner_shift_y_slider.setValue(0)
        vy_row.addWidget(self.corner_shift_y_slider, 1)
        self.corner_shift_y_label = QLabel("0")
        self.corner_shift_y_label.setMinimumWidth(32)
        vy_row.addWidget(self.corner_shift_y_label)
        cshift.addLayout(vy_row)
        sec_template.addWidget(self.corner_shift_row)

        # ③ 导出设置
        sec_export = self._add_section("导出设置")
        sec_export.addWidget(self._field_label("导出格式"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["原格式", "JPG", "PNG"])
        self.format_combo.setCurrentText("原格式")
        sec_export.addWidget(self.format_combo)

        quality_row = QHBoxLayout()
        quality_row.addWidget(self._field_label("质量"))
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(92)
        quality_row.addWidget(self.quality_slider, 1)
        self.quality_label = QLabel("92")
        self.quality_label.setMinimumWidth(28)
        quality_row.addWidget(self.quality_label)
        sec_export.addLayout(quality_row)

        self.keep_exif_check = QCheckBox("保留 EXIF (GPS 等元数据)")
        self.keep_exif_check.setChecked(True)
        sec_export.addWidget(self.keep_exif_check)

        preset_row = QHBoxLayout()
        self.save_preset_btn = QPushButton("存预设")
        self.load_preset_btn = QPushButton("读预设")
        preset_row.addWidget(self.save_preset_btn)
        preset_row.addWidget(self.load_preset_btn)
        sec_export.addLayout(preset_row)

        # 底部状态（放在分组区之外，始终可见）
        self.status = QLabel("未加载图片")
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        # 一键恢复默认参数按钮
        self.reset_btn = QPushButton("恢复默认参数")
        self.reset_btn.setObjectName("resetBtn")
        self.reset_btn.setToolTip("把所有参数恢复为默认值")
        lay.addWidget(self.reset_btn)

        # 底部留一点弹性，把分组顶到顶部
        lay.addStretch(1)

        # 把 panel 放进滚动区，超高时可滚动
        scroll = QScrollArea()
        scroll.setObjectName("sidePanel")
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumWidth(280)
        # 始终显示滚动条，避免鼠标扫过时滚动条闪显/闪退导致内容宽度抖动
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        return scroll

    def _add_section(self, title: str):
        """创建一个可折叠 section：标题按钮 + 内容容器。

        返回内容区的布局，供后续 addWidget/addLayout 填充。
        标题按钮点击时切换内容区显示/隐藏。
        """
        content = QWidget()
        content.setObjectName("sectionContent")
        v = QVBoxLayout(content)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(8)

        header = QPushButton(title)
        header.setObjectName("sectionHeader")
        header.setCheckable(True)
        header.setChecked(True)
        header.setCursor(Qt.PointingHandCursor)

        self._sections_layout.addWidget(header)
        self._sections_layout.addWidget(content)

        def _toggle(checked):
            content.setVisible(checked)

        header.toggled.connect(_toggle)

        # 保存 header 引用，供「聚焦某 section」使用
        if not hasattr(self, "_section_headers"):
            self._section_headers = {}
        self._section_headers[title] = (header, content)

        return v

    def _focus_section(self, title: str):
        """展开指定 section，收起其他 section（点击模版卡片时聚焦对应编辑区）。

        「导出设置」始终展开（通用功能，不随聚焦收起）。
        """
        for name, (header, content) in getattr(self, "_section_headers", {}).items():
            if name == "导出设置":
                continue  # 导出设置始终展开
            checked = (name == title)
            header.setChecked(checked)
            content.setVisible(checked)

    def _field_label(self, text: str) -> QLabel:
        """参数字段标签：统一字号/颜色（由 QSS 控制，此处仅复用对象名）。"""
        lb = QLabel(text)
        lb.setObjectName("fieldLabel")
        return lb

    def _subsection_label(self, text: str) -> QLabel:
        """分组内的小节标题（比字段标签醒目，用于大分组内分区）。"""
        lb = QLabel(text)
        lb.setObjectName("subsectionLabel")
        return lb

    def _build_position_grid(self) -> QWidget:
        """3x3 九宫格位置选择器（可视化，替代下拉框）。"""
        container = QWidget()
        grid = QVBoxLayout(container)
        grid.setSpacing(2)
        self.position_btns: dict[str, QPushButton] = {}
        self._pos_group = QButtonGroup(self)
        self._pos_group.setExclusive(True)

        # POSITIONS 顺序正好是逐行 3 个
        for row in range(3):
            h = QHBoxLayout()
            h.setSpacing(2)
            for col in range(3):
                name = POSITIONS[row * 3 + col]
                btn = QPushButton()
                btn.setCheckable(True)
                btn.setFixedSize(32, 26)
                btn.setToolTip(name)
                self.position_btns[name] = btn
                self._pos_group.addButton(btn)
                h.addWidget(btn)
                if name == "右下":
                    btn.setChecked(True)
            h.addStretch()
            grid.addLayout(h)
        return container

    def _sync_color_btn(self):
        """让取色按钮背景色显示当前文字颜色。"""
        r, g, b = self._text_color
        self.color_btn.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); "
            f"border: 1px solid #888; border-radius: 4px;"
        )
        self.color_hex_label.setText(f"#{r:02X}{g:02X}{b:02X}")

    def _current_position(self) -> str:
        """从九宫格按钮组取当前选中位置。"""
        btn = self._pos_group.checkedButton()
        for name, b in self.position_btns.items():
            if b is btn:
                return name
        return "右下"

    def _build_export_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self.theme_btn = QPushButton("浅色")
        self.theme_btn.setObjectName("themeBtn")
        self.theme_btn.setToolTip("切换深色/浅色主题")
        self.theme_btn.setIcon(_icon("moon"))
        self.info_btn = QPushButton("")
        self.info_btn.setObjectName("infoBtn")
        self.info_btn.setToolTip("关于 / 开源字体授权")
        self.info_btn.setIcon(_icon("info"))
        self.output_btn = QPushButton("输出目录…")
        self.output_btn.setIcon(_icon("export_dir"))
        self.output_label = QLabel("未设置")
        self.output_label.setMinimumWidth(160)
        self.output_label.setText(self._output_dir or "未设置")
        self.output_label.setToolTip(self._output_dir)
        self.export_btn = QPushButton("导出")
        self.export_btn.setObjectName("exportBtn")  # 让 QSS 能高亮它
        self.export_btn.setIcon(_icon("export", color="#FFFFFF"))
        self.export_btn.setEnabled(False)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setIcon(_icon("cancel"))
        self.cancel_btn.setEnabled(False)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(False)

        bar.addWidget(self.theme_btn)
        bar.addWidget(self.info_btn)
        bar.addWidget(self.output_btn)
        bar.addWidget(self.output_label)
        bar.addStretch()
        bar.addWidget(self.progress, 1)
        bar.addWidget(self.cancel_btn)
        bar.addWidget(self.export_btn)
        return bar

    # ---------- 信号连接 ----------
    def _connect(self):
        self.open_btn.clicked.connect(self._choose_images)
        self.add_btn.clicked.connect(self._choose_images)
        self.folder_btn.clicked.connect(self._choose_folder)
        self.clear_btn.clicked.connect(self._clear_images)
        self.remove_btn.clicked.connect(self._remove_selected)
        self.up_btn.clicked.connect(self._move_selected_up)
        self.down_btn.clicked.connect(self._move_selected_down)
        self.file_list.currentItemChanged.connect(self._on_select_file)

        # 参数变化 → 刷新预览
        self.text_enabled.toggled.connect(self._refresh_preview)
        self.text_edit.textChanged.connect(self._refresh_preview)
        self.font_combo.currentIndexChanged.connect(self._refresh_preview)
        self.size_slider.valueChanged.connect(self._refresh_preview)
        self.opacity_slider.valueChanged.connect(self._refresh_preview)
        self._pos_group.buttonClicked.connect(lambda _: self._refresh_preview())
        self.color_btn.clicked.connect(self._choose_color)
        self.stroke_check.toggled.connect(self._refresh_preview)
        self.stroke_spin.valueChanged.connect(self._refresh_preview)
        self.rotation_slider.valueChanged.connect(self._on_rotation_changed)
        self.margin_slider.valueChanged.connect(self._on_margin_changed)
        self.image_enabled.toggled.connect(self._on_image_toggle)
        self.logo_btn.clicked.connect(self._choose_logo)
        self.tiled_enabled.toggled.connect(self._refresh_preview)
        self.tiled_spacing_slider.valueChanged.connect(self._refresh_preview)
        self.crop_combo.currentIndexChanged.connect(self._refresh_preview)
        self.brand_combo.currentIndexChanged.connect(self._refresh_preview)
        self.scheme_combo.currentIndexChanged.connect(self._refresh_preview)
        self.info_sig_edit.textChanged.connect(self._refresh_preview)
        self.info_loc_edit.textChanged.connect(self._refresh_preview)
        self.corner_shift_x_slider.valueChanged.connect(self._on_corner_shift_changed)
        self.corner_shift_y_slider.valueChanged.connect(self._on_corner_shift_changed)
        self.format_combo.currentIndexChanged.connect(self._refresh_preview)
        self.quality_slider.valueChanged.connect(self._on_quality_changed)
        self.keep_exif_check.toggled.connect(lambda _: self._mark_current_edited())  # 无需刷新预览，仅标记编辑

        # 预览缩放
        self.zoom_in_btn.clicked.connect(lambda: self._zoom(1.2))
        self.zoom_out_btn.clicked.connect(lambda: self._zoom(1 / 1.2))
        self.zoom_fit_btn.clicked.connect(self._zoom_fit)

        # 预设
        self.save_preset_btn.clicked.connect(self._save_preset)
        self.load_preset_btn.clicked.connect(self._load_preset)
        self.reset_btn.clicked.connect(self._reset_defaults)

        # 导出
        self.output_btn.clicked.connect(self._choose_output_dir)
        self.export_btn.clicked.connect(self._start_export)
        self.cancel_btn.clicked.connect(self._cancel_export)

        # 主题切换
        self.theme_btn.clicked.connect(self._toggle_theme)
        # 关于 / 字体授权
        self.info_btn.clicked.connect(self._show_settings)
        # 编辑面板关闭按钮
        self.editor_close_btn.clicked.connect(self._hide_editor)

    # ---------- 拖拽导入 ----------
    def _add_files(self, paths: list[str]):
        """把一批路径加入文件列表（去重）。

        路径既可以是图片文件，也可以是文件夹（自动展开为文件夹内所有图片）。
        """
        expanded: list[str] = []
        for p in paths:
            path = Path(p)
            if path.is_dir():
                # 文件夹：展开为里面所有受支持的图片
                expanded.extend(str(f) for f in list_images(path))
            else:
                expanded.append(p)

        added = False
        for p in expanded:
            if p in self._files:
                continue
            if Path(p).suffix.lower() not in IMAGE_EXTS:
                continue
            self._files.append(p)
            item = QListWidgetItem(Path(p).name, self.file_list)
            # 完整路径存到 UserRole 数据（toolTip 留给徽标说明用，二者解耦）
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            added = True
        if added and self.file_list.currentRow() < 0:
            self.file_list.setCurrentRow(0)
        # 有文件且输出目录已就绪时，启用导出按钮
        if self._files and self._output_dir:
            self.export_btn.setEnabled(True)
        self._sync_file_list_empty()

    def _sync_file_list_empty(self):
        """根据列表是否有文件，切换空状态提示的显示。"""
        if not hasattr(self, "file_list_empty"):
            return
        has_items = self.file_list.count() > 0
        self.file_list_empty.setVisible(not has_items)
        if not has_items:
            self.file_list_empty.setGeometry(self.file_list.rect())

    def dragEnterEvent(self, event):
        # 只接受拖入文件/链接
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        paths = []
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p:
                paths.append(p)
        if paths:
            self._add_files(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    # ---------- 槽：文件选择 ----------
    def _choose_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "",
            "图片 (*.jpg *.jpeg *.png *.webp *.bmp *.tiff *.tif)"
        )
        if not paths:
            return
        self._add_files(paths)

    def _choose_folder(self):
        """选择一个文件夹，导入其中所有受支持的图片。"""
        d = QFileDialog.getExistingDirectory(self, "选择图片文件夹", self._output_dir or "")
        if not d:
            return
        images = list_images(d)
        if not images:
            QMessageBox.information(self, "文件夹", f"该文件夹内没有受支持的图片：\n{d}")
            return
        self._add_files([str(p) for p in images])

    def _clear_images(self):
        self._files.clear()
        self.file_list.clear()
        self._img = None
        self._img_path = ""
        self._preview_seq += 1  # 使后台进行中的旧预览任务失效
        # 清空每图独立参数快照
        self._per_image_params.clear()
        self._last_img_path = ""
        self.preview.setText(self._empty_preview_html())
        self._set_status("未加载图片", "neutral")
        self._sync_file_list_empty()

    def _remove_selected(self):
        row = self.file_list.currentRow()
        if row < 0:
            return
        # 移除该图对应的独立参数快照
        removed_path = self._files[row] if row < len(self._files) else ""
        if removed_path:
            self._per_image_params.pop(removed_path, None)
            if self._last_img_path == removed_path:
                self._last_img_path = ""
        self.file_list.takeItem(row)
        self._files.pop(row)
        # 选中下一个（或上一个），刷新预览
        if self.file_list.count() > 0:
            new_row = min(row, self.file_list.count() - 1)
            self.file_list.setCurrentRow(new_row)
        else:
            self._img = None
            self._img_path = ""
            self._preview_seq += 1  # 使后台进行中的旧预览任务失效
            self.preview.setText(self._empty_preview_html())
            self._set_status("未加载图片", "neutral")
        self._sync_file_list_empty()
        # 移除后第一张图可能变化 → 重算所有徽标
        self._update_all_badges()

    def _move_selected_up(self):
        self._move_selected(-1)

    def _move_selected_down(self):
        self._move_selected(1)

    def _move_selected(self, delta: int):
        row = self.file_list.currentRow()
        new_row = row + delta
        if row < 0 or not (0 <= new_row < self.file_list.count()):
            return
        # 交换 _files 里的顺序
        self._files[row], self._files[new_row] = self._files[new_row], self._files[row]
        # 交换列表项
        item = self.file_list.takeItem(row)
        self.file_list.insertItem(new_row, item)
        self.file_list.setCurrentRow(new_row)
        # 顺序变化可能改变「第一张图」基准 → 重算所有徽标
        self._update_all_badges()

    def _on_select_file(self, current, _prev):
        if current is None:
            return
        new_path = current.data(Qt.UserRole) or ""
        if not new_path:
            return
        # 切换文件前：把当前图的参数存回它的独立快照（实现「每图独立模版」）
        self._save_current_image_params()
        # 切换到新图
        self._img_path = new_path
        self._img = open_image(self._img_path)
        # 恢复新图的独立参数快照（若有），否则继承当前全局参数
        self._load_image_params(new_path)
        self._do_refresh_preview()
        # 刷新画廊缩略图（用当前选中的图）
        self._refresh_gallery_thumbs()

    def _update_file_badge(self, path: str):
        """刷新文件列表某项的「已单独设置模版」徽标。

        徽标显示条件：该图有独立参数快照，且其参数与「基准模版」不同。
        基准模版 = 本组第一张图（若已编辑/有快照）的参数，否则为默认模版。
        这样第一张图是锚点，后续图只有偏离它（或偏离默认）才标出，避免铺满。
        """
        row = self._files.index(path) if path in self._files else -1
        if row < 0:
            return
        item = self.file_list.item(row)
        if item is None:
            return
        marked = self._image_has_custom_template(path)
        if marked:
            item.setIcon(self._badge_pixmap)
            item.setToolTip(f"{path}\n（已单独设置模版，导出时使用本图自己的参数）")
        else:
            item.setIcon(QPixmap())
            item.setToolTip(path)

    def _image_has_custom_template(self, path: str) -> bool:
        """判断某张图是否「单独设置了与基准不同的模版」（用于徽标）。

        规则：
        - 无独立快照 → False（继承基准，未单独设置）
        - 有快照 → 与基准模版比较，不同则 True
        """
        snap = self._per_image_params.get(path)
        if snap is None:
            return False
        return self._params_differ(snap, self._get_base_params())

    def _get_base_params(self) -> dict:
        """本组「基准模版」参数。

        第一张图（列表第 0 项）若已被编辑（有独立快照），以它为准；
        否则用默认模版 DEFAULT_PARAMS。第一张图是整组的锚点。
        """
        first = self._files[0] if self._files else ""
        if first and first in self._per_image_params:
            return self._per_image_params[first]
        return DEFAULT_PARAMS

    @staticmethod
    def _params_differ(a: dict, b: dict) -> bool:
        """判断两个参数字典在「模版选择」上是否实质不同。

        只比较与模版语义相关的字段（字体名/路径等次要字段不参与，
        避免仅字体不同就被误判为「换了模版」）。颜色 list/tuple 等价。
        """
        keys = (
            "text_enabled", "text", "size_permille", "opacity", "position",
            "color", "stroke", "stroke_width", "rotation", "margin",
            "image_enabled", "logo_path", "tiled_enabled", "tiled_spacing",
            "crop", "info_layout", "info_brand", "info_scheme",
            "info_signature", "info_location",
            "corner_shift_x", "corner_shift_y",
            "format", "quality", "keep_exif",
        )
        for k in keys:
            va, vb = a.get(k), b.get(k)
            if isinstance(va, list):
                va = tuple(va)
            if isinstance(vb, list):
                vb = tuple(vb)
            if va != vb:
                return True
        return False

    def _update_all_badges(self):
        """重算并刷新文件列表所有项的徽标（基准变化后调用）。"""
        for path in self._files:
            self._update_file_badge(path)

    def _save_current_image_params(self):
        """把当前 UI 参数保存为「上次选中图」的独立快照。

        只有真实编辑过参数（UI 状态与默认/继承状态不同）才写快照，
        但为简单可靠起见，这里始终记录一次完整快照；导出时会优先取快照。
        """
        if not self._last_img_path:
            return
        self._per_image_params[self._last_img_path] = self._collect_params_dict()
        # 快照/基准可能变化（如第一张图被编辑后基准切换）→ 重算所有徽标
        self._update_all_badges()

    def _load_image_params(self, path: str):
        """恢复某张图的独立参数快照；无快照则保留当前全局参数不变。"""
        self._last_img_path = path
        snap = self._per_image_params.get(path)
        if snap is not None:
            self._apply_params_dict(snap)
        # 无快照：UI 保持现状（即继承全局默认），无需处理
        # 同步徽标（基准可能随第一张图状态变化，重算全部）
        self._update_all_badges()

    def _choose_logo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 Logo", "", "图片 (*.png *.jpg *.jpeg *.webp)"
        )
        if path:
            self._logo_path = path
            self.logo_label.setText(Path(path).name)
            self._mark_current_edited()
            self._do_refresh_preview()

    def _on_image_toggle(self, checked):
        self.logo_btn.setEnabled(checked)
        if checked and not self._logo_path:
            self._choose_logo()
        self._mark_current_edited()
        self._do_refresh_preview()

    def _default_output_dir(self) -> str:
        """默认输出目录：访达「图片」(~/Pictures) 下的「watermark products」文件夹。

        不存在时自动创建；创建失败则回退到「图片」目录本身。
        """
        pictures = Path.home() / "Pictures"
        target = pictures / "watermark products"
        try:
            target.mkdir(parents=True, exist_ok=True)
            return str(target)
        except OSError:
            # 无法在图片下建文件夹时，回退到图片目录（尽量保证有可写目录）
            try:
                pictures.mkdir(parents=True, exist_ok=True)
                return str(pictures)
            except OSError:
                return ""

    def _choose_output_dir(self):
        start = self._output_dir or self._default_output_dir()
        d = QFileDialog.getExistingDirectory(self, "选择输出目录", start)
        if d:
            self._output_dir = d
            self.output_label.setText(d)
            self.output_label.setToolTip(d)
            self.export_btn.setEnabled(bool(self._files))

    # ---------- 槽：预览 ----------
    def _current_text_wm(self) -> TextWatermark:
        color = self._text_color
        return TextWatermark(
            text=self.text_edit.text() or " ",
            font_path=FONT_MAP[self.font_combo.currentText()],
            size_permille=self.size_slider.value(),
            opacity=self.opacity_slider.value() / 100,
            color=color,
            stroke_width=self.stroke_spin.value() if self.stroke_check.isChecked() else 0,
            stroke_color=(0, 0, 0) if sum(color) > 384 else (255, 255, 255),
            position=self._current_position(),
            margin_permille=self.margin_slider.value(),
            rotation=float(self.rotation_slider.value()),
        )

    def _choose_color(self):
        c = QColorDialog.getColor(QColor(*self._text_color), self, "选择文字颜色")
        if c.isValid():
            self._text_color = (c.red(), c.green(), c.blue())
            self._sync_color_btn()
            self._mark_current_edited()
            self._do_refresh_preview()

    def _on_rotation_changed(self, v):
        self.rotation_label.setText(f"{v}°")
        self._refresh_preview()

    def _on_margin_changed(self, v):
        self.margin_label.setText(str(v))
        self._refresh_preview()

    def _on_quality_changed(self, v):
        self.quality_label.setText(str(v))
        # 质量只影响导出，不影响预览（预览是 PNG 无损显示），无需刷新预览
        # 但质量属于模版参数的一部分，改动要标记当前图为已编辑
        self._mark_current_edited()

    # ---------- 预览缩放 ----------
    def _zoom(self, factor: float):
        """放大/缩小：调整相对「适应窗口」的缩放因子（>1 放大看细节）。"""
        self._preview_zoom = max(0.25, min(8.0, self._preview_zoom * factor))
        self._refresh_preview_display()

    def _zoom_fit(self):
        """适应窗口：缩放因子重置为 1.0，预览图完整放进预览框。"""
        self._preview_zoom = 1.0
        self._refresh_preview_display()

    def _refresh_preview_display(self):
        """根据当前缩放因子，把已缓存的预览图重新缩放显示（无需重渲染）。"""
        self.zoom_label.setText(f"{int(self._preview_zoom * 100)}%")
        if getattr(self, "_preview_full_img", None):
            self._fit_preview_to_window()

    def _current_image_wm(self) -> ImageWatermark | None:
        if not self.image_enabled.isChecked() or not self._logo_path:
            return None
        return ImageWatermark(
            watermark_path=self._logo_path,
            scale=0.15,
            opacity=0.85,
            position="左下",
            margin_permille=24,
        )

    def _current_image_wm_preview(self) -> ImageWatermark | None:
        """预览专用的图片水印：未选 logo 时用预制 α 示例图，让用户理解功能。

        与 _current_image_wm 的区别：后者无 logo 返回 None（导出时不会误加水印），
        这里无 logo 时回退到预制图，仅用于实时预览演示。
        """
        if not self.image_enabled.isChecked():
            return None
        logo = self._logo_path or str(resource_path("assets", "icons", "alpha-orange.png"))
        return ImageWatermark(
            watermark_path=logo,
            scale=0.15,
            opacity=0.85,
            position="左下",
            margin_permille=24,
        )

    def _current_crop_ratio(self):
        return RATIOS[self.crop_combo.currentText()]

    def _current_tiled(self) -> dict | None:
        """平铺水印参数，未启用时返回 None。"""
        if not self.tiled_enabled.isChecked():
            return None
        if not self.text_edit.text().strip():
            return None
        return {
            "text": self.text_edit.text(),
            "font_path": FONT_MAP[self.font_combo.currentText()],
            "size_permille": self.size_slider.value(),
            "opacity": 0.15,
            "rotation": -30.0,
            "spacing_permille": self.tiled_spacing_slider.value(),
            "color": self._text_color,
        }

    def _current_output_format(self) -> str | None:
        """导出格式：'原格式' -> None，其余 -> 'jpg'/'png'。"""
        name = self.format_combo.currentText()
        return None if name == "原格式" else name.lower()

    def _current_info_bar_style(self) -> InfoBarStyle | None:
        """根据布局骨架 + 品牌 logo + 配色方案，组合出统一模版参数。

        '不启用' 返回 None；否则返回组合出的 InfoBarStyle（含署名/地点回填）。
        """
        layout_name = self._layout_name
        layout = LAYOUT_CHOICES.get(layout_name)
        if layout is None:
            return None

        # 组装统一模版
        style = InfoBarStyle(layout=layout)

        # 套用配色方案
        scheme_name = self.scheme_combo.currentText()
        scheme = COLOR_SCHEMES.get(scheme_name, COLOR_SCHEMES["白底黑字"])
        style.apply_scheme(scheme)

        # 套用品牌 logo
        brand_name = self.brand_combo.currentText()
        logo_path = BRAND_LOGOS.get(brand_name, "")
        style.apply_logo(logo_path)

        # 各布局的 logo 尺寸微调（扁平字标需要更大的 brand_scale）
        if layout in ("center", "month_title", "left_panel"):
            style.brand_scale = 90
        if layout == "left_logo":
            style.logo_scale = 80

        # 回填署名/地点
        style.signature = self.info_sig_edit.text().strip()
        style.location = self.info_loc_edit.text().strip()

        # corner_sign 独有：位置微调偏移
        style.corner_shift_x = self.corner_shift_x_slider.value()
        style.corner_shift_y = self.corner_shift_y_slider.value()
        return style

    def _on_corner_shift_changed(self, _v):
        """corner_sign 位置微调滑块：更新数值标签并刷新预览。"""
        self.corner_shift_x_label.setText(str(self.corner_shift_x_slider.value()))
        self.corner_shift_y_label.setText(str(self.corner_shift_y_slider.value()))
        self._refresh_preview()

    def _update_info_bar_fields(self):
        """根据当前布局骨架显示/隐藏署名、地点输入框。"""
        layout_name = self._layout_name
        layout = LAYOUT_CHOICES.get(layout_name)
        support = LAYOUT_FIELD_SUPPORT.get(layout, {"signature": False, "location": False})
        self.sig_row.setVisible(support["signature"])
        self.loc_row.setVisible(support["location"])
        # 位置微调滑块仅 corner_sign 布局显示
        self.corner_shift_row.setVisible(layout == "corner_sign")
        # 布局未启用时，隐藏 logo/配色下拉（它们只在启用模版时才有意义）
        enabled = layout is not None
        self.brand_combo.setEnabled(enabled)
        self.scheme_combo.setEnabled(enabled)

    def _refresh_preview(self):
        """参数变化入口：启动防抖定时器，停止操作后统一刷新一次。

        文字输入、滑块拖动等高频信号都走这里，通过单次定时器合并，
        避免每敲一个字/每动一格就重算整张预览图。
        """
        if self._img is None:
            return
        self._preview_timer.start()

    def _on_preview_edit(self):
        """防抖到期：用户编辑参数后，标记当前图为「已编辑」并刷新预览。

        与切换文件（_on_select_file 直接调 _do_refresh_preview，不走定时器）区分开，
        保证只有真正的参数编辑动作才触发「当前图写入快照 + 重算徽标」。
        """
        self._mark_current_edited()
        self._do_refresh_preview()

    def _mark_current_edited(self):
        """把当前选中图写入独立快照，并重算所有徽标。

        用户编辑参数时实时生效（无需等切换文件），让「第一张图作基准」的
        判定立即可见：一旦第一张图被编辑，后续图即以其为基准比较。
        """
        if not self._last_img_path:
            return
        self._per_image_params[self._last_img_path] = self._collect_params_dict()
        self._update_all_badges()

    def _do_refresh_preview(self):
        """真正执行预览渲染：收集参数快照，交给后台线程。"""
        if self._img is None:
            return
        # 取消上一个还在跑的渲染任务（若有），避免旧结果覆盖新结果
        if self._preview_worker is not None:
            self._preview_worker.cancel()

        params = self._collect_preview_params()
        self._preview_seq += 1
        seq = self._preview_seq

        worker = PreviewWorker(
            seq=seq,
            img=self._img,
            img_path=self._img_path,
            preview_scale=1.0,  # 已弃用：缩放改在显示端按预览框 fit 计算
            params=params,
        )
        worker.result_ready.connect(self._on_preview_ready)
        # 线程结束（含取消/异常）后自动清理引用，避免旧 worker 运行中被 GC 回收导致崩溃
        worker.finished.connect(lambda w=worker: self._release_preview_worker(w))
        self._preview_worker = worker
        self._preview_workers.append(worker)
        worker.start()

    def _release_preview_worker(self, worker: PreviewWorker):
        """预览线程结束（含取消）后，从持有列表移除其引用。"""
        if worker in self._preview_workers:
            self._preview_workers.remove(worker)
        if self._preview_worker is worker:
            self._preview_worker = None

    def _collect_preview_params(self) -> dict:
        """收集当前所有影响预览的参数，打包成不可变快照传给后台线程。"""
        return {
            "crop_ratio": self._current_crop_ratio(),
            "text_enabled": self.text_enabled.isChecked(),
            "text_wm": self._current_text_wm() if self.text_enabled.isChecked() else None,
            "tiled": self._current_tiled(),
            "image_wm": self._current_image_wm_preview(),
            "info_bar_style": self._current_info_bar_style(),
        }

    def _on_preview_ready(self, seq: int, result_img: Image.Image):
        """后台渲染完成回调：只接受最新序号的结果，丢弃过时帧。"""
        if seq != self._preview_seq:
            return  # 已被更新的任务取代，丢弃
        self._preview_full_img = result_img  # 缓存完整渲染图（缩放/重绘用）
        self._fit_preview_to_window()
        crop_name = self.crop_combo.currentText()
        ratio = self._current_crop_ratio()
        self._set_status(
            f"{Path(self._img_path).name} · 透明度{self.opacity_slider.value()}%"
            f" · 字号{self.size_slider.value()}"
            + (f" · 裁剪{crop_name}" if ratio else ""),
            "neutral",
        )

    def _fit_preview_to_window(self):
        """把缓存的完整预览图按预览框尺寸等比缩放显示（fit-in-box）。

        缩放比例 = 预览框尺寸与图片尺寸的较小比值，再乘缩放因子 _preview_zoom。
        这样「适应窗口」保证完整显示；放大/缩小则在此基础上缩放（放大看细节）。
        """
        if not getattr(self, "_preview_full_img", None):
            return
        pw = self.preview.width()
        ph = self.preview.height()
        if pw <= 0 or ph <= 0:
            return
        pm = pil_to_qpixmap(self._preview_full_img)
        iw, ih = pm.width(), pm.height()
        fit = min(pw / iw, ph / ih) * self._preview_zoom
        target_w = max(1, round(iw * fit))
        target_h = max(1, round(ih * fit))
        self.preview.setPixmap(pm.scaled(
            target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation,
        ))

    # ---------- 状态反馈（语义色） ----------
    def _empty_preview_html(self) -> str:
        """预览区空状态：图标 + 引导语，替代干巴巴的灰字。

        文字颜色随主题适配（深色用浅灰、浅色用深灰），保证对比度。
        """
        if self._light_theme:
            icon_c = "#B0B4BC"
            title_c = "#6A6A72"
            sub_c = "#9AA0A8"
        else:
            icon_c = "#4A4A4A"
            title_c = "#888"
            sub_c = "#5A5A5A"
        return (
            '<div style="color:#5A5A5A; font-size:14px;">'
            f'<div style="font-size:40px; margin-bottom:12px; color:{icon_c};">'
            '\u25A3</div>'  # 空相框符号
            f'<div style="font-size:15px; color:{title_c};">拖入图片开始添加水印</div>'
            f'<div style="font-size:12px; margin-top:6px; color:{sub_c};">'
            '支持 JPG / PNG / TIFF / WebP / BMP</div>'
            '</div>'
        )

    def _set_status(self, text: str, kind: str = "neutral"):
        """设置状态栏文字并套用语义色。

        kind 取值：neutral（默认灰）/ info（蓝）/ success（绿）/
        warning（橙）/ danger（红）。通过动态属性匹配 QSS 规则。
        """
        self.status.setText(text)
        self.status.setProperty("statusKind", kind)
        # 触发样式重算
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    # ---------- 参数快照（每图独立模版 + 预设保存/加载复用） ----------
    def _collect_params_dict(self) -> dict:
        """把当前 UI 所有参数收集成不可变字典快照。

        供三处复用：预设保存、每图独立参数快照、导出时的全局默认参数。
        """
        return {
            "text_enabled": self.text_enabled.isChecked(),
            "text": self.text_edit.text(),
            "font": self.font_combo.currentText(),
            "font_path": FONT_MAP[self.font_combo.currentText()],
            "size_permille": self.size_slider.value(),
            "opacity": self.opacity_slider.value() / 100,
            "position": self._current_position(),
            "color": list(self._text_color),
            "stroke": self.stroke_check.isChecked(),
            "stroke_width": self.stroke_spin.value(),
            "rotation": self.rotation_slider.value(),
            "margin": self.margin_slider.value(),
            "image_enabled": self.image_enabled.isChecked(),
            "logo_path": self._logo_path,
            "tiled_enabled": self.tiled_enabled.isChecked(),
            "tiled_spacing": self.tiled_spacing_slider.value(),
            "crop": self.crop_combo.currentText(),
            "info_layout": self._layout_name,
            "info_brand": self.brand_combo.currentText(),
            "info_scheme": self.scheme_combo.currentText(),
            "info_signature": self.info_sig_edit.text(),
            "info_location": self.info_loc_edit.text(),
            "corner_shift_x": self.corner_shift_x_slider.value(),
            "corner_shift_y": self.corner_shift_y_slider.value(),
            "format": self.format_combo.currentText(),
            "quality": self.quality_slider.value(),
            "keep_exif": self.keep_exif_check.isChecked(),
        }

    def _apply_params_dict(self, data: dict):
        """把参数字典回填到 UI 控件（并触发预览刷新）。

        供三处复用：预设加载、每图独立参数恢复、恢复默认。
        data 中缺失的键保留当前值（用 get 兜底）。
        """
        self.text_enabled.setChecked(data.get("text_enabled", True))
        self.text_edit.setText(data.get("text", ""))
        self.font_combo.setCurrentText(data.get("font", self.font_combo.itemText(0)))
        self.size_slider.setValue(int(data.get("size_permille", 36)))
        self.opacity_slider.setValue(int(data.get("opacity", 0.7) * 100))

        pos = data.get("position", "右下")
        if pos in self.position_btns:
            self.position_btns[pos].setChecked(True)

        c = data.get("color", [255, 255, 255])
        if isinstance(c, (list, tuple)) and len(c) == 3:
            self._text_color = tuple(int(x) for x in c)
            self._sync_color_btn()

        self.stroke_check.setChecked(data.get("stroke", True))
        self.stroke_spin.setValue(int(data.get("stroke_width", 1)))
        self.rotation_slider.setValue(int(data.get("rotation", 0)))
        self.rotation_label.setText(f"{self.rotation_slider.value()}°")
        self.margin_slider.setValue(int(data.get("margin", 24)))
        self.margin_label.setText(str(self.margin_slider.value()))
        # 先设 logo_path，再 setChecked(image_enabled)，避免 toggled 触发 _on_image_toggle
        # 时 _logo_path 还是旧的空值导致误弹「选择 logo」对话框
        self._logo_path = data.get("logo_path", "")
        if self._logo_path:
            self.logo_label.setText(Path(self._logo_path).name)
        else:
            self.logo_label.setText("未选择")
        self.image_enabled.setChecked(data.get("image_enabled", False))
        self.tiled_enabled.setChecked(data.get("tiled_enabled", False))
        self.tiled_spacing_slider.setValue(int(data.get("tiled_spacing", 300)))
        self.crop_combo.setCurrentText(data.get("crop", "不裁剪"))

        # 统一模版：布局 + logo + 配色（向后兼容旧的 info_bar 字段）
        layout = data.get("info_layout", "")
        if layout in LAYOUT_CHOICES:
            self._layout_name = layout
        else:
            old_ib = data.get("info_bar", "")
            self._layout_name = _map_old_layout(old_ib)
        brand = data.get("info_brand", "")
        if brand in BRAND_LOGOS:
            self.brand_combo.setCurrentText(brand)
        scheme = data.get("info_scheme", "")
        if scheme in COLOR_SCHEMES:
            self.scheme_combo.setCurrentText(scheme)
        self._update_info_bar_fields()
        self.info_sig_edit.setText(data.get("info_signature", ""))
        self.info_loc_edit.setText(data.get("info_location", ""))
        self.corner_shift_x_slider.setValue(int(data.get("corner_shift_x", 0)))
        self.corner_shift_y_slider.setValue(int(data.get("corner_shift_y", 0)))
        self.corner_shift_x_label.setText(str(self.corner_shift_x_slider.value()))
        self.corner_shift_y_label.setText(str(self.corner_shift_y_slider.value()))
        self.format_combo.setCurrentText(data.get("format", "原格式"))
        self.quality_slider.setValue(int(data.get("quality", 92)))
        self.quality_label.setText(str(self.quality_slider.value()))
        self.keep_exif_check.setChecked(data.get("keep_exif", False))

    # ---------- 槽：预设 ----------
    def _reset_defaults(self):
        """一键恢复所有参数到默认值。"""
        self._apply_params_dict(DEFAULT_PARAMS)
        self._do_refresh_preview()
        self._set_status("已恢复默认参数", "info")

    def _save_preset(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "保存预设", str(Path.home() / "水印预设.json"),
            "预设 (*.json)"
        )
        if not path:
            return
        data = self._collect_params_dict()
        cfg.save_json(data, Path(path))
        QMessageBox.information(self, "预设", f"预设已保存到：\n{path}")

    def _load_preset(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "加载预设", "", "预设 (*.json)"
        )
        if not path:
            return
        try:
            data = cfg.load_json(Path(path))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "预设", f"读取失败：{e}")
            return
        # 回填到界面（触发预览刷新）
        self._apply_params_dict(data)
        self._do_refresh_preview()
        QMessageBox.information(self, "预设", f"预设已加载：\n{Path(path).name}")

    # ---------- 槽：导出 ----------
    def _start_export(self):
        if not self._files:
            return
        out_dir = getattr(self, "_output_dir", "")
        if not out_dir:
            self._choose_output_dir()
            out_dir = getattr(self, "_output_dir", "")
            if not out_dir:
                return

        # 导出前：把当前选中图的参数也存进它的独立快照，
        # 保证「当前正在编辑、尚未切换走」的这张图能带上最新参数。
        self._save_current_image_params()
        # 同时把当前参数作为「全局默认」：未被单独编辑过的图继承这套
        global_params = self._collect_params_dict()

        # 禁用界面，启动后台线程
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)

        self._worker = ExportWorker(
            files=self._files,
            output_dir=out_dir,
            text_wm=self._current_text_wm() if self.text_enabled.isChecked() else None,
            image_wm=self._current_image_wm(),
            crop_ratio=self._current_crop_ratio(),
            tiled=self._current_tiled(),
            quality=self.quality_slider.value(),
            output_format=self._current_output_format(),
            keep_exif=self.keep_exif_check.isChecked(),
            info_bar_style=self._current_info_bar_style(),
            per_image_params=self._per_image_params,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_finished)
        self._worker.start()

    def _cancel_export(self):
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, i, total, name):
        self.progress.setRange(0, total)
        self.progress.setValue(i)
        self._set_status(f"导出中 [{i}/{total}] {name}", "info")

    def _on_failed(self, name, err):
        # 累计失败，最终在 finished 里汇总弹窗
        pass

    def _on_finished(self, ok, fail, out_dir):
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress.setVisible(False)
        if fail > 0:
            self._set_status(f"完成：成功 {ok} 张，失败 {fail} 张", "warning")
        else:
            self._set_status(f"完成：成功 {ok} 张", "success")

        if fail > 0:
            QMessageBox.warning(
                self, "导出完成",
                f"成功 {ok} 张，失败 {fail} 张。\n\n"
                f"失败的图片已跳过（详见下方状态栏）。\n输出目录：{out_dir}"
            )
        else:
            QMessageBox.information(
                self, "导出完成",
                f"成功导出 {ok} 张图片到：\n{out_dir}"
            )
