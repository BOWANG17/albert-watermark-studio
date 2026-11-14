"""比例裁剪：把图片裁成指定宽高比（居中裁剪）。

用于"先裁剪、再加水印"的流程（社交平台发图常用）。
裁剪是居中取最大区域，保持比例，不拉伸不变形。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageOps

# 支持的裁剪比例：名 -> (宽, 高)
RATIOS = {
    "不裁剪": None,
    "1:1": (1, 1),
    "4:5": (4, 5),
    "3:4": (3, 4),
    "9:16": (9, 16),
    "16:9": (16, 9),
}


@dataclass
class CropSpec:
    """裁剪参数。ratio 为 (宽, 高) 元组，None 表示不裁剪。"""

    ratio: Optional[tuple[int, int]] = None


def crop_to_ratio(img: Image.Image, ratio: tuple[int, int]) -> Image.Image:
    """居中裁剪到指定宽高比，返回新图（不改动原图）。"""
    rw, rh = ratio
    w, h = img.size
    target_ratio = rw / rh
    current_ratio = w / h

    if abs(current_ratio - target_ratio) < 1e-6:
        return img.copy()

    if current_ratio > target_ratio:
        # 原图偏宽，裁宽度
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:
        # 原图偏高，裁高度
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)

    return img.crop(box)


def apply_crop(img: Image.Image, spec: CropSpec) -> Image.Image:
    """按 CropSpec 裁剪（含 EXIF 方向纠正）。ratio 为 None 时不裁剪。"""
    img = ImageOps.exif_transpose(img)
    if spec.ratio is None:
        return img
    return crop_to_ratio(img, spec.ratio)
