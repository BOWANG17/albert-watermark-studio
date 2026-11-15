"""应用启动入口。

用法：
    python -m watermarker.app
或：
    python run.py
"""

from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .resources import resource_path
from .ui.main_window import MainWindow

# QSS 皮肤路径（相对资源根，兼容开发/打包两种模式）
_THEME_PATH = resource_path("ui", "theme.qss")
_THEME_LIGHT_PATH = resource_path("ui", "theme_light.qss")


def _load_theme(app: QApplication, light: bool = False) -> None:
    """加载 QSS 样式表，去掉 Qt 默认的旧外观。

    light=True 时加载浅色主题，否则加载深色主题。
    """
    path = _THEME_LIGHT_PATH if light else _THEME_PATH
    try:
        qss = path.read_text(encoding="utf-8")
        app.setStyleSheet(qss)
    except OSError:
        # 样式表加载失败不影响功能，只是界面丑一点
        pass


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Albert水印工坊")
    app.setOrganizationName("personal")

    # 窗口图标（Windows 任务栏/标题栏图标依赖它；macOS 由 Bundle 图标兜底）。
    # 用品牌 α 图标作为运行时窗口图标，避免 Windows 任务栏显示默认 exe 图标。
    _icon_path = resource_path("assets", "icons", "alpha-orange.png")
    if _icon_path.exists():
        _app_icon = QIcon(str(_icon_path))
        app.setWindowIcon(_app_icon)

    _load_theme(app)

    window = MainWindow()
    if _icon_path.exists():
        window.setWindowIcon(_app_icon)
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
