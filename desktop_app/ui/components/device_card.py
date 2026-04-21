
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from desktop_app.config import Colors
from desktop_app.ui.styles.app_styles import device_card_style
from desktop_app.ui.utils import (
    address_digits,
    compact_label,
    display_device_name,
    format_address,
)

_C = Colors


class DeviceCard(QFrame):

    CARD_W = 270
    CARD_H = 150

    def __init__(
        self,
        device_id: str,
        address: str | None = None,
        device_name: str | None = None,
        owner_name: str | None = None,
        owner_phone: str | None = None,
        owner_email: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.device_id   = device_id
        self.address     = address_digits(address)
        self.device_name = device_name
        self.owner_name  = (owner_name or "").strip() or None
        self.owner_email = (owner_email or "").strip() or None
        self.owner_phone = (owner_phone or "").strip() or None
        self._online       = False
        self._connect_cb   = None
        self._forget_cb    = None

        self.setFixedSize(self.CARD_W, self.CARD_H)
        self._build()

    # ── builder ─────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(4)

        # Üst satır: durum noktası + unut butonu
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._dot = QFrame()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(
            f"background-color: {_C.TEXT_DIM}; border-radius: 4px;"
        )
        top_row.addWidget(self._dot)
        top_row.addStretch()

        self._btn_forget = QPushButton("×")
        self._btn_forget.setFixedSize(22, 22)
        self._btn_forget.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_forget.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {_C.TEXT_DIM}; border: none;
                border-radius: 11px; font-size: 14px; font-weight: 700;
            }}
            QPushButton:hover {{
                color: {_C.RED}; background-color: rgba(248,113,113,0.12);
            }}
        """)
        self._btn_forget.clicked.connect(self._on_forget_clicked)
        top_row.addWidget(self._btn_forget)
        root.addLayout(top_row)

        # Sahip adı (Kişi bilgisi)
        owner = (self.owner_name or "").strip()
        if not owner:
            owner = (self.owner_email or self.owner_phone or "").strip()
            
        self._owner = None
        if owner:
            self._owner = QLabel(compact_label(owner, 34))
            self._owner.setStyleSheet(
                f"color: {_C.ACCENT}; font-size: 14px; font-weight: 800;"
                f" background: transparent;"
            )
            root.addWidget(self._owner)
        
        # Cihaz adı / adres
        formatted = display_device_name(self.device_name, self.address, self.device_id)
        self._title = QLabel(compact_label(formatted, 28))
        self._title.setStyleSheet(
            f"color: {_C.TEXT}; font-size: 15px; font-weight: 800;"
            f" background: transparent;"
        )
        root.addWidget(self._title)

        address_text = format_address(self.address) if self.address else ""
        subtitle = address_text if address_text and address_text != formatted else "Eşleşmiş cihaz"
        self._lbl_address = QLabel(subtitle)
        self._lbl_address.setStyleSheet(
            f"color: {_C.TEXT_MUTED}; font-size: 12px; background: transparent;"
        )
        root.addWidget(self._lbl_address)

        self._lbl_status = QLabel("Çevrimdışı")
        self._lbl_status.setStyleSheet(
            f"color: {_C.TEXT_DIM}; font-size: 12px; background: transparent;"
        )
        root.addWidget(self._lbl_status)

        root.addStretch()
        self._apply_card_style()

    # ── public helpers ───────────────────────────────────────────────────────

    def display_name(self) -> str:
        return display_device_name(self.device_name, self.address, self.device_id)

    def connection_address(self) -> str | None:
        digits = address_digits(self.address)
        return format_address(digits) if digits else None

    def card_key(self) -> str:
        return str(self.device_id)

    def set_connect_callback(self, cb):
        self._connect_cb = cb

    def set_forget_callback(self, cb):
        self._forget_cb = cb

    # ── durum güncelleme ──────────────────────────────────────────────────────

    def set_online(self, online: bool):
        self._online = online
        if online:
            self._dot.setStyleSheet(
                f"background-color: {_C.GREEN}; border-radius: 4px;"
            )
            self._lbl_status.setText("Çevrimiçi")
            self._lbl_status.setStyleSheet(
                f"color: {_C.GREEN}; font-size: 10px;"
                f" font-weight: 600; background: transparent;"
            )
        else:
            self._dot.setStyleSheet(
                f"background-color: {_C.TEXT_DIM}; border-radius: 4px;"
            )
            self._lbl_status.setText("Çevrimdışı")
            self._lbl_status.setStyleSheet(
                f"color: {_C.TEXT_DIM}; font-size: 10px; background: transparent;"
            )
        self._apply_card_style()

    def is_online(self) -> bool:
        return self._online

    def set_connecting(self):
        self._lbl_status.setText("Bağlanıyor…")

    # ── qt events ─────────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._online and self._connect_cb:
            self._connect_cb(self.card_key())
        super().mousePressEvent(event)

    # ── private ──────────────────────────────────────────────────────────────

    def _apply_card_style(self):
        self.setStyleSheet(device_card_style(self._online))
        cursor = Qt.CursorShape.PointingHandCursor if self._online else Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)

    def _on_forget_clicked(self):
        if self._forget_cb:
            self._forget_cb(self.card_key())
