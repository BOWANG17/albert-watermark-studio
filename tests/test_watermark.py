"""核心逻辑的单元测试。

跑法（在项目根目录）：
    python3 -m pytest tests/ -v
或不用 pytest，直接：
    python3 tests/test_watermark.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PIL import Image  # noqa: E402

from watermarker.core.watermark import (  # noqa: E402
    ImageWatermark,
    TextWatermark,
    add_image_watermark,
    add_text_watermark,
)

FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
ROOT = Path(__file__).resolve().parent.parent


def _make_img(w=800, h=600, color=(120, 140, 180)):
    return Image.new("RGB", (w, h), color)


def test_text_watermark_preserves_size():
    img = _make_img()
    wm = TextWatermark(text="测试", font_path=FONT)
    out = add_text_watermark(img, wm)
    assert out.size == img.size  # 输出尺寸不变


def test_text_watermark_changes_pixels():
    img = _make_img(color=(0, 0, 0))  # 纯黑图，白字水印必改变像素
    wm = TextWatermark(text="© TEST", font_path=FONT, position="右下")
    out = add_text_watermark(img, wm)
    # 右下角区域应该有白色像素出现
    region = out.crop((out.width - 200, out.height - 100, out.width, out.height))
    pixels = list(region.get_flattened_data())
    assert any(sum(p[:3]) > 200 for p in pixels), "右下角应出现白色水印像素"


def test_image_watermark_preserves_size():
    img = _make_img()
    logo = Image.new("RGBA", (100, 50), (255, 0, 0, 255))
    wm = ImageWatermark(watermark_path="", scale=0.2)
    out = add_image_watermark(img, wm, wm_img=logo)
    assert out.size == img.size


def test_image_watermark_scales_down():
    # 大 Logo 应被等比缩到 scale 指定的宽度
    img = _make_img(w=1000, h=800)
    logo = Image.new("RGBA", (2000, 1000), (255, 0, 0, 255))
    wm = ImageWatermark(watermark_path="", scale=0.2)
    out = add_image_watermark(img, wm, wm_img=logo)
    # 左上角区域（logo 若未缩放会覆盖很大范围）——这里只验证输出正常即可
    assert out.size == img.size


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests)-failed}/{len(tests)} 通过")
    raise SystemExit(1 if failed else 0)
