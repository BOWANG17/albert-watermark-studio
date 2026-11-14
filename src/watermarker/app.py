"""应用启动入口。

用法：
    python -m watermarker.app
或：
    python run.py
"""

from __future__ import annotations

import sys

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

    _load_theme(app)

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
