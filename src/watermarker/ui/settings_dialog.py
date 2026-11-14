"""「关于 / 开源字体授权」设置对话框。

点导出栏的 info 图标进入，展示：
- 软件信息（名称、版本）
- 使用到的开源字体及其授权协议说明

这是纯信息展示页，不涉及任何设置项的读写。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QVBoxLayout,
    QScrollArea,
    QWidget,
    QHBoxLayout,
    QPushButton,
)

APP_NAME = "Albert水印工坊"
APP_VERSION = "1.2.0"

# 开源字体授权说明：(字体名, 类型, 授权协议, 说明)
FONT_CREDITS = [
    (
        "思源宋体 (Source Han Serif)",
        "衬线宋体",
        "SIL Open Font License 1.1",
        "Adobe 与 Google 联合开发的开源字体，可免费商用、自由修改与分发。",
    ),
    (
        "MiSans",
        "无衬线黑体",
        "小米《MiSans 字体知识产权许可协议》",
        "小米官方字体，允许免费使用（含商用）；使用时需注明字体来源，"
        "且不得对字体文件本身进行改编或单独分发。",
    ),
]


class SettingsDialog(QDialog):
    """关于 / 字体授权说明对话框。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关于 {APP_NAME}")
        self.setObjectName("aboutDialog")
        self.setModal(True)
        self.resize(460, 420)

        root = QVBoxLayout(self)

        # 软件信息
        title = QLabel(APP_NAME)
        title.setObjectName("aboutTitle")
        title.setAlignment(Qt.AlignCenter)
        version = QLabel(f"版本 {APP_VERSION}")
        version.setObjectName("aboutVersion")
        version.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        root.addWidget(version)
        root.addSpacing(8)

        # 开源字体说明标题
        fonts_header = QLabel("本软件使用了以下开源字体")
        fonts_header.setObjectName("aboutSection")
        root.addWidget(fonts_header)

        # 字体授权列表（放在滚动区，避免字体多时溢出）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content.setObjectName("aboutContent")
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        for name, kind, license_name, desc in FONT_CREDITS:
            col.addWidget(self._build_font_card(name, kind, license_name, desc))

        # 底部补充说明
        tip = QLabel(
            "字体版权信息仅供参考，完整条款请以各字体官方发布的许可协议为准。"
        )
        tip.setObjectName("aboutTip")
        tip.setWordWrap(True)
        col.addWidget(tip)
        col.addStretch(1)

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # 关闭按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("aboutClose")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

    @staticmethod
    def _build_font_card(name: str, kind: str, license_name: str, desc: str) -> QWidget:
        """构建单个字体的授权说明卡片。"""
        card = QWidget()
        card.setObjectName("aboutFontCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        head = QHBoxLayout()
        name_label = QLabel(name)
        name_label.setObjectName("aboutFontName")
        kind_label = QLabel(kind)
        kind_label.setObjectName("aboutFontKind")
        head.addWidget(name_label)
        head.addStretch()
        head.addWidget(kind_label)
        lay.addLayout(head)

        license_label = QLabel(f"授权：{license_name}")
        license_label.setObjectName("aboutFontLicense")
        license_label.setWordWrap(True)
        lay.addWidget(license_label)

        desc_label = QLabel(desc)
        desc_label.setObjectName("aboutFontDesc")
        desc_label.setWordWrap(True)
        lay.addWidget(desc_label)

        return card
