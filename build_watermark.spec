# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Albert水印工坊）。

用法（在项目根目录，venv 已激活）：
    pyinstaller --clean --noconfirm build_watermark.spec

产物：
    dist/Albert水印工坊.app  （自包含，含 Python 运行时 + PySide6 + Pillow + 资源）
"""

from pathlib import Path

# 项目根目录（spec 所在目录）
ROOT = Path(SPECPATH)  # noqa: F821  (PyInstaller 注入 SPECPATH)

# 入口脚本
ENTRY = ROOT / "wm_app_entry.py"

# 图标（复用之前生成的 icns，若不存在则回退无图标）
ICON = ROOT / "build" / "Albert水印工坊.icns"
icon_path = str(ICON) if ICON.exists() else None

# 需要随包收集的数据文件（相对项目根 → 打包后相对 _MEIPASS 的路径）
datas = [
    (str(ROOT / "src" / "watermarker" / "ui" / "theme.qss"), "ui"),
    (str(ROOT / "src" / "watermarker" / "ui" / "theme_light.qss"), "ui"),
    (str(ROOT / "src" / "watermarker" / "assets" / "icons"), "assets/icons"),
    (str(ROOT / "src" / "watermarker" / "assets" / "fonts"), "assets/fonts"),
]

a = Analysis(
    [str(ENTRY)],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
        "pydoc",
        "email",
        "http",
        "xmlrpc",
        "test",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Albert水印工坊",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI 应用，不弹终端
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Albert水印工坊",
)

app = BUNDLE(
    coll,
    name="Albert水印工坊.app",
    icon=icon_path,
    bundle_identifier="personal.watermark.oneline",
    info_plist={
        "CFBundleName": "Albert水印工坊",
        "CFBundleDisplayName": "Albert水印工坊",
        "CFBundleShortVersionString": "1.2.0",
        "CFBundleVersion": "1.2.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "CFBundleDocumentTypes": [],
    },
)
