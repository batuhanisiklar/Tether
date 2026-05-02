"""
HTTP MJPEG stream receiver.
"""

from __future__ import annotations

import logging
import threading
import time

import requests
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from desktop_app.config import Network

logger = logging.getLogger(__name__)

_MIN_FRAME_INTERVAL = 1.0 / 30.0
_RETRY_DELAY_SEC = 1.0


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
        while not self._stop.is_set():
            try:
                # Keep connect timeout low but allow longer read timeout for live streams.
                with requests.get(
                    self._url,
                    stream=True,
                    timeout=(5, 45),
                ) as r:
                    r.raise_for_status()
                    buf = bytearray()
                    last_emit = 0.0

                    for chunk in r.iter_content(chunk_size=Network.MJPEG_CHUNK_SIZE):
                        if self._stop.is_set():
                            break
                        if not chunk:
                            continue
                        buf.extend(chunk)

                        jstart = buf.find(Network.JPEG_MARKER_START)
                        while jstart >= 0:
                            jend = buf.find(Network.JPEG_MARKER_END, jstart + 2)
                            if jend < 0:
                                if jstart > 0:
                                    del buf[:jstart]
                                break

                            jpeg = bytes(buf[jstart : jend + 2])
                            now = time.monotonic()
                            if (now - last_emit) >= _MIN_FRAME_INTERVAL:
                                self._emit_frame(jpeg)
                                last_emit = now

                            del buf[: jend + 2]
                            jstart = buf.find(Network.JPEG_MARKER_START)

                        if len(buf) > 2_000_000:
                            del buf[: len(buf) - 800_000]

            except Exception as e:
                if self._stop.is_set():
                    break
                logger.warning("MJPEG: %s", e)
                QTimer.singleShot(0, lambda err=str(e): self.error_occurred.emit(err))
                time.sleep(_RETRY_DELAY_SEC)

        QTimer.singleShot(0, self.stream_stopped.emit)
