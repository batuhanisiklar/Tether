"""
Ekran Görüntüsü Widget'ı
=========================
Frame'leri gösterir; görsel döndürme (0/90/180/270°) destekler.
Koordinat normalizasyonu hem gerçek image rect hem de döndürme açısına göre yapılır.
"""

from PyQt6.QtWidgets import QLabel, QSizePolicy
from PyQt6.QtCore import Qt, QRect, pyqtSignal, QPoint
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QTransform

from desktop_app.config import Ui


class ScreenWidget(QLabel):
    """
    Frame görüntüleyen ve dokunma olaylarını yakalayan widget.

    Özellikler:
        • set_rotation(deg): Görüntüyü 0/90/180/270° döndürür.
          Koordinat normalizasyonu açıya göre otomatik ayarlanır.
        • Sadece gerçek görüntü alanında tıklama aktif — boş kenarlarda
          hiçbir komut gönderilmez.

    Sinyaller:
        touch_event(x, y)           – Normalize [0,1] tıklama
        swipe_event(x1,y1,x2,y2)   – Normalize kaydırma
    """

    touch_event = pyqtSignal(float, float)
    swipe_event = pyqtSignal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(280, 500)
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {Ui.SCREEN_PLACEHOLDER_BG};
                border: 1px solid {Ui.SCREEN_BORDER};
                border-radius: 4px;
            }}
        """)

        self._current_pixmap: QPixmap | None = None
        self._drag_start: QPoint | None = None
        self._rotation_deg: int = 0   # 0 | 90 | 180 | 270

        self._show_placeholder()

    # ─── PUBLIC ────────────────────────────────────────────────────────────────

    def set_frame(self, pixmap: QPixmap):
        """Yeni bir frame göster."""
        if pixmap is None or pixmap.isNull():
            return
        self._current_pixmap = pixmap
        self._render()

    def clear_frame(self):
        """Stream durduğunda placeholder göster."""
        self._current_pixmap = None
        self._show_placeholder()

    def set_rotation(self, degrees: int):
        """
        Görüntüyü belirtilen açıda döndür (0, 90, 180, 270).
        Koordinat normalizasyonu otomatik güncellenir.
        """
        self._rotation_deg = degrees % 360
        if self._current_pixmap:
            self._render()
        else:
            self._show_placeholder()

    def toggle_rotation(self):
        """Her çağrıda 90° saat yönünde döndür (0→90→180→270→0)."""
        self.set_rotation((self._rotation_deg + 90) % 360)

    # ─── MOUSE EVENTS ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            if self._image_rect().contains(pos):
                self._drag_start = pos

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start:
            end = event.pos()
            start = self._drag_start
            self._drag_start = None

            dx = abs(end.x() - start.x())
            dy = abs(end.y() - start.y())

            if dx < Ui.TOUCH_THRESHOLD_PX and dy < Ui.TOUCH_THRESHOLD_PX:
                nx, ny = self._normalize(end.x(), end.y())
                self.touch_event.emit(nx, ny)
            else:
                nx1, ny1 = self._normalize(start.x(), start.y())
                nx2, ny2 = self._normalize(end.x(), end.y())
                self.swipe_event.emit(nx1, ny1, nx2, ny2)

    def mouseMoveEvent(self, event):
        if self._image_rect().contains(event.pos()):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # ─── COORDINATE MAPPING ────────────────────────────────────────────────────

    def _image_rect(self) -> QRect:
        """Render edilen (ölçeklenmiş+döndürülmüş) pixmap'in gerçek dikdörtgeni."""
        p = self.pixmap()
        if p is None or p.isNull():
            return self.rect()
        pw, ph = p.width(), p.height()
        ww, wh = self.width(), self.height()
        x = (ww - pw) // 2
        y = (wh - ph) // 2
        return QRect(x, y, pw, ph)

    def _normalize(self, x: int, y: int) -> tuple[float, float]:
        """
        Widget piksel koordinatını telefon [0,1] koordinatına çevir.
        Döndürme açısına göre eksen eşleştirmesi yapılır.
        """
        rect = self._image_rect()
        # Görüntü sınırlarına clamp et
        rx = max(rect.left(), min(x, rect.right()))
        ry = max(rect.top(), min(y, rect.bottom()))
        # [0,1] aralığına normalize et (görüntü içi)
        nx = (rx - rect.left()) / max(rect.width(), 1)
        ny = (ry - rect.top()) / max(rect.height(), 1)

        # Döndürme açısına göre telefon koordinatına çevir
        if self._rotation_deg == 90:
            # Ekran 90° CW döndü; x_widget → y_telefon, y_widget → (1-x_telefon)
            nx, ny = ny, 1.0 - nx
        elif self._rotation_deg == 180:
            nx, ny = 1.0 - nx, 1.0 - ny
        elif self._rotation_deg == 270:
            nx, ny = 1.0 - ny, nx

        return round(nx, Ui.COORD_PRECISION), round(ny, Ui.COORD_PRECISION)

    # ─── RENDERING ─────────────────────────────────────────────────────────────

    def _render(self):
        """Mevcut pixmap'i döndürerek ve widget boyutuna uyarlayarak göster."""
        if not self._current_pixmap:
            return
        source = self._current_pixmap
        if self._rotation_deg != 0:
            transform = QTransform().rotate(self._rotation_deg)
            source = source.transformed(transform, Qt.TransformationMode.SmoothTransformation)
        scaled = source.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_pixmap:
            self._render()

    def _show_placeholder(self):
        """Bağlantı bekleme ekranı."""
        ph = QPixmap(self.minimumSize())
        ph.fill(QColor(Ui.SCREEN_PLACEHOLDER_BG))
        painter = QPainter(ph)
        painter.setPen(QColor(Ui.SCREEN_PLACEHOLDER_FG))
        painter.setFont(QFont("Segoe UI", 11))
        painter.drawText(
            ph.rect(),
            Qt.AlignmentFlag.AlignCenter,
            "Telefon bağlantısı bekleniyor"
        )
        painter.end()
        self.setPixmap(ph)
