"""内置功能图标（线性风格，单色，随主题色着色）。

所有图标用 SVG path 定义，渲染成 QIcon。风格统一为：
- 24x24 视口，1.5px 描边、圆角端
- 单色（currentColor），由调用方指定颜色
- 纯矢量，无外部依赖，离线可用

用法：
    from .icons import icon
    btn.setIcon(icon("folder", color="#E6E6E6"))
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 每个图标是一个 SVG 片段（path 使用 currentColor 描边）
_SVG_PATHS: dict[str, str] = {
    # 选择图片（图片 + 加号）
    "image": (
        '<rect x="3" y="3" width="18" height="18" rx="2" '
        'fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<circle cx="8.5" cy="8.5" r="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/>'
        '<path d="M21 15l-5-5L5 21" fill="none" stroke="currentColor" stroke-width="1.6" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
    ),
    # 追加（加号）
    "add": (
        '<path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round"/>'
    ),
    # 文件夹
    "folder": (
        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" '
        'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>'
    ),
    # 移除（垃圾桶）
    "trash": (
        '<path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12" '
        'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    # 上移（向上箭头）
    "up": (
        '<path d="M12 19V5M5 12l7-7 7 7" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    # 下移（向下箭头）
    "down": (
        '<path d="M12 5v14M5 12l7 7 7-7" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    # 清空（叉）
    "clear": (
        '<path d="M6 6l12 12M18 6L6 18" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round"/>'
    ),
    # 缩小
    "zoom_out": (
        '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M8 11h6M20 20l-4-4" fill="none" stroke="currentColor" '
        'stroke-width="1.6" stroke-linecap="round"/>'
    ),
    # 放大
    "zoom_in": (
        '<circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M11 8v6M8 11h6M20 20l-4-4" fill="none" stroke="currentColor" '
        'stroke-width="1.6" stroke-linecap="round"/>'
    ),
    # 适应窗口（四角缩放）
    "zoom_fit": (
        '<path d="M9 3H3v6M15 3h6v6M9 21H3v-6M15 21h6v-6" fill="none" '
        'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    # 输出目录（文件夹带导出箭头）
    "export_dir": (
        '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" '
        'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>'
        '<path d="M12 11v5M9.5 13.5L12 16l2.5-2.5" fill="none" stroke="currentColor" '
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    # 导出（上传/下载箭头）
    "export": (
        '<path d="M12 3v12M6 9l6 6 6-6M4 21h16" fill="none" stroke="currentColor" '
        'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>'
    ),
    # 取消（停止方块）
    "cancel": (
        '<rect x="6" y="6" width="12" height="12" rx="1.5" fill="none" '
        'stroke="currentColor" stroke-width="1.6"/>'
    ),
    # 主题切换（半月亮）
    "moon": (
        '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" '
        'fill="none" stroke="currentColor" stroke-width="1.6" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
    ),
    # 关于/信息（圆圈内 i）
    "info": (
        '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="1.6"/>'
        '<path d="M12 11v5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
        '<circle cx="12" cy="7.8" r="1.2" fill="currentColor"/>'
    ),
}


def _make_icon(svg_body: str, color: str, size: int = 20) -> QIcon:
    """把 SVG path 片段 + 颜色渲染成 QIcon。"""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'width="{size}" height="{size}">'
        f'<g color="{color}">{svg_body}</g>'
        f'</svg>'
    )
    data = QByteArray(svg.encode("utf-8"))
    renderer = QSvgRenderer(data)

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()

    icon = QIcon(pixmap)
    return icon


def icon(name: str, color: str = "#E6E6E6", size: int = 20) -> QIcon:
    """按名称取图标（未知名返回空 QIcon，不报错）。"""
    body = _SVG_PATHS.get(name)
    if body is None:
        return QIcon()
    return _make_icon(body, color, size)
