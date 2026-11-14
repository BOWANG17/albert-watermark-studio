"""S0 命令行入口：给一张图加文字水印，验证核心算法。

用法：
    python wm.py 输入图.jpg [输出图.jpg]

示例：
    python wm.py test.jpg                    # 输出 test_wm.jpg
    python wm.py test.jpg out.jpg            # 指定输出名

这是整个项目的第一步。跑通它就说明核心逻辑对了，
后面的 GUI 只是给这些参数套一层界面。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让脚本能在不安装包的情况下直接 import 到 src 下的模块
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from PIL import Image  # noqa: E402
from watermarker.core.watermark import TextWatermark, add_text_watermark  # noqa: E402

# 一个系统自带、含中文字形的字体（冬青黑体，macOS 默认都有）
# 正式版会把字体文件打包进 assets/fonts，这里先用系统字体验证效果
_DEFAULT_FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python wm.py 输入图.jpg [输出图.jpg]")
        return 1

    src = Path(sys.argv[1])
    if not src.exists():
        print(f"找不到输入文件: {src}")
        return 1

    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_name(f"{src.stem}_wm{src.suffix}")

    img = Image.open(src)
    wm = TextWatermark(
        text="© 我的名字",
        font_path=_DEFAULT_FONT,
        size_permille=36,
        opacity=0.7,
        color=(255, 255, 255),
        stroke_width=1,
        stroke_color=(0, 0, 0),
        position="右下",
        margin_permille=24,
    )
    out = add_text_watermark(img, wm)
    # JPEG 不支持透明通道，存 JPEG 前转 RGB
    if dst.suffix.lower() in (".jpg", ".jpeg"):
        out = out.convert("RGB")
    out.save(dst, quality=92)
    print(f"完成: {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
