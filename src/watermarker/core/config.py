"""参数配置的序列化 / 反序列化（JSON）。

把界面上的所有水印参数保存成一个 dict，存到用户目录，下次打开恢复。
预设也可以导出成文件，方便备份/分享。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from .watermark import ImageWatermark, TextWatermark


def text_wm_to_dict(wm: TextWatermark) -> dict[str, Any]:
    return asdict(wm)


def text_wm_from_dict(d: dict[str, Any]) -> TextWatermark:
    d = dict(d)
    # JSON 会把 tuple 存成 list，这里转回 tuple（否则 wm.color + (alpha,) 会报错）
    for key in ("color", "stroke_color"):
        if key in d and not isinstance(d[key], tuple):
            d[key] = tuple(d[key])
    return TextWatermark(**d)


def image_wm_to_dict(wm: ImageWatermark) -> dict[str, Any]:
    return asdict(wm)


def image_wm_from_dict(d: dict[str, Any]) -> ImageWatermark:
    return ImageWatermark(**d)


def save_json(obj: dict, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def default_config_dir() -> Path:
    """配置目录：用户主目录下 .watermarker/"""
    return Path.home() / ".watermarker"


def config_file() -> Path:
    return default_config_dir() / "config.json"
