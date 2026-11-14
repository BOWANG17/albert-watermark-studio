"""S3 后台导出线程。

把 core.batch.process_batch 包进 QThread，通过 Signal 把进度/失败/完成
跨线程安全地传回主线程（UI）。

关键点：任何耗时的图像处理都不能在主线程跑，否则界面卡死。
规律：超过 ~100ms 的操作，都放进这个线程。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..core.batch import process_batch
from ..core.info_bar import InfoBarStyle
from ..core.watermark import ImageWatermark, TextWatermark


class ExportWorker(QThread):
    """批量导出的后台线程。"""

    # (当前序号, 总数, 当前文件名)
    progress = Signal(int, int, str)
    # (失败文件名, 错误信息)
    failed = Signal(str, str)
    # (成功数量, 失败数量, 输出目录)
    finished = Signal(int, int, str)

    def __init__(
        self,
        files: list[str],
        output_dir: str,
        text_wm: Optional[TextWatermark] = None,
        image_wm: Optional[ImageWatermark] = None,
        crop_ratio=None,
        tiled: Optional[dict] = None,
        quality: int = 92,
        output_format: Optional[str] = None,
        keep_exif: bool = False,
        info_bar_style: Optional[InfoBarStyle] = None,
        per_image_params: Optional[dict] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._files = files
        self._output_dir = output_dir
        self._text_wm = text_wm
        self._image_wm = image_wm
        self._crop_ratio = crop_ratio
        self._tiled = tiled
        self._quality = quality
        self._output_format = output_format
        self._keep_exif = keep_exif
        self._info_bar_style = info_bar_style
        self._per_image_params = per_image_params
        self._cancel = False

    def cancel(self):
        """请求取消（线程安全，由主线程调用）。"""
        self._cancel = True

    def run(self):
        """线程主体。"""
        result = process_batch(
            self._files,
            self._output_dir,
            text_wm=self._text_wm,
            image_wm=self._image_wm,
            crop_ratio=self._crop_ratio,
            tiled=self._tiled,
            quality=self._quality,
            output_format=self._output_format,
            keep_exif=self._keep_exif,
            info_bar_style=self._info_bar_style,
            per_image_params=self._per_image_params,
            progress=lambda i, total, name: self.progress.emit(i, total, name),
            should_cancel=lambda: self._cancel,
        )
        self.finished.emit(result.ok_count, result.fail_count, str(self._output_dir))
