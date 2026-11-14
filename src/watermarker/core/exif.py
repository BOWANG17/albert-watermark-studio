"""读取照片 EXIF 拍摄参数，供「摄影信息条」使用。

只依赖 Pillow，不 import GUI 库（遵循 core/ui 分离约定）。

字段映射：EXIF 标签 ID → 人类可读的拍摄参数。
- 相机型号 / 镜头 / 焦距 / 光圈 / 快门 / ISO / 拍摄时间 / 地点（GPS）
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

from PIL import Image
from PIL.ExifTags import TAGS

# 常用的 EXIF 标签 ID（Pillow 的 getexif 返回的 key 就是这些数字）
TAG_MAKE = 0x010F        # 相机制造商，如 SONY
TAG_MODEL = 0x0110       # 相机型号，如 ILCE-6300
TAG_LENS = 0xA434        # 镜头型号
TAG_FOCAL = 0x920A       # 焦距（mm），存的是有理数
TAG_FNUMBER = 0x829D     # 光圈 F 值，有理数
TAG_EXPOSURE = 0x829A    # 曝光时间（秒），有理数，如 1/200
TAG_ISO = 0x8827         # ISO
TAG_DATETIME = 0x9003    # 拍摄时间字符串 "YYYY:MM:DD HH:MM:SS"
TAG_DATETIME_ALT = 0x0132  # 部分相机（如索尼）用这个标签存时间
TAG_OFFSET_TIME = 0x9011  # 时区偏移
TAG_ORIENTATION = 0x0112  # 方向（transpose 前有用）

# GPS 相关（在 GPSInfo 字典里）
GPS_LAT = 2
GPS_LAT_REF = 1
GPS_LON = 4
GPS_LON_REF = 3


def _rational_to_float(v) -> Optional[float]:
    """Pillow 里有理数存成 IFDRational 或 tuple，转成 float。"""
    if v is None:
        return None
    if isinstance(v, tuple) and len(v) == 2:
        try:
            return float(v[0]) / float(v[1])
        except (ZeroDivisionError, ValueError, TypeError):
            return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _format_fnumber(v) -> str:
    """光圈：2.8 -> 'f/2.8'。"""
    f = _rational_to_float(v)
    if f is None:
        return ""
    return f"f/{f:g}"


def _format_exposure(v) -> str:
    """快门：0.005 -> '1/200s'；0.5 -> '1/2s'；1 -> '1s'。"""
    f = _rational_to_float(v)
    if f is None:
        return ""
    if f < 1:
        # 取倒数，凑成常见快门档位
        inv = 1.0 / f
        # 快门档位常用：1, 2, 4, 8, 15, 30, 60, 125, 250, 500, 1000, 2000...
        if inv >= 1:
            return f"1/{round(inv)}s"
        return f"{f:g}s"
    return f"{f:g}s"


def _format_focal(v) -> str:
    """焦距：35.0 -> '35mm'。"""
    f = _rational_to_float(v)
    if f is None:
        return ""
    return f"{f:g}mm"


def _format_datetime(v) -> str:
    """拍摄时间：'2026:02:02 16:33:00' -> '2026.02.02 16:33'。"""
    if not v:
        return ""
    s = str(v).strip()
    # 尝试多种格式
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y.%m.%d %H:%M")
        except ValueError:
            continue
    return s.replace(":", ".", 2).replace("-", ".", 2)[:16]


def read_exif(path: Union[str, Path]) -> dict:
    """读取照片的关键拍摄参数，返回 dict。

    返回字段（缺失时为 "" 或 None）：
        make, model, lens, focal, fnumber, exposure, iso,
        datetime, latitude, longitude

    带进程内缓存：同一路径的 EXIF 只解析一次（画廊缩略图/预览会反复调用，
    避免每次重新打开文件拖慢 UI）。EXIF 不会在运行中变化，缓存是安全的。
    """
    return _read_exif_cached(str(path))


@lru_cache(maxsize=256)
def _read_exif_cached(path: str) -> dict:
    result = {
        "make": "",
        "model": "",
        "lens": "",
        "focal": "",
        "fnumber": "",
        "exposure": "",
        "iso": "",
        "datetime": "",
        "latitude": None,
        "longitude": None,
    }

    try:
        img = Image.open(path)
        exif = img.getexif()
    except Exception:
        return result

    if not exif:
        return result

    raw = dict(exif)

    # 焦距/光圈/快门/ISO 通常在 Exif 子 IFD（0x8769）里，需单独取
    exif_ifd: dict = {}
    try:
        exif_ifd = dict(exif.get_ifd(0x8769)) if exif.get_ifd(0x8769) else {}
    except Exception:
        exif_ifd = {}

    # 合并：子 IFD 优先（字段更全），顶层兜底
    merged = dict(raw)
    merged.update(exif_ifd)

    make = merged.get(TAG_MAKE)
    model = merged.get(TAG_MODEL)
    lens = merged.get(TAG_LENS)
    focal = merged.get(TAG_FOCAL)
    fnum = merged.get(TAG_FNUMBER)
    expo = merged.get(TAG_EXPOSURE)
    iso = merged.get(TAG_ISO)
    dt = merged.get(TAG_DATETIME) or merged.get(TAG_DATETIME_ALT)

    result["make"] = str(make).strip() if make else ""
    result["model"] = str(model).strip() if model else ""
    result["lens"] = str(lens).strip() if lens else ""
    result["focal"] = _format_focal(focal)
    result["fnumber"] = _format_fnumber(fnum)
    result["exposure"] = _format_exposure(expo)
    result["iso"] = str(iso).strip() if iso else ""
    result["datetime"] = _format_datetime(dt)

    # GPS（可选，多数照片没有）
    gps = raw.get(0x8825)  # GPSInfo IFD
    if gps:
        try:
            lat, lon = _parse_gps(gps)
            result["latitude"] = lat
            result["longitude"] = lon
        except Exception:
            pass

    return result


def _parse_gps(gps) -> tuple[Optional[float], Optional[float]]:
    """解析 GPSInfo，返回 (纬度, 经度)，None 表示无。"""
    lat = _gps_to_decimal(gps.get(GPS_LAT), gps.get(GPS_LAT_REF))
    lon = _gps_to_decimal(gps.get(GPS_LON), gps.get(GPS_LON_REF))
    return lat, lon


def _gps_to_decimal(value, ref) -> Optional[float]:
    if not value:
        return None
    try:
        d, m, s = value
        dec = float(d) + float(m) / 60 + float(s) / 3600
        if ref in ("S", "W"):
            dec = -dec
        return dec
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def exif_summary(path: Union[str, Path]) -> str:
    """把 EXIF 汇总成一行参数文本，如 '35mm  f/2.8  1/200s  ISO100'。"""
    d = read_exif(path)
    parts = [p for p in (d["focal"], d["fnumber"], d["exposure"],
                         f"ISO{d['iso']}" if d["iso"] else "") if p]
    return "  ".join(parts)
