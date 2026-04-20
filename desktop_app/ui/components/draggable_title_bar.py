from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QFrame, QMainWindow, QWidget


class DraggableTitleBar(QFrame):
    """Frameless pencerede fare sürükleme ile taşıma sağlar."""

    def __init__(self, window: QMainWindow, parent: QWidget | None = None):
        super().__init__(parent)
        self._window = window
        self._drag_pos: QPoint | None = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)
