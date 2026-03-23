"""
Ana Pencere — Remote Phone Control
=====================================
Profesyonel koyu arayüz. DB'den eşleşmiş cihazlar yüklenir,
gerçek zamanlı online durumu signaling sunucusu üzerinden alınır.
"""

import json
import logging
import os
from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFrame, QStatusBar,
    QSplitter, QGroupBox, QGridLayout, QDialog, QScrollArea,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QThread
from PyQt6.QtGui import QPixmap

from desktop_app.config import AppMeta, Prefs, ServerDefaults, Network, Ui, Colors, AndroidKeyCodes
from desktop_app.ui.screen_widget import ScreenWidget
from desktop_app.network.ws_client import WsClient, load_paired_phone_id
from desktop_app.network.mjpeg_receiver import MjpegReceiver
from desktop_app.database.db_client import DbClient

logger = logging.getLogger(__name__)


# ── Buton renk stilleri ───────────────────────────────────────────────────────
def _btn_nav() -> str:
    return f"""
        QPushButton {{
            background-color: {Colors.BTN_NAV_BG}; color: {Colors.BTN_NAV_FG};
            border: 1px solid {Colors.BTN_NAV_BDR};
            border-radius: 4px; padding: 8px 4px; font-size: 11px; font-weight: 500;
        }}
        QPushButton:hover  {{ background-color: #253060; border-color: {Colors.ACCENT}; color: {Colors.TEXT}; }}
        QPushButton:pressed {{ background-color: {Colors.ACCENT_DIM}; }}
        QPushButton:disabled {{ background-color: {Colors.BG_INPUT}; color: {Colors.TEXT_OFF}; border-color: {Colors.BORDER}; }}
    """

def _btn_vol() -> str:
    return f"""
        QPushButton {{
            background-color: {Colors.BTN_VOL_BG}; color: {Colors.BTN_VOL_FG};
            border: 1px solid {Colors.BTN_VOL_BDR};
            border-radius: 4px; padding: 8px 4px; font-size: 11px; font-weight: 500;
        }}
        QPushButton:hover  {{ background-color: #253A25; border-color: {Colors.SUCCESS}; color: {Colors.TEXT}; }}
        QPushButton:pressed {{ background-color: #1A2A1A; }}
        QPushButton:disabled {{ background-color: {Colors.BG_INPUT}; color: {Colors.TEXT_OFF}; border-color: {Colors.BORDER}; }}
    """

def _btn_screen() -> str:
    return f"""
        QPushButton {{
            background-color: {Colors.BTN_SCR_BG}; color: {Colors.BTN_SCR_FG};
            border: 1px solid {Colors.BTN_SCR_BDR};
            border-radius: 4px; padding: 8px 4px; font-size: 11px; font-weight: 500;
        }}
        QPushButton:hover  {{ background-color: #351E3D; border-color: #9B59B6; color: {Colors.TEXT}; }}
        QPushButton:pressed {{ background-color: #1E1028; }}
        QPushButton:disabled {{ background-color: {Colors.BG_INPUT}; color: {Colors.TEXT_OFF}; border-color: {Colors.BORDER}; }}
    """

_GROUP_STYLES = {"nav": _btn_nav, "vol": _btn_vol, "screen": _btn_screen}


def _relative_time(dt: datetime | None) -> str:
    """Datetime → '3 dk önce' formatında string."""
    if dt is None:
        return "Hiç bağlanmadı"
    # timezone-aware yap
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = int((now - dt).total_seconds())
    if diff < 60:
        return "Az önce"
    if diff < 3600:
        return f"{diff // 60} dk önce"
    if diff < 86400:
        return f"{diff // 3600} sa önce"
    return f"{diff // 86400} gün önce"


# ─── Cihaz kartı widget'ı ─────────────────────────────────────────────────────
class DeviceCard(QFrame):
    """Tek bir eşleşmiş telefon için kart."""

    def __init__(self, device_id: str, last_seen: datetime | None, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self._online = False
        self._connect_cb = None
        self._build(device_id, last_seen)

    def _build(self, device_id: str, last_seen: datetime | None):
        c = Colors
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {c.BG_INPUT};
                border: 1px solid {c.BORDER};
                border-radius: 6px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)

        # Üst satır: ikon + isim + durum noktası
        top = QHBoxLayout()
        top.setSpacing(7)

        icon = QLabel("📱")
        icon.setStyleSheet("font-size: 16px; background: transparent;")
        icon.setFixedWidth(22)
        top.addWidget(icon)

        short_id = device_id[-10:] if len(device_id) > 10 else device_id
        name_lbl = QLabel(f"...{short_id}")
        name_lbl.setStyleSheet(
            f"color: {c.TEXT}; font-size: 12px; font-weight: 600;"
            f" background: transparent; font-family: 'Segoe UI', Arial, sans-serif;"
        )
        top.addWidget(name_lbl)
        top.addStretch()

        self._dot = QFrame()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(f"background-color: {c.TEXT_OFF}; border-radius: 4px;")
        top.addWidget(self._dot)

        lay.addLayout(top)

        # Alt satır: son görülme + bağlan butonu
        bot = QHBoxLayout()
        bot.setSpacing(6)

        self._lbl_time = QLabel(_relative_time(last_seen))
        self._lbl_time.setStyleSheet(
            f"color: {c.TEXT_MUTED}; font-size: 10px; background: transparent;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        bot.addWidget(self._lbl_time)
        bot.addStretch()

        self._btn_conn = QPushButton("Bağlan")
        self._btn_conn.setFixedSize(62, 24)
        self._btn_conn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_conn.setEnabled(False)
        self._apply_btn_style(False)
        self._btn_conn.clicked.connect(self._on_connect_clicked)
        bot.addWidget(self._btn_conn)

        lay.addLayout(bot)

    def _apply_btn_style(self, enabled: bool):
        c = Colors
        if enabled:
            self._btn_conn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c.ACCENT}; color: #FFF;
                    border: none; border-radius: 4px;
                    font-size: 10px; font-weight: 600;
                    font-family: 'Segoe UI', Arial, sans-serif;
                }}
                QPushButton:hover {{ background-color: {c.ACCENT_HOVER}; }}
            """)
        else:
            self._btn_conn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c.BG_SURFACE}; color: {c.TEXT_OFF};
                    border: 1px solid {c.BORDER}; border-radius: 4px;
                    font-size: 10px; font-weight: 600;
                    font-family: 'Segoe UI', Arial, sans-serif;
                }}
            """)

    def set_online(self, online: bool):
        self._online = online
        c = Colors
        if online:
            self._dot.setStyleSheet(f"background-color: {c.SUCCESS}; border-radius: 4px;")
            self._lbl_time.setText("🟢 Çevrimiçi")
            self._lbl_time.setStyleSheet(
                f"color: {c.SUCCESS}; font-size: 10px; background: transparent;"
                f" font-family: 'Segoe UI', Arial, sans-serif;"
            )
        else:
            self._dot.setStyleSheet(f"background-color: {c.TEXT_OFF}; border-radius: 4px;")
        self._btn_conn.setEnabled(online)
        self._apply_btn_style(online)

    def set_last_seen(self, dt: datetime | None):
        if not self._online:
            self._lbl_time.setText(_relative_time(dt))
            self._lbl_time.setStyleSheet(
                f"color: {Colors.TEXT_MUTED}; font-size: 10px; background: transparent;"
                f" font-family: 'Segoe UI', Arial, sans-serif;"
            )

    def set_connect_callback(self, cb):
        self._connect_cb = cb

    def _on_connect_clicked(self):
        if self._connect_cb:
            self._connect_cb(self.device_id)

    def set_connecting(self):
        self._btn_conn.setEnabled(False)
        self._btn_conn.setText("...")
        self._dot.setStyleSheet(
            f"background-color: {Colors.WARNING}; border-radius: 4px;"
        )


# ─── Ana Pencere ──────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    """Ana uygulama penceresi."""

    def __init__(self, db: DbClient):
        super().__init__()
        self.db = db
        self.setWindowTitle(AppMeta.WINDOW_TITLE)
        self.setMinimumSize(AppMeta.MIN_WIDTH, AppMeta.MIN_HEIGHT)
        self.resize(AppMeta.DEFAULT_WIDTH, AppMeta.DEFAULT_HEIGHT)

        self._ws_client     = WsClient()
        self._mjpeg         = MjpegReceiver()
        self._connected     = False
        self._rotation_step = 0
        self._paired_phone_id: str | None = None
        self._device_cards: dict[str, DeviceCard] = {}  # device_id → card

        # Prefs'ten user bilgilerini yükle
        self._user_id: int | None   = None
        self._username: str         = "Kullanıcı"
        self._load_user_prefs()

        self._setup_style()
        self._build_ui()
        self._connect_signals()

        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(Network.HEARTBEAT_INTERVAL_MS)
        self._heartbeat.timeout.connect(self._ws_client.send_heartbeat)

        # DB'den eşleşmiş cihazları yükle + auto-connect
        QTimer.singleShot(300, self._load_devices_from_db)

    def _load_user_prefs(self):
        try:
            if os.path.exists(Prefs.PATH):
                with open(Prefs.PATH) as f:
                    data = json.load(f)
                self._user_id = data.get(Prefs.KEY_USER_ID)
                self._username = data.get(Prefs.KEY_USERNAME, "Kullanıcı")
        except Exception:
            pass

    # ─── STYLE ────────────────────────────────────────────────────────────────

    def _setup_style(self):
        c = Colors
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {c.BG_APP}; }}
            QWidget      {{ background-color: transparent; color: {c.TEXT};
                           font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; }}
            QGroupBox {{
                background-color: {c.BG_CARD};
                border: 1px solid {c.BORDER}; border-radius: 5px;
                margin-top: 12px; padding: 14px 10px 10px 10px;
                font-size: 10px; font-weight: 700; letter-spacing: 1px;
                color: {c.TEXT_SUBTLE}; text-transform: uppercase;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 10px; padding: 2px 6px;
                background-color: {c.BG_CARD};
            }}
            QLineEdit {{
                background-color: {c.BG_INPUT}; border: 1px solid {c.BORDER_INPUT};
                border-radius: 4px; padding: 8px 12px;
                color: {c.TEXT}; font-size: 13px;
                selection-background-color: {c.ACCENT};
            }}
            QLineEdit:focus {{ border-color: {c.BORDER_FOCUS}; }}
            QPushButton {{ border: none; border-radius: 4px;
                          padding: 7px 12px; font-size: 12px; font-weight: 500; }}
            QPushButton#btn_connect {{
                background-color: {c.BTN_CONNECT_BG}; color: #FFFFFF;
            }}
            QPushButton#btn_connect:hover   {{ background-color: {c.BTN_CONNECT_HOV}; }}
            QPushButton#btn_connect:pressed {{ background-color: {c.BTN_CONNECT_PRESS}; }}
            QPushButton#btn_connect:disabled {{
                background-color: #1E3A2A; color: #3A6A4A; border: 1px solid #1E3A2A;
            }}
            QPushButton#btn_disconnect {{
                background-color: {c.BTN_DISCONNECT_BG};
                color: {c.BTN_DISCONNECT_FG};
                border: 1px solid {c.BTN_DISCONNECT_BDR};
            }}
            QPushButton#btn_disconnect:hover   {{ background-color: {c.BTN_DISCONNECT_HOV}; }}
            QPushButton#btn_disconnect:disabled {{
                background-color: {c.BG_INPUT}; color: {c.TEXT_OFF}; border: 1px solid {c.BORDER};
            }}
            QPushButton#btn_rotate {{
                background-color: {c.BTN_NAV_BG}; color: {c.BTN_NAV_FG};
                border: 1px solid {c.BTN_NAV_BDR};
            }}
            QPushButton#btn_rotate:hover   {{ background-color: #253060; color: {c.TEXT}; }}
            QPushButton#btn_rotate:disabled {{
                background-color: {c.BG_INPUT}; color: {c.TEXT_OFF}; border-color: {c.BORDER};
            }}
            QStatusBar {{
                background-color: {c.BG_APP}; color: {c.TEXT_MUTED};
                border-top: 1px solid {c.BORDER}; font-size: 11px; padding: 0 8px;
            }}
            QSplitter::handle {{ background-color: {c.BORDER}; width: 1px; }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: {c.BG_APP}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {c.BORDER}; border-radius: 3px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    # ─── UI BUILD ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background-color: {Colors.BG_APP};")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)
        splitter.setHandleWidth(1)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_screen_area())
        splitter.setSizes([Ui.SPLITTER_LEFT_SIZE, Ui.SPLITTER_RIGHT_SIZE])
        root.addWidget(splitter, stretch=1)

        self._status_bar = QStatusBar()
        self._status_bar.showMessage(Ui.MSG_WAITING)
        self.setStatusBar(self._status_bar)

    def _build_header(self) -> QWidget:
        c = Colors
        header = QFrame()
        header.setFixedHeight(Ui.HEADER_HEIGHT)
        header.setStyleSheet(f"""
            QFrame {{
                background-color: {c.BG_SURFACE};
                border-bottom: 1px solid {c.BORDER};
            }}
        """)
        lay = QHBoxLayout(header)
        lay.setContentsMargins(16, 0, 16, 0)

        title = QLabel("Remote Phone Control")
        title.setStyleSheet(
            f"color: {c.TEXT}; font-size: 14px; font-weight: 600;"
            f" letter-spacing: -0.2px; background: transparent;"
        )
        lay.addWidget(title)

        ver = QLabel(f"  v{AppMeta.VERSION}")
        ver.setStyleSheet(f"color: {c.TEXT_OFF}; font-size: 11px; background: transparent;")
        lay.addWidget(ver)
        lay.addStretch()

        # Kullanıcı adı
        user_lbl = QLabel(f"👤 {self._username}")
        user_lbl.setStyleSheet(f"color: {c.TEXT_MUTED}; font-size: 11px; background: transparent;")
        lay.addWidget(user_lbl)
        lay.addSpacing(12)

        # Bağlantı durumu
        self._status_indicator = QFrame()
        self._status_indicator.setFixedSize(8, 8)
        self._status_indicator.setStyleSheet(
            f"background-color: {c.TEXT_OFF}; border-radius: 4px;"
        )
        lay.addWidget(self._status_indicator)
        lay.addSpacing(6)

        self._lbl_status_text = QLabel("Bağlı Değil")
        self._lbl_status_text.setStyleSheet(
            f"color: {c.TEXT_OFF}; font-size: 12px; background: transparent;"
        )
        lay.addWidget(self._lbl_status_text)
        lay.addSpacing(16)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedHeight(20)
        sep.setStyleSheet(f"background-color: {c.BORDER}; max-width: 1px;")
        lay.addWidget(sep)
        lay.addSpacing(12)

        self._btn_logout = QPushButton("Çıkış")
        self._btn_logout.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {c.TEXT_MUTED};
                border: 1px solid {c.BORDER}; border-radius: 4px;
                padding: 4px 12px; font-size: 11px;
            }}
            QPushButton:hover {{
                color: {c.BTN_DANGER_FG}; border-color: {c.BTN_DANGER_BDR};
                background-color: {c.BTN_DANGER_BG};
            }}
        """)
        self._btn_logout.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_logout.clicked.connect(self._on_logout)
        lay.addWidget(self._btn_logout)

        self._lbl_status_dot = QLabel()
        self._lbl_status_dot.hide()
        return header

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(Ui.LEFT_PANEL_WIDTH)
        panel.setStyleSheet(
            f"background-color: {Colors.BG_SURFACE};"
            f" border-right: 1px solid {Colors.BORDER};"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(10)

        # ── Eşleştirilmiş Cihazlar ────────────────────────────────────
        lay.addWidget(self._build_devices_group())

        # ── Yeni Eşleşme ─────────────────────────────────────────────
        grp_conn = QGroupBox("Yeni Eşleşme")
        cl = QVBoxLayout(grp_conn)
        cl.setSpacing(7)

        cl.addWidget(self._lbl(f"6 Haneli Kod"))
        self._inp_code = QLineEdit()
        self._inp_code.setPlaceholderText(Ui.PLACEHOLDER_CODE)
        self._inp_code.setMaxLength(ServerDefaults.CODE_LENGTH)
        self._inp_code.setFixedHeight(36)
        self._inp_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inp_code.setStyleSheet(f"""
            QLineEdit {{
                background-color: {Colors.BG_INPUT};
                border: 1px solid {Colors.BORDER_INPUT};
                border-radius: 4px; padding: 0 12px;
                color: {Colors.TEXT}; font-size: 15px;
                font-family: 'Segoe UI', Arial, sans-serif;
                letter-spacing: 2px;
                selection-background-color: {Colors.ACCENT};
            }}
            QLineEdit:focus {{ border-color: {Colors.BORDER_FOCUS}; }}
        """)
        cl.addWidget(self._inp_code)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._btn_connect = QPushButton("Eşleş ve Bağlan")
        self._btn_connect.setObjectName("btn_connect")
        self._btn_connect.setFixedHeight(32)
        self._btn_disconnect = QPushButton("Bağlantıyı Kes")
        self._btn_disconnect.setObjectName("btn_disconnect")
        self._btn_disconnect.setFixedHeight(32)
        self._btn_disconnect.setEnabled(False)
        btn_row.addWidget(self._btn_connect)
        btn_row.addWidget(self._btn_disconnect)
        cl.addLayout(btn_row)
        lay.addWidget(grp_conn)

        # ── Ekran Kontrolü ───────────────────────────────────────────
        grp_screen = QGroupBox("Ekran")
        sl = QVBoxLayout(grp_screen)
        self._btn_rotate = QPushButton("Yatay Moda Geç  ↻")
        self._btn_rotate.setObjectName("btn_rotate")
        self._btn_rotate.setFixedHeight(32)
        self._btn_rotate.setEnabled(False)
        self._btn_rotate.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_rotate.clicked.connect(self._on_rotate_toggle)
        sl.addWidget(self._btn_rotate)
        lay.addWidget(grp_screen)

        # ── Tuş Kontrolleri ─────────────────────────────────────────
        grp_keys = QGroupBox("Tuş Kontrolleri")
        kl = QGridLayout(grp_keys)
        kl.setSpacing(5)
        key_codes = AndroidKeyCodes.as_mapping()
        self._key_buttons = []
        for label, group, row, col, key_id in AndroidKeyCodes.button_specs():
            btn = QPushButton(label)
            btn.setStyleSheet(_GROUP_STYLES[group]())
            btn.clicked.connect(lambda _, k=key_codes[key_id]: self._ws_client.send_key_event(k))
            btn.setEnabled(False)
            self._key_buttons.append(btn)
            kl.addWidget(btn, row, col)
        lay.addWidget(grp_keys)

        lay.addStretch()
        return panel

    def _build_devices_group(self) -> QGroupBox:
        """DB'den yüklenen eşleşmiş cihaz kartlarının bulunduğu grup."""
        grp = QGroupBox("Eşleştirilmiş Cihazlar")
        outer = QVBoxLayout(grp)
        outer.setSpacing(6)
        outer.setContentsMargins(6, 8, 6, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(140)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background: transparent;")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_container)
        outer.addWidget(scroll)

        self._lbl_no_devices = QLabel("Kayıtlı cihaz yok.\nYeni eşleşme için aşağıya bakın.")
        self._lbl_no_devices.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_no_devices.setWordWrap(True)
        self._lbl_no_devices.setStyleSheet(
            f"color: {Colors.TEXT_MUTED}; font-size: 11px; background: transparent;"
            f" padding: 8px 0;"
        )
        outer.addWidget(self._lbl_no_devices)
        self._lbl_no_devices.hide()

        return grp

    def _build_screen_area(self) -> QWidget:
        c = Colors
        container = QWidget()
        container.setStyleSheet(f"background-color: {c.BG_APP};")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        top_bar = QWidget()
        top_bar.setFixedHeight(32)
        top_bar.setStyleSheet(
            f"background-color: {c.BG_SURFACE}; border-bottom: 1px solid {c.BORDER};"
        )
        bar_lay = QHBoxLayout(top_bar)
        bar_lay.setContentsMargins(16, 0, 16, 0)

        screen_lbl = QLabel("EKRAN GÖRÜNTÜSÜ")
        screen_lbl.setStyleSheet(
            f"color: {c.TEXT_SUBTLE}; font-size: 10px; font-weight: 700;"
            f" letter-spacing: 1px; background: transparent;"
        )
        bar_lay.addWidget(screen_lbl)
        bar_lay.addStretch()

        self._lbl_coords = QLabel("")
        self._lbl_coords.setStyleSheet(
            f"color: {c.TEXT_OFF}; font-size: 10px;"
            f" font-family: 'Consolas', monospace; background: transparent;"
        )
        bar_lay.addWidget(self._lbl_coords)
        lay.addWidget(top_bar)

        self._screen = ScreenWidget()
        lay.addWidget(self._screen, stretch=1)
        return container

    # ─── SIGNALS ──────────────────────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        self._ws_client.connected.connect(self._on_ws_connected)
        self._ws_client.disconnected.connect(self._on_ws_disconnected)
        self._ws_client.paired.connect(self._on_paired)
        self._ws_client.auto_paired.connect(self._on_auto_paired)
        self._ws_client.peer_disconnected.connect(self._on_peer_disconnected)
        self._ws_client.error_occurred.connect(self._on_error)
        self._ws_client.frame_received.connect(self._on_frame_received)
        self._mjpeg.frame_ready.connect(self._screen.set_frame)
        self._mjpeg.error_occurred.connect(self._on_mjpeg_error)
        self._mjpeg.stream_stopped.connect(self._on_stream_stopped)
        self._screen.touch_event.connect(self._on_touch)
        self._screen.swipe_event.connect(self._on_swipe)

    # ─── SLOTS ────────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _load_devices_from_db(self):
        """DB'den eşleşmiş cihazları arka planda yükler."""
        if not self._user_id:
            self._try_auto_connect()
            return

        # DB'ye önce kendi cihazımızı kaydet
        self.db.upsert_device(self._user_id, self._ws_client.device_id, "pc")

        # Paired cihazları yükle
        devices = self.db.get_paired_devices(self._user_id, self._ws_client.device_id)
        self._populate_device_cards(devices)

        # Kayıtlı telefon varsa auto-connect dene
        self._try_auto_connect()

    def _populate_device_cards(self, devices: list[dict]):
        """Kart listesini DB sonuçlarıyla doldurur."""
        # Eski kartları temizle
        for card in self._device_cards.values():
            self._cards_layout.removeWidget(card)
            card.deleteLater()
        self._device_cards.clear()

        if not devices:
            self._lbl_no_devices.show()
            return

        self._lbl_no_devices.hide()
        # Stretch'ten önce ekle
        stretch_item = self._cards_layout.itemAt(self._cards_layout.count() - 1)
        for dev in devices:
            card = DeviceCard(dev["device_id"], dev.get("last_seen"))
            card.set_connect_callback(self._on_card_connect)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._device_cards[dev["device_id"]] = card

    def _on_card_connect(self, device_id: str):
        """Kullanıcı kart üzerindeki 'Bağlan' butonuna bastı."""
        self._paired_phone_id = device_id
        card = self._device_cards.get(device_id)
        if card:
            card.set_connecting()
        self._set_status(f"Eşleşmiş telefona bağlanılıyor...")
        self._ws_client.connect_with_device_id(ServerDefaults.DEFAULT_URL)

    @pyqtSlot()
    def _try_auto_connect(self):
        """Kayıtlı telefon varsa sunucuya bağlan ve device_hello gönder."""
        paired_id = load_paired_phone_id()
        if paired_id:
            self._paired_phone_id = paired_id
            self._set_status("Kayıtlı telefon aranıyor...")
            self._ws_client.connect_with_device_id(ServerDefaults.DEFAULT_URL)
        else:
            self._set_status(Ui.MSG_WAITING)

    @pyqtSlot()
    def _on_connect(self):
        code = self._inp_code.text().strip()
        if not code:
            self._set_status("Oturum kodu girilmedi.", error=True)
            return
        if len(code) != ServerDefaults.CODE_LENGTH or not code.isdigit():
            self._set_status(Ui.MSG_CODE_MUST_BE_6_DIGITS, error=True)
            return
        self._btn_connect.setEnabled(False)
        self._set_status(Ui.MSG_CONNECTING)
        self._ws_client.connect_to_server(ServerDefaults.DEFAULT_URL, code)

    @pyqtSlot()
    def _on_disconnect(self):
        self._mjpeg.stop()
        self._ws_client.disconnect()
        self._set_connected(False)
        self._screen.clear_frame()
        # Kart durumlarını güncelle
        for card in self._device_cards.values():
            card.set_online(False)

    @pyqtSlot()
    def _on_logout(self):
        self._mjpeg.stop()
        self._ws_client.disconnect()
        self.db.close()
        try:
            prefs = {}
            if os.path.exists(Prefs.PATH):
                with open(Prefs.PATH) as f:
                    prefs = json.load(f)
            prefs[Prefs.KEY_LOGGED_IN] = False
            with open(Prefs.PATH, "w") as f:
                json.dump(prefs, f)
        except Exception:
            pass
        from desktop_app.ui.login_window import LoginWindow
        new_db = DbClient()
        if LoginWindow(new_db).exec() == QDialog.DialogCode.Accepted:
            self._load_user_prefs()
            self._set_status(Ui.MSG_WAITING)
            QTimer.singleShot(300, self._load_devices_from_db)
        else:
            import sys; sys.exit(0)

    @pyqtSlot()
    def _on_ws_connected(self):
        self._set_status(Ui.MSG_SERVER_CONNECTED)
        self._btn_disconnect.setEnabled(True)

    @pyqtSlot(str)
    def _on_ws_disconnected(self, reason: str):
        self._set_connected(False)
        for card in self._device_cards.values():
            card.set_online(False)
        if "10060" in reason or "timed out" in reason.lower():
            self._set_status(Ui.MSG_DISCONNECT_TIMEOUT, error=True)
        else:
            self._set_status(f"Bağlantı kesildi  —  {reason}", error=True)
        self._btn_connect.setEnabled(True)
        self._screen.clear_frame()

    @pyqtSlot(str)
    def _on_paired(self, stream_url: str):
        """İlk eşleşme (6 haneli kod)."""
        self._set_connected(True)
        # pair_confirm gönder ve DB'ye kaydet
        # Phone device_id henüz bilinmiyor; server auto_paired'dan alınacak
        self._set_status("Eşleşildi! Akış bekleniyor...")
        if stream_url and stream_url.startswith("http"):
            if "0.0.0.0" not in stream_url and "10.0.2." not in stream_url:
                try:
                    self._mjpeg.start(stream_url)
                    self._set_status("Bağlandı  —  Video akışı aktif")
                    return
                except Exception:
                    pass
        self._set_status(Ui.MSG_PAIRED_WS)

    @pyqtSlot(str)
    def _on_auto_paired(self, partner_device_id: str):
        """Kayıtlı eşleşme — telefon çevrimiçiydi, otomatik bağlandı."""
        self._paired_phone_id = partner_device_id
        self._set_connected(True)
        self._set_status(f"Otomatik bağlandı  —  Ekran akışı bekleniyor")

        # Kart güncelle
        card = self._device_cards.get(partner_device_id)
        if card:
            card.set_online(True)

        # DB'ye pair kaydet ve last_seen güncelle
        if self._user_id:
            self.db.save_pairing(self._user_id, partner_device_id, self._ws_client.device_id)
            self.db.upsert_device(self._user_id, partner_device_id, "phone")

        # Prefs'e partner kaydet
        self._ws_client.send_pair_confirm(partner_device_id)

        # Kart yoksa listeye ekle
        if partner_device_id not in self._device_cards:
            if self._user_id:
                devices = self.db.get_paired_devices(self._user_id, self._ws_client.device_id)
                self._populate_device_cards(devices)

    @pyqtSlot()
    def _on_peer_disconnected(self):
        self._mjpeg.stop()
        self._screen.clear_frame()
        self._set_connected(False)
        if self._paired_phone_id and self._paired_phone_id in self._device_cards:
            self._device_cards[self._paired_phone_id].set_online(False)
        self._set_status(Ui.MSG_PEER_DISCONNECTED, error=True)

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        self._set_status(f"Hata: {msg}", error=True)

    @pyqtSlot(QPixmap)
    def _on_frame_received(self, pixmap: QPixmap):
        self._screen.set_frame(pixmap)

    @pyqtSlot(str)
    def _on_mjpeg_error(self, _: str):
        if self._connected:
            self._set_status(Ui.MSG_PAIRED_WS)

    @pyqtSlot()
    def _on_stream_stopped(self):
        if self._connected:
            self._set_status(Ui.MSG_PAIRED_WS)
        else:
            self._screen.clear_frame()
            self._set_status(Ui.MSG_STREAM_STOPPED, error=True)

    @pyqtSlot()
    def _on_rotate_toggle(self):
        self._rotation_step = (self._rotation_step + 1) % 4
        deg = self._rotation_step * 90
        self._screen.set_rotation(deg)
        labels = {0: "Yatay Moda Geç  ↻", 90: "180° Döndür  ↻",
                  180: "270° Döndür  ↻", 270: "Dikey Moda Geç  ↻"}
        self._btn_rotate.setText(labels[deg])
        self._ws_client.send_rotate_screen(deg in (90, 270))
        self._set_status(f"Görüntü {deg}° döndürüldü")

    @pyqtSlot(float, float)
    def _on_touch(self, x: float, y: float):
        self._ws_client.send_touch(x, y)
        self._lbl_coords.setText(f"x={x:.3f}  y={y:.3f}")

    @pyqtSlot(float, float, float, float)
    def _on_swipe(self, x1, y1, x2, y2):
        self._ws_client.send_swipe(x1, y1, x2, y2)
        self._lbl_coords.setText(f"({x1:.2f},{y1:.2f}) → ({x2:.2f},{y2:.2f})")

    # ─── HELPERS ──────────────────────────────────────────────────────────────

    @staticmethod
    def _lbl(text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {Colors.TEXT_MUTED}; font-size: 11px; font-weight: 600;"
            f" background: transparent;"
        )
        return l

    def _set_connected(self, connected: bool):
        self._connected = connected
        color = Colors.SUCCESS if connected else Colors.TEXT_OFF
        self._status_indicator.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
        self._lbl_status_text.setStyleSheet(
            f"color: {color}; font-size: 12px; background: transparent;"
        )
        self._lbl_status_text.setText("Bağlandı" if connected else "Bağlı Değil")
        for btn in self._key_buttons:
            btn.setEnabled(connected)
        self._btn_rotate.setEnabled(connected)
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)
        if connected:
            self._heartbeat.start()
        else:
            self._heartbeat.stop()

    def _set_status(self, msg: str, error: bool = False):
        color = Colors.ERROR if error else Colors.TEXT_MUTED
        self._status_bar.setStyleSheet(f"color: {color};")
        self._status_bar.showMessage(msg)

    def closeEvent(self, event):
        self._mjpeg.stop()
        self._ws_client.disconnect()
        self.db.close()
        super().closeEvent(event)
