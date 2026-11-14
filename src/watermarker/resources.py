"""资源路径解析（兼容开发模式与 PyInstaller 打包模式）。

开发模式：资源位于源码树内（相对本包）。
打包模式：PyInstaller 会把 datas 解压到临时目录 sys._MEIPASS。

用法：
    from .resources import resource_path
    p = resource_path("ui", "theme.qss")
"""

from __future__ import annotations

import sys
from pathlib import Path


def _base_dir() -> Path:
    """返回资源根目录（打包时为 _MEIPASS，开发时为包目录）。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后运行时
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # 开发模式：watermarker 包目录
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """拼接资源相对路径，返回绝对 Path。"""
    return _base_dir().joinpath(*parts)
