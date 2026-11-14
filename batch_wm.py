"""S1 命令行入口：批量加水印（文字 + 图片），支持九宫格位置。

用法：
    python batch_wm.py 输入文件夹 [输出文件夹]

示例：
    python batch_wm.py ~/Pictures/raw          # 输出到 ~/Pictures/raw/../raw_wm
    python batch_wm.py ~/Pictures/raw ~/out     # 指定输出文件夹

支持的位置：左上 中上 右上 左中 正中 右中 左下 中下 右下
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from watermarker.core.batch import process_batch  # noqa: E402
from watermarker.core.image_io import list_images  # noqa: E402
from watermarker.core.watermark import TextWatermark  # noqa: E402

_DEFAULT_FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python batch_wm.py 输入文件夹 [输出文件夹]")
        return 1

    src_dir = Path(sys.argv[1])
    if not src_dir.is_dir():
        print(f"找不到输入文件夹: {src_dir}")
        return 1

    out_dir = (
        Path(sys.argv[2])
        if len(sys.argv) > 2
        else src_dir.parent / f"{src_dir.name}_wm"
    )

    files = list_images(src_dir)
    if not files:
        print(f"文件夹里没有可处理的图片: {src_dir}")
        return 1
    print(f"共找到 {len(files)} 张图片，输出到 {out_dir}")

    text_wm = TextWatermark(
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

    def on_progress(i: int, total: int, name: str) -> None:
        print(f"[{i}/{total}] 处理: {name}")

    result = process_batch(files, out_dir, text_wm=text_wm, progress=on_progress)

    print("\n=== 完成 ===")
    print(f"成功: {result.ok_count} 张")
    if result.failed:
        print(f"失败: {result.fail_count} 张")
        for name, err in result.failed:
            print(f"  - {name}: {err}")
    print(f"输出目录: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
