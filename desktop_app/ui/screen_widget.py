"""
Ekran Görüntüsü Widget'ı
=========================
Frame'leri gösterir; görsel döndürme (0/90/180/270°) destekler.
Koordinat normalizasyonu hem gerçek image rect hem de döndürme açısına göre yapılır.
"""

from PyQt6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
)
from PyQt6.QtCore import Qt, QRect, QRectF, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import (
    QPixmap,
    QPainter,
    QColor,
    QFont,
    QTransform,
    QKeyEvent,
    QPainterPath,
    QPen,
)

from desktop_app.config import Ui
from desktop_app.config.constants import AndroidKeyCodes


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
    remote_key_pressed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(96, 160)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
        self._last_source_key: int | None = None
        self._last_transform_key: tuple[int, int] | None = None
        self._transformed_pixmap: QPixmap | None = None
        self._last_render_key: tuple[int, int, int, int] | None = None

        self._show_placeholder()

    # ─── PUBLIC ────────────────────────────────────────────────────────────────

    def set_frame(self, pixmap: QPixmap):
        """Yeni bir frame göster."""
        if pixmap is None or pixmap.isNull():
            return
        self._current_pixmap = pixmap
        self._last_source_key = pixmap.cacheKey()
        self._render()

    def clear_frame(self):
        """Stream durduğunda placeholder göster."""
        self._current_pixmap = None
        self._last_source_key = None
        self._last_transform_key = None
        self._transformed_pixmap = None
        self._last_render_key = None
        self._show_placeholder()

    def set_rotation(self, degrees: int):
        """
        Görüntüyü belirtilen açıda döndür (0, 90, 180, 270).
        Koordinat normalizasyonu otomatik güncellenir.
        """
        try:
            deg = int(degrees)
        except (TypeError, ValueError):
            deg = 0
        # Yakın 90 katına snap et; beklenmeyen değerlerde de stabil kalır.
        self._rotation_deg = (round(deg / 90.0) * 90) % 360
        self._last_render_key = None
        if self._current_pixmap:
            self._render()
        else:
            self._show_placeholder()

    def toggle_rotation(self):
        """Her çağrıda 90° saat yönünde döndür (0→90→180→270→0)."""
        self.set_rotation((self._rotation_deg + 90) % 360)

    def effective_frame_size(self) -> tuple[int, int]:
        """
        Daima masaüstündeki kullanıcı dönüş yönüne göre telefon çerçevesinin (bezel)
        oranını belirler. Gelen yayının (pw, ph) yamuk/yatay olmasına bakılmaz, 
        doğrudan masaüstü çerçevesinin şekli dikey ya da yatay kitlenir.
        """
        base_w, base_h = 1080, 2330
        if self._rotation_deg % 180 != 0:
            return base_h, base_w
        return base_w, base_h

    def displayed_size_for_incoming(self, source_w: int, source_h: int) -> tuple[int, int]:
        """
        Sunucudan gelen karenin piksel boyutu + mevcut masaüstü döndürme ile
        görünür en/boy (çerçeve oranı ve durum çubuğu etiketi bununla uyumlu).
        """
        if source_w <= 0 or source_h <= 0:
            return (1080, 2330)
        if self._rotation_deg % 180 != 0:
            return source_h, source_w
        return source_w, source_h

    # ─── MOUSE EVENTS ──────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
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

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if key == Qt.Key.Key_Escape:
            self.remote_key_pressed.emit(AndroidKeyCodes.BACK)
            event.accept()
            return
        if ctrl and key == Qt.Key.Key_H:
            self.remote_key_pressed.emit(AndroidKeyCodes.HOME)
            event.accept()
            return
        if ctrl and key == Qt.Key.Key_Tab:
            self.remote_key_pressed.emit(AndroidKeyCodes.RECENTS)
            event.accept()
            return
        if ctrl and key == Qt.Key.Key_M:
            self.remote_key_pressed.emit(AndroidKeyCodes.VOL_MUTE)
            event.accept()
            return
        if key == Qt.Key.Key_VolumeUp or (ctrl and key == Qt.Key.Key_Up):
            self.remote_key_pressed.emit(AndroidKeyCodes.VOL_UP)
            event.accept()
            return
        if key == Qt.Key.Key_VolumeDown or (ctrl and key == Qt.Key.Key_Down):
            self.remote_key_pressed.emit(AndroidKeyCodes.VOL_DOWN)
            event.accept()
            return
        super().keyPressEvent(event)

    def get_export_pixmap(self) -> QPixmap | None:
        """Kayıt / pano için: mümkünse ham çözünürlük, yoksa ekrandaki ölçekli görüntü."""
        if self._current_pixmap is not None and not self._current_pixmap.isNull():
            return QPixmap(self._current_pixmap)
        p = self.pixmap()
        if p is None or p.isNull():
            return None
        return QPixmap(p)

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
        w, h = self.width(), self.height()
        # Layout henüz hazır değilken scaled(0,0) boş pixmap → siyah ekran; resizeEvent tekrar dener.
        if w < 4 or h < 4:
            return

        source_key = self._last_source_key or self._current_pixmap.cacheKey()
        render_key = (source_key, self._rotation_deg, w, h)
        if self._last_render_key == render_key:
            return

        transform_key = (source_key, self._rotation_deg)
        if self._last_transform_key != transform_key:
            source = self._current_pixmap
            if self._rotation_deg != 0:
                transform = QTransform().rotate(self._rotation_deg)
                source = source.transformed(transform, Qt.TransformationMode.SmoothTransformation)
            self._transformed_pixmap = source
            self._last_transform_key = transform_key

        if self._transformed_pixmap is None:
            return

        scaled = self._transformed_pixmap.scaled(
            w,
            h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if scaled.isNull():
            return
        self._last_render_key = render_key
        self.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_pixmap:
            self._render()

    def _show_placeholder(self):
        """Bağlantı bekleme ekranı."""
        ph = QPixmap(480, 960)
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
        self._last_render_key = None
        self.setPixmap(ph)


class PhoneDeviceFrame(QWidget):
    """
    Canlı akışı yuvarlatılmış telefon gövdesi (bezel) içinde gösterir;
    üstte ince hoparlör, altta home çizgisi süslemesi.
    """

    _RADIUS = 30.0
    _M_L = 12
    _M_T = 20
    _M_R = 12
    _M_B = 24

    def __init__(self, inner: ScreenWidget, parent=None):
        super().__init__(parent)
        self._inner = inner
        lay = QVBoxLayout(self)
        lay.setContentsMargins(self._M_L, self._M_T, self._M_R, self._M_B)
        lay.setSpacing(0)
        lay.addWidget(inner, stretch=1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def minimumSizeHint(self) -> QSize:
        ih = self._inner.minimumSizeHint()
        return QSize(
            ih.width() + self._M_L + self._M_R,
            ih.height() + self._M_T + self._M_B,
        )

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        body = QPainterPath()
        body.addRoundedRect(r, self._RADIUS, self._RADIUS)
        p.fillPath(body, QColor("#262628"))
        pen = QPen(QColor("#4a4a4e"))
        pen.setWidthF(1.8)
        p.setPen(pen)
        p.drawPath(body)

        is_landscape = r.width() > r.height()
        p.setPen(Qt.PenStyle.NoPen)

        if is_landscape:
            sp_w, sp_h = 5.0, 52.0
            sp = QRectF(r.left() + 10, r.center().y() - sp_h / 2, sp_w, sp_h)
            p.setBrush(QColor("#151516"))
            p.drawRoundedRect(sp, 2.5, 2.5)

            hb_w, hb_h = 4.0, 92.0
            hb = QRectF(r.right() - 14, r.center().y() - hb_h / 2, hb_w, hb_h)
            p.setBrush(QColor("#3a3a3e"))
            p.drawRoundedRect(hb, 2.0, 2.0)
        else:
            sp_w, sp_h = 52.0, 5.0
            sp = QRectF(r.center().x() - sp_w / 2, r.top() + 10, sp_w, sp_h)
            p.setBrush(QColor("#151516"))
            p.drawRoundedRect(sp, 2.5, 2.5)

            hb_w, hb_h = 92.0, 4.0
            hb = QRectF(r.center().x() - hb_w / 2, r.bottom() - 14, hb_w, hb_h)
            p.setBrush(QColor("#3a3a3e"))
            p.drawRoundedRect(hb, 2.0, 2.0)


class StreamAspectFitContainer(QWidget):
    """
    Akış çözünürlüğünün en-boy oranını korur; telefon çerçevesi yatayda gereksiz
    genişlemez (içte siyah şerit oluşmaz).
    """

    def __init__(self, phone_frame: PhoneDeviceFrame, parent=None):
        super().__init__(parent)
        self._phone = phone_frame
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        hl = QHBoxLayout()
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addStretch(1)
        hl.addWidget(self._phone, alignment=Qt.AlignmentFlag.AlignCenter)
        hl.addStretch(1)
        outer.addStretch(1)
        outer.addLayout(hl)
        outer.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._last_w = 1080
        self._last_h = 2330

    def set_stream_dimensions(self, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            return
        if w == self._last_w and h == self._last_h:
            return
        self._last_w = w
        self._last_h = h
        self._refit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit()

    def showEvent(self, event):
        super().showEvent(event)
        self._refit()

    def _refit(self) -> None:
        aw, ah = self.width(), self.height()
        if aw < 8 or ah < 8:
            return
        r = self._last_w / self._last_h
        w_at_full_h = int(ah * r)
        if w_at_full_h <= aw:
            cw, ch = w_at_full_h, ah
        else:
            cw, ch = aw, max(int(aw / r), 1)
        # İç ScreenWidget + PhoneDeviceFrame kenarları için alt sınır
        cw = max(cw, 124)
        ch = max(ch, 224)
        self._phone.setFixedSize(cw, ch)
        self._phone.updateGeometry()
        self.updateGeometry()
