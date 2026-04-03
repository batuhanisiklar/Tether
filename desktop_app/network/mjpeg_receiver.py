"""
HTTP MJPEG akışından JPEG kareleri ayıklar (boundary veya ham akış).
"""

from __future__ import annotations

import logging
import threading

import requests
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap

from desktop_app.config import Network

logger = logging.getLogger(__name__)


class MjpegReceiver(QObject):
    frame_ready = pyqtSignal(QPixmap)
    error_occurred = pyqtSignal(str)
    stream_stopped = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._url: str = ""

    def start(self, stream_url: str) -> None:
        self.stop()
        if not stream_url or not stream_url.startswith("http"):
            return
        self._url = stream_url
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _emit_frame(self, jpeg: bytes) -> None:
        if len(jpeg) < 4 or not jpeg.startswith(Network.JPEG_MARKER_START):
            return

        def _work() -> None:
            img = QImage()
            if img.loadFromData(jpeg, "JPEG"):
                pm = QPixmap.fromImage(img)
                if not pm.isNull():
                    self.frame_ready.emit(pm)

        QTimer.singleShot(0, _work)

    def _run(self) -> None:
        try:
            with requests.get(self._url, stream=True, timeout=Network.MJPEG_REQUEST_TIMEOUT_SEC) as r:
                r.raise_for_status()
                buf = b""
                for chunk in r.iter_content(chunk_size=Network.MJPEG_CHUNK_SIZE):
                    if self._stop.is_set():
                        break
                    if not chunk:
                        continue
                    buf += chunk
                    jstart = buf.find(Network.JPEG_MARKER_START)
                    while jstart >= 0:
                        jend = buf.find(Network.JPEG_MARKER_END, jstart + 2)
                        if jend < 0:
                            buf = buf[jstart:]
                            break
                        jpeg = buf[jstart : jend + 2]
                        self._emit_frame(jpeg)
                        buf = buf[jend + 2 :]
                        jstart = buf.find(Network.JPEG_MARKER_START)
                    if len(buf) > 2_000_000:
                        buf = buf[-800_000:]
        except Exception as e:
            logger.warning("MJPEG: %s", e)
            QTimer.singleShot(0, lambda: self.error_occurred.emit(str(e)))
        finally:
            QTimer.singleShot(0, self.stream_stopped.emit)
