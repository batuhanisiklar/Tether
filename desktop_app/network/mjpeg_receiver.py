import threading
import requests
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage

from desktop_app.config import Network


class MjpegReceiver(QObject):

    frame_ready = pyqtSignal(QPixmap)
    error_occurred = pyqtSignal(str)
    stream_stopped = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._running = False
        self._url: str = ""

    def start(self, url: str):
        if self._running:
            self.stop()

        self._url = url
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=Network.MJPEG_JOIN_TIMEOUT_SEC)
        self._thread = None

    def _run(self):
        try:
            with requests.get(
                self._url,
                stream=True,
                timeout=Network.MJPEG_REQUEST_TIMEOUT_SEC,
            ) as resp:
                resp.raise_for_status()
                buffer = b""
                for chunk in resp.iter_content(chunk_size=Network.MJPEG_CHUNK_SIZE):
                    if not self._running:
                        break
                    buffer += chunk
                    while True:
                        start = buffer.find(Network.JPEG_MARKER_START)
                        end = buffer.find(Network.JPEG_MARKER_END)
                        if start == -1 or end == -1 or end <= start:
                            break
                        end_len = len(Network.JPEG_MARKER_END)
                        jpeg_data = buffer[start : end + end_len]
                        buffer = buffer[end + end_len :]

                        if not self._running:
                            break

                        pixmap = self._bytes_to_pixmap(jpeg_data)
                        if pixmap and not pixmap.isNull():
                            self.frame_ready.emit(pixmap)

        except requests.exceptions.RequestException as e:
            if self._running:
                self.error_occurred.emit(f"Stream hatası: {e}")
        finally:
            self._running = False
            self.stream_stopped.emit()

    @staticmethod
    def _bytes_to_pixmap(data: bytes) -> QPixmap | None:
        img = QImage()
        if img.loadFromData(data, "JPEG"):
            return QPixmap.fromImage(img)
        return None
