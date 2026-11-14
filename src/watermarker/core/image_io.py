"""图像文件的打开 / 保存 / 元数据处理。

统一封装，保证：
- 打开时自动纠正 EXIF 方向（手机竖拍照片"躺倒"的元凶）
- 保存 JPEG 前自动转 RGB（否则报 cannot write mode RGBA as JPEG）
- 用 with 上下文管理，避免批量时文件句柄泄漏
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from PIL import Image, ImageOps

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"}


def open_image(path: Union[str, Path]) -> Image.Image:
    """打开图片并纠正 EXIF 方向，返回 RGBA 图。"""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # 关键：手机照片方向纠正
    return img


def save_image(
    img: Image.Image,
    path: Union[str, Path],
    quality: int = 92,
    fmt: Optional[str] = None,
    exif: Optional[bytes] = None,
) -> Path:
    """保存图片。JPEG/无 alpha 的格式自动转 RGB；PNG 保留透明通道。

    Args:
        fmt: 强制输出格式（"jpg"/"png"），None 时按文件扩展名推断。
        exif: 原图 EXIF bytes，传入则写回（JPEG/TIFF 支持）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 指定了格式时，替换扩展名
    if fmt is not None:
        fmt = fmt.lower().lstrip(".")
        path = path.with_suffix("." + fmt)
    suffix = path.suffix.lower()

    save_kwargs: dict = {}
    if exif is not None and suffix in (".jpg", ".jpeg", ".tiff", ".tif"):
        save_kwargs["exif"] = exif

    if suffix in (".jpg", ".jpeg"):
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        img.save(path, quality=quality, optimize=True, **save_kwargs)
    elif suffix == ".png":
        if img.mode not in ("RGBA", "LA", "RGB"):
            img = img.convert("RGBA")
        img.save(path)
    else:
        # 其余格式按原样存
        img.save(path, **save_kwargs)

    return path


def list_images(directory: Union[str, Path]) -> list[Path]:
    """列出目录下所有受支持的图片文件（按文件名排序，不含隐藏文件）。"""
    directory = Path(directory)
    files = [
        p for p in directory.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() in SUPPORTED
    ]
    return sorted(files)
