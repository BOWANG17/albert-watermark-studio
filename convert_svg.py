"""把品牌 logo SVG 转成透明底 PNG 贴图。

用 PySide6 的 QSvgRenderer 渲染（项目已依赖），无需额外库。
输出：统一高度 512px，宽度按比例，透明底，保留原色。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SRC_DIR = Path("/Users/mac/Desktop/svg素材")
OUT_DIR = Path("/Users/mac/WorkBuddy/2026-11-06-20-04-07/watermark-app/src/watermarker/assets/icons")

TARGET_HEIGHT = 512

# 品牌 -> 源 SVG 文件名（每个品牌选 1 个最清晰的）
BRANDS = {
    "sony-alpha": "Sony_Alpha_logo.svg",
    "canon": "Canon_wordmark.svg",
    "nikon": "Nikon_Logo.svg",
    "fujifilm": "Fujifilm_logo.svg",
    "hasselblad": "Hasselblad_logo.svg",
    "leica": "Leica_Camera.svg",
    "insta360": "Insta360_logo_(transparent).svg",
    "dji": "dji-3.svg",
    "ricoh": "ricoh-logo-2005-neu.svg",
    "lumix": "lumix.svg",
}


def render_svg_to_png(svg_path: Path, out_path: Path, target_h: int = TARGET_HEIGHT):
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        print(f"  ❌ 无效 SVG: {svg_path.name}")
        return False

    size = renderer.defaultSize()
    if size.width() <= 0 or size.height() <= 0:
        print(f"  ❌ 尺寸异常: {svg_path.name} ({size.width()}x{size.height()})")
        return False

    # 按目标高度等比缩放宽度
    scale = target_h / size.height()
    target_w = max(1, round(size.width() * scale))

    img = QImage(target_w, target_h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, target_w, target_h))
    painter.end()

    ok = img.save(str(out_path), "PNG")
    if ok:
        print(f"  ✅ {out_path.name}  ({target_w}x{target_h})")
    else:
        print(f"  ❌ 保存失败: {out_path.name}")
    return ok


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, src_name in BRANDS.items():
        src = SRC_DIR / src_name
        if not src.exists():
            print(f"⚠️ 源文件不存在: {src_name}")
            continue
        render_svg_to_png(src, OUT_DIR / f"{name}.png")


if __name__ == "__main__":
    main()
