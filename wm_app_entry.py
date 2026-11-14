"""PyInstaller 打包入口（Albert水印工坊）。

与开发期 run.py 等价，但路径处理为打包模式友好：
直接把 src 加入 sys.path 后调用 watermarker.app.main()。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 打包时入口脚本位于项目根，src 在其下
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

from watermarker.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
