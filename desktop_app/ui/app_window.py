"""
AnyDesk-inspired desktop shell.
Layout (top→bottom):
  1. Title bar  (app name · session tab · account)
  2. Connect hero  (large remote address input)
  3. Recent Sessions tab strip
  4. Recent Sessions device card grid
When a connection is active, a second stacked page shows live control.
"""

import logging
from datetime import datetime, timezone

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from desktop_app.config import AppMeta, ServerDefaults, Network, Ui, Colors, AndroidKeyCodes
from desktop_app.config.prefs_store import (
    clear_logged_in,
    clear_paired_phone_id,
    load_paired_phone_id,
    read_prefs,
)
from desktop_app.database.db_client import DbClient
from desktop_app.network.mjpeg_receiver import MjpegReceiver
from desktop_app.network.ws_client import WsClient
from desktop_app.ui.screen_widget import ScreenWidget
from desktop_app.ui.theme import (
    card_style,
    filled_button_style,
    line_edit_style,
    outline_button_style,
    text_style,
)

logger = logging.getLogger(__name__)

# ── Renkler (AnyDesk-inspired dark palette) ──────────────────────────────────
_CLR_TITLEBAR = "#1A1A1A"
_CLR_BODY = "#222222"
_CLR_CARD = "#2C2C2C"
_CLR_CARD_BORDER = "#3A3A3A"
_CLR_INPUT_BG = "#2E2E2E"
_CLR_INPUT_BORDER = "#444444"
_CLR_INPUT_FOCUS = "#E06040"
_CLR_TAB_ACTIVE = "#E06040"
_CLR_TAB_INACTIVE = "#888888"
_CLR_TEXT = "#EEEEEE"
_CLR_TEXT_MUTED = "#999999"
_CLR_TEXT_DIM = "#666666"
_CLR_ACCENT = "#E06040"
_CLR_ACCENT_HOVER = "#D05535"
_CLR_GREEN_DOT = "#55CC66"
_CLR_RED_DOT = "#FF4444"


def _format_address(addr: str) -> str:
    """'000000000001' → '000 000 000 001' gibi 3'erli boşluklu gösterim."""
    digits = addr.replace(" ", "")
    return " ".join(digits[i:i + 3] for i in range(0, len(digits), 3))


def _relative_time(dt: datetime | None) -> str:
    if dt is None:
        return "Hic baglanmadi"
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = int((now - dt).total_seconds())
    if diff < 60:
        return "Az once"
    if diff < 3600:
        return f"{diff // 60} dk once"
    if diff < 86400:
        return f"{diff // 3600} sa once"
    return f"{diff // 86400} gun once"


# ─────────────────────────────────────────────────────────────────────────────
# DeviceCard — Recent Sessions grid item
# ─────────────────────────────────────────────────────────────────────────────
class DeviceCard(QFrame):
    """AnyDesk recent session card: dark tile with device address/id, status dot, and actions."""

    def __init__(self, device_id: str, last_seen: datetime | None, address: str | None = None, parent=None):
        super().__init__(parent)
        self.device_id = device_id
        self.address = address
        self._online = False
        self._connect_cb = None
        self._forget_cb = None
        self.setFixedSize(200, 120)
        self._build(device_id, last_seen, address)

    def _build(self, device_id: str, last_seen: datetime | None, address: str | None):
        self.setStyleSheet(f"""
            DeviceCard {{
                background-color: {_CLR_CARD};
                border: 1px solid {_CLR_CARD_BORDER};
                border-radius: 6px;
            }}
            DeviceCard:hover {{
                border-color: {_CLR_ACCENT};
            }}
        """)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        self._dot = QFrame()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(f"background-color: {_CLR_RED_DOT}; border-radius: 4px;")

        top_row = QHBoxLayout()
        top_row.setSpacing(0)
        top_row.addWidget(self._dot)
        top_row.addStretch()

        self._btn_menu = QPushButton("⋮")
        self._btn_menu.setFixedSize(22, 22)
        self._btn_menu.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {_CLR_TEXT_MUTED}; border: none;
                font-size: 14px; font-weight: bold;
            }}
            QPushButton:hover {{ color: {_CLR_TEXT}; }}
        """)
        self._btn_menu.clicked.connect(self._on_menu_clicked)
        top_row.addWidget(self._btn_menu)
        root.addLayout(top_row)

        root.addStretch()

        display_id = address or device_id
        if address:
            formatted = _format_address(address)
        else:
            formatted = "..." + device_id[-8:] if len(device_id) > 8 else device_id

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)
        icon_lbl = QLabel("🖥")
        icon_lbl.setStyleSheet(f"color: {_CLR_TEXT_MUTED}; font-size: 12px;")
        bottom_row.addWidget(icon_lbl)

        self._title = QLabel(formatted)
        self._title.setStyleSheet(f"color: {_CLR_TEXT}; font-size: 12px; font-weight: 500;")
        bottom_row.addWidget(self._title)
        bottom_row.addStretch()
        root.addLayout(bottom_row)

        self._lbl_time = QLabel(_relative_time(last_seen))
        self._lbl_time.setStyleSheet(f"color: {_CLR_TEXT_DIM}; font-size: 10px;")
        self._lbl_time.setContentsMargins(20, 0, 0, 0)
        root.addWidget(self._lbl_time)

    def set_connect_callback(self, cb):
        self._connect_cb = cb

    def set_forget_callback(self, cb):
        self._forget_cb = cb

    def set_online(self, online: bool):
        self._online = online
        if online:
            self._dot.setStyleSheet(f"background-color: {_CLR_GREEN_DOT}; border-radius: 4px;")
            self._lbl_time.setText("Cevrimici")
            self._lbl_time.setStyleSheet(f"color: {_CLR_GREEN_DOT}; font-size: 10px;")
        else:
            self._dot.setStyleSheet(f"background-color: {_CLR_RED_DOT}; border-radius: 4px;")
            self._lbl_time.setStyleSheet(f"color: {_CLR_TEXT_DIM}; font-size: 10px;")

    def set_last_seen(self, dt: datetime | None):
        if not self._online:
            self._lbl_time.setText(_relative_time(dt))

    def set_connecting(self):
        self._lbl_time.setText("Baglaniyor...")

    def reset_connect_label(self):
        pass

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._online and self._connect_cb:
            self._connect_cb(self.device_id)
        super().mousePressEvent(event)

    def _on_menu_clicked(self):
        if self._online and self._connect_cb:
            self._connect_cb(self.device_id)
        elif not self._online and self._forget_cb:
            self._forget_cb(self.device_id)

    def _on_connect_clicked(self):
        if self._connect_cb:
            self._connect_cb(self.device_id)

    def _on_forget_clicked(self):
        if self._forget_cb:
            self._forget_cb(self.device_id)


# ─────────────────────────────────────────────────────────────────────────────
# MainWindow
# ─────────────────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, db: DbClient):
        super().__init__()
        self.db = db
        self._ws_client = WsClient()
        self._mjpeg = MjpegReceiver()
        self._connected = False
        self._rotation_step = 0
        self._paired_phone_id: str | None = None
        self._device_cards: dict[str, DeviceCard] = {}
        self._online_paired_devices: set[str] = set()
        self._logging_out = False
        self._user_id: int | None = None
        self._username = "Kullanici"
        self._user_address = ""
        self._current_page = 0
        self._session_tab_btn: QPushButton | None = None

        self.setWindowTitle(AppMeta.WINDOW_TITLE)
        self.setMinimumSize(960, 640)
        self.resize(1060, 720)
        self._load_user_prefs()
        self._apply_global_style()
        self._build_ui()
        self._connect_signals()

        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(Network.HEARTBEAT_INTERVAL_MS)
        self._heartbeat.timeout.connect(self._ws_client.send_heartbeat)

        QTimer.singleShot(250, self._load_devices_from_db)

    # ── prefs ────────────────────────────────────────────────────────────────
    def _load_user_prefs(self):
        prefs = read_prefs()
        self._user_id = prefs.get("user_id")
        self._username = prefs.get("username", "Kullanici")
        if self._user_id:
            self._user_address = self.db.get_user_address(self._user_id) or ""

    # ── global style ─────────────────────────────────────────────────────────
    def _apply_global_style(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {_CLR_BODY}; }}
            QWidget {{ background: transparent; color: {_CLR_TEXT}; font-family: 'Segoe UI', Arial, sans-serif; }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{
                background: {_CLR_BODY}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #555555; border-radius: 3px; min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    # ── build UI ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_home_page())
        self._pages.addWidget(self._build_remote_page())
        root.addWidget(self._pages, stretch=1)

        self._status_bar = QStatusBar()
        self._status_bar.showMessage(Ui.MSG_WAITING)
        self._status_bar.setStyleSheet(
            f"QStatusBar {{ background-color: {_CLR_TITLEBAR}; border-top: 1px solid #333; color: {_CLR_TEXT_MUTED}; font-size: 11px; }}"
        )
        self.setStatusBar(self._status_bar)

    # ── 1. Title Bar ─────────────────────────────────────────────────────────
    def _build_title_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(38)
        bar.setStyleSheet(f"background-color: {_CLR_TITLEBAR}; border-bottom: 1px solid #333;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 0, 14, 0)
        layout.setSpacing(0)

        logo_dot = QFrame()
        logo_dot.setFixedSize(14, 14)
        logo_dot.setStyleSheet(f"background-color: {_CLR_ACCENT}; border-radius: 7px;")
        layout.addWidget(logo_dot)
        layout.addSpacing(8)

        app_name = QLabel("Remote Control")
        app_name.setStyleSheet(f"color: {_CLR_TEXT}; font-size: 13px; font-weight: 700;")
        layout.addWidget(app_name)
        layout.addSpacing(18)

        self._session_tab_btn = QPushButton("  Aktif Oturum")
        self._session_tab_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._session_tab_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {_CLR_TEXT_MUTED}; border: none;
                font-size: 12px; padding: 4px 10px;
            }}
            QPushButton:hover {{ color: {_CLR_TEXT}; }}
        """)
        self._session_tab_btn.clicked.connect(lambda: self._switch_page(1))
        self._session_tab_btn.hide()
        layout.addWidget(self._session_tab_btn)

        layout.addStretch()

        self._header_status_dot = QFrame()
        self._header_status_dot.setFixedSize(8, 8)
        self._header_status_dot.setStyleSheet(f"background-color: {_CLR_GREEN_DOT}; border-radius: 4px;")
        layout.addWidget(self._header_status_dot)
        layout.addSpacing(6)

        self._header_user_label = QLabel(self._username)
        self._header_user_label.setStyleSheet(f"color: {_CLR_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(self._header_user_label)
        layout.addSpacing(14)

        logout_btn = QPushButton("Cikis")
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.setFixedHeight(24)
        logout_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {_CLR_TEXT_DIM}; border: 1px solid #444;
                border-radius: 4px; font-size: 11px; padding: 2px 10px;
            }}
            QPushButton:hover {{ color: {_CLR_TEXT}; border-color: #666; }}
        """)
        logout_btn.clicked.connect(self._on_logout)
        layout.addWidget(logout_btn)
        return bar

    # ── 2. Home Page ────────────────────────────────────────────────────────
    def _build_home_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background-color: {_CLR_BODY};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_connect_hero())
        layout.addWidget(self._build_tab_strip())
        layout.addWidget(self._build_recent_sessions_section(), stretch=1)
        return page

    def _build_connect_hero(self) -> QWidget:
        section = QFrame()
        section.setStyleSheet(f"background-color: {_CLR_BODY};")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(60, 40, 60, 28)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl_title = QLabel("Uzak Cihaza Baglan")
        lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_title.setStyleSheet(f"color: {_CLR_TEXT_MUTED}; font-size: 14px;")
        layout.addWidget(lbl_title)

        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        input_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        dot = QFrame()
        dot.setFixedSize(12, 12)
        dot.setStyleSheet(f"background-color: {_CLR_GREEN_DOT}; border-radius: 6px;")
        input_row.addWidget(dot)

        self._inp_code = QLineEdit()
        self._inp_code.setPlaceholderText("12 haneli sabit adresi girin")
        self._inp_code.setFixedHeight(50)
        self._inp_code.setMinimumWidth(420)
        self._inp_code.setMaximumWidth(560)
        font = QFont("Segoe UI", 20)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0)
        self._inp_code.setFont(font)
        self._inp_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inp_code.setStyleSheet(f"""
            QLineEdit {{
                background-color: {_CLR_INPUT_BG}; border: 1px solid {_CLR_INPUT_BORDER};
                border-radius: 6px; padding: 0 18px; color: {_CLR_TEXT};
            }}
            QLineEdit:focus {{ border-color: {_CLR_INPUT_FOCUS}; }}
        """)
        self._inp_code.returnPressed.connect(self._on_connect)
        input_row.addWidget(self._inp_code)

        self._btn_connect = QPushButton("→")
        self._btn_connect.setFixedSize(50, 50)
        self._btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_connect.setStyleSheet(f"""
            QPushButton {{
                background-color: {_CLR_ACCENT}; color: white; border: none;
                border-radius: 6px; font-size: 22px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {_CLR_ACCENT_HOVER}; }}
            QPushButton:disabled {{ background-color: #555; color: #888; }}
        """)
        input_row.addWidget(self._btn_connect)
        layout.addLayout(input_row)

        status_row = QHBoxLayout()
        status_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_row.setSpacing(8)

        self._addr_status_dot = QFrame()
        self._addr_status_dot.setFixedSize(8, 8)
        self._addr_status_dot.setStyleSheet(f"background-color: {_CLR_GREEN_DOT}; border-radius: 4px;")
        status_row.addWidget(self._addr_status_dot)

        self._addr_status_label = QLabel("Hazir")
        self._addr_status_label.setStyleSheet(f"color: {_CLR_TEXT_MUTED}; font-size: 11px;")
        status_row.addWidget(self._addr_status_label)
        layout.addLayout(status_row)

        return section

    def _build_tab_strip(self) -> QWidget:
        strip = QFrame()
        strip.setFixedHeight(32)
        strip.setStyleSheet(f"background-color: {_CLR_BODY}; border-bottom: 1px solid #333;")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(20, 0, 20, 0)
        layout.setSpacing(20)

        tab_recent = QLabel("Recent Sessions")
        tab_recent.setStyleSheet(f"color: {_CLR_TAB_ACTIVE}; font-size: 12px; font-weight: 600; border-bottom: 2px solid {_CLR_TAB_ACTIVE}; padding-bottom: 4px;")
        layout.addWidget(tab_recent)

        layout.addStretch()

        self._lbl_device_count = QLabel("")
        self._lbl_device_count.setStyleSheet(f"color: {_CLR_TEXT_DIM}; font-size: 11px;")
        layout.addWidget(self._lbl_device_count)
        return strip

    def _build_recent_sessions_section(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background-color: {_CLR_BODY};")

        container = QWidget()
        container.setStyleSheet(f"background-color: {_CLR_BODY};")

        inner = QVBoxLayout(container)
        inner.setContentsMargins(20, 14, 20, 20)
        inner.setSpacing(10)

        section_header = QHBoxLayout()
        section_icon = QLabel("🖥  Recent Sessions")
        section_icon.setStyleSheet(f"color: {_CLR_TEXT_DIM}; font-size: 11px; font-weight: 600;")
        section_header.addWidget(section_icon)
        section_header.addStretch()
        inner.addLayout(section_header)

        self._recent_cards_container = QWidget()
        self._recent_cards_container.setStyleSheet("background: transparent;")
        self._recent_devices_layout = QGridLayout(self._recent_cards_container)
        self._recent_devices_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_devices_layout.setHorizontalSpacing(14)
        self._recent_devices_layout.setVerticalSpacing(14)
        self._recent_devices_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        inner.addWidget(self._recent_cards_container)

        self._lbl_no_devices = QLabel("Henuz eslesmis cihaz yok.\nTelefondaki 12 haneli sabit adresi girerek baglanti kurun.")
        self._lbl_no_devices.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_no_devices.setWordWrap(True)
        self._lbl_no_devices.setStyleSheet(f"color: {_CLR_TEXT_DIM}; font-size: 12px; padding: 40px 0;")
        inner.addWidget(self._lbl_no_devices)
        self._lbl_no_devices.hide()

        inner.addStretch()
        scroll.setWidget(container)
        return scroll

    # ── 4. Remote (Live Control) Page ────────────────────────────────────────
    def _build_remote_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background-color: {_CLR_BODY};")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(8)

        top_bar = QFrame()
        top_bar.setStyleSheet(f"background-color: {_CLR_CARD}; border: 1px solid {_CLR_CARD_BORDER}; border-radius: 6px;")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(14, 8, 14, 8)
        top_bar_layout.setSpacing(10)

        btn_back = QPushButton("← Anasayfa")
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {_CLR_ACCENT}; border: none; font-size: 12px; font-weight: 600; }}
            QPushButton:hover {{ color: {_CLR_TEXT}; }}
        """)
        btn_back.clicked.connect(lambda: self._switch_page(0))
        top_bar_layout.addWidget(btn_back)

        self._remote_device_badge = QLabel("Bagli cihaz yok")
        self._remote_device_badge.setStyleSheet(f"color: {_CLR_TEXT_MUTED}; font-size: 11px;")
        top_bar_layout.addStretch()
        top_bar_layout.addWidget(self._remote_device_badge)

        self._btn_disconnect = QPushButton("Baglantıyi Kes")
        self._btn_disconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_disconnect.setFixedHeight(28)
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.setStyleSheet(f"""
            QPushButton {{
                background-color: #442222; color: #FF8888; border: 1px solid #663333;
                border-radius: 4px; font-size: 11px; padding: 2px 12px;
            }}
            QPushButton:hover {{ background-color: #553333; }}
            QPushButton:disabled {{ background-color: #333; color: #666; border-color: #444; }}
        """)
        top_bar_layout.addWidget(self._btn_disconnect)
        left.addWidget(top_bar)

        screen_frame = QFrame()
        screen_frame.setStyleSheet(f"background-color: #111; border: 1px solid {_CLR_CARD_BORDER}; border-radius: 6px;")
        screen_layout = QVBoxLayout(screen_frame)
        screen_layout.setContentsMargins(4, 4, 4, 4)
        self._screen = ScreenWidget()
        screen_layout.addWidget(self._screen, stretch=1)

        self._lbl_coords = QLabel("")
        self._lbl_coords.setStyleSheet(f"color: {_CLR_TEXT_DIM}; font-size: 10px;")
        self._lbl_coords.setAlignment(Qt.AlignmentFlag.AlignRight)
        screen_layout.addWidget(self._lbl_coords)
        left.addWidget(screen_frame, stretch=1)

        self._remote_summary_label = QLabel("")
        layout.addLayout(left, stretch=7)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(self._build_controls_panel())
        right.addWidget(self._build_key_controls_panel())
        right.addStretch()
        layout.addLayout(right, stretch=3)
        return page

    def _build_controls_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(f"background-color: {_CLR_CARD}; border: 1px solid {_CLR_CARD_BORDER}; border-radius: 6px;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Kontroller")
        title.setStyleSheet(f"color: {_CLR_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(title)

        self._btn_rotate = QPushButton("Yatay moda gec")
        self._btn_rotate.setFixedHeight(30)
        self._btn_rotate.setEnabled(False)
        self._btn_rotate.setStyleSheet(f"""
            QPushButton {{
                background-color: {_CLR_INPUT_BG}; color: {_CLR_TEXT_MUTED};
                border: 1px solid {_CLR_CARD_BORDER}; border-radius: 4px;
                font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #444; color: {_CLR_TEXT}; }}
            QPushButton:disabled {{ color: #555; }}
        """)
        layout.addWidget(self._btn_rotate)
        return panel

    def _build_key_controls_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(f"background-color: {_CLR_CARD}; border: 1px solid {_CLR_CARD_BORDER}; border-radius: 6px;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Tus Kontrolleri")
        title.setStyleSheet(f"color: {_CLR_TEXT_MUTED}; font-size: 11px; font-weight: 600;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(4)
        self._key_buttons = []
        key_codes = AndroidKeyCodes.as_mapping()

        _key_btn_style = f"""
            QPushButton {{
                background-color: {_CLR_INPUT_BG}; color: {_CLR_TEXT_MUTED};
                border: 1px solid {_CLR_CARD_BORDER}; border-radius: 4px;
                font-size: 10px; padding: 6px 2px;
            }}
            QPushButton:hover {{ background-color: #444; color: {_CLR_TEXT}; }}
            QPushButton:disabled {{ color: #555; }}
        """

        for label, group, row, col, key_id in AndroidKeyCodes.button_specs():
            btn = QPushButton(label)
            btn.setEnabled(False)
            btn.setStyleSheet(_key_btn_style)
            btn.clicked.connect(lambda _, code=key_codes[key_id]: self._ws_client.send_key_event(code))
            grid.addWidget(btn, row, col)
            self._key_buttons.append(btn)
        layout.addLayout(grid)
        return panel

    # ── signals ──────────────────────────────────────────────────────────────
    def _connect_signals(self):
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        self._btn_rotate.clicked.connect(self._on_rotate_toggle)
        self._ws_client.connected.connect(self._on_ws_connected)
        self._ws_client.disconnected.connect(self._on_ws_disconnected)
        self._ws_client.paired.connect(self._on_paired)
        self._ws_client.auto_paired.connect(self._on_auto_paired)
        self._ws_client.peer_disconnected.connect(self._on_peer_disconnected)
        self._ws_client.error_occurred.connect(self._on_error)
        self._ws_client.paired_devices_status.connect(self._on_paired_devices_status)
        self._ws_client.frame_received.connect(self._on_frame_received)
        self._mjpeg.frame_ready.connect(self._screen.set_frame)
        self._mjpeg.error_occurred.connect(self._on_mjpeg_error)
        self._mjpeg.stream_stopped.connect(self._on_stream_stopped)
        self._screen.touch_event.connect(self._on_touch)
        self._screen.swipe_event.connect(self._on_swipe)

    def _switch_page(self, index: int):
        self._current_page = index
        self._pages.setCurrentIndex(index)

    # ── data loading ─────────────────────────────────────────────────────────
    @pyqtSlot()
    def _load_devices_from_db(self):
        if self._user_id:
            self.db.upsert_device(self._user_id, self._ws_client.device_id, "pc")
        devices = self.db.get_paired_devices(self._ws_client.device_id)
        self._populate_device_cards(devices)
        self._try_auto_connect()

    def _populate_device_cards(self, devices: list[dict]):
        for card in self._device_cards.values():
            self._recent_devices_layout.removeWidget(card)
            card.deleteLater()
        self._device_cards.clear()

        if not devices:
            self._lbl_no_devices.show()
            self._lbl_device_count.setText("")
            return

        self._lbl_no_devices.hide()
        cols = max(1, (self.width() - 80) // 220)
        for index, device in enumerate(devices):
            card = DeviceCard(device["device_id"], device.get("last_seen"), device.get("address"))
            card.set_connect_callback(self._on_card_connect)
            card.set_forget_callback(self._on_card_forget)
            row = index // cols
            col = index % cols
            self._recent_devices_layout.addWidget(card, row, col)
            self._device_cards[device["device_id"]] = card

        self._lbl_device_count.setText(f"{len(devices)} cihaz")
        self._refresh_home_summary()

    def _refresh_home_summary(self):
        if self._connected:
            self._addr_status_label.setText("Bagli")
            self._addr_status_dot.setStyleSheet(f"background-color: {_CLR_GREEN_DOT}; border-radius: 4px;")
        else:
            self._addr_status_label.setText("Hazir")
            self._addr_status_dot.setStyleSheet(f"background-color: {_CLR_GREEN_DOT}; border-radius: 4px;")

        if self._paired_phone_id:
            short_id = self._paired_phone_id[-8:]
            self._remote_device_badge.setText(f"Aktif: ...{short_id}")
            if self._session_tab_btn is not None:
                self._session_tab_btn.setText(f"  Cihaz ...{short_id}")
                self._session_tab_btn.show()
        else:
            self._remote_device_badge.setText("Bagli cihaz yok")
            if self._session_tab_btn is not None:
                self._session_tab_btn.hide()

    # ── card actions ─────────────────────────────────────────────────────────
    def _on_card_connect(self, device_id: str):
        self._paired_phone_id = device_id
        card = self._device_cards.get(device_id)
        if card:
            card.set_connecting()
        self._set_status("Secilen cihaza baglaniliyor...")
        self._ws_client.connect_with_device_id(ServerDefaults.DEFAULT_URL, preferred_partner_id=device_id)
        self._refresh_home_summary()

    def _on_card_forget(self, device_id: str):
        answer = QMessageBox.question(
            self, "Eslesmeyi Kaldir",
            "Bu eslesme kaldirilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if not self.db.delete_pairing(device_id, self._ws_client.device_id):
            self._set_status("Eslesme silinemedi.", error=True)
            return

        card = self._device_cards.pop(device_id, None)
        if card:
            self._recent_devices_layout.removeWidget(card)
            card.deleteLater()
        if not self._device_cards:
            self._lbl_no_devices.show()
        self._online_paired_devices.discard(device_id)

        if self._paired_phone_id == device_id:
            self._paired_phone_id = None
            clear_paired_phone_id()
            self._ws_client.forget_paired_phone()
            self._on_disconnect()

        self._refresh_home_summary()
        self._lbl_device_count.setText(f"{len(self._device_cards)} cihaz" if self._device_cards else "")
        self._set_status("Eslesme kaldirildi.")

    # ── auto connect ─────────────────────────────────────────────────────────
    @pyqtSlot()
    def _try_auto_connect(self):
        paired_id = load_paired_phone_id()
        if paired_id or self._device_cards:
            self._paired_phone_id = paired_id
            self._refresh_home_summary()
            self._set_status("Kayitli cihazlar kontrol ediliyor...")
            self._ws_client.connect_with_device_id(ServerDefaults.DEFAULT_URL, preferred_partner_id=paired_id)
        else:
            self._set_status(Ui.MSG_WAITING)

    # ── connect button ───────────────────────────────────────────────────────
    @pyqtSlot()
    def _on_connect(self):
        raw_value = self._inp_code.text().strip().replace(" ", "")
        if not raw_value:
            self._set_status("Adres girilmedi.", error=True)
            return
        if not raw_value.isdigit():
            self._set_status("Adres sadece rakam olmali.", error=True)
            return
        if len(raw_value) != 12:
            self._set_status("12 haneli sabit adresi girin.", error=True)
            return

        partner_device_id = self.db.find_phone_device_by_address(raw_value)
        if not partner_device_id:
            self._set_status("Bu adrese ait telefon bulunamadi.", error=True)
            return
        self._btn_connect.setEnabled(False)
        self._set_status("Adres cozuldu, baglaniliyor...")
        self._paired_phone_id = partner_device_id
        self._ws_client.connect_with_device_id(ServerDefaults.DEFAULT_URL, preferred_partner_id=partner_device_id)
        self._refresh_home_summary()

    @pyqtSlot()
    def _on_disconnect(self):
        self._mjpeg.stop()
        self._ws_client.disconnect()
        self._screen.clear_frame()
        self._set_connected(False)
        for card in self._device_cards.values():
            card.set_online(False)

    @pyqtSlot()
    def _on_logout(self):
        if self._logging_out:
            return
        self._logging_out = True

        self._mjpeg.stop()
        self._heartbeat.stop()
        self._ws_client.disconnect()
        self._screen.clear_frame()
        clear_logged_in()

        from desktop_app.ui.login_window import LoginWindow

        new_db = DbClient()
        login = LoginWindow(new_db, self)
        if login.exec() == QDialog.DialogCode.Accepted:
            replacement = MainWindow(new_db)
            app = QApplication.instance()
            if app is not None:
                setattr(app, "_rpc_main_window", replacement)
            replacement.show()
            self.close()
        else:
            new_db.close()
            import sys
            sys.exit(0)
        self._logging_out = False

    # ── WS slots ─────────────────────────────────────────────────────────────
    @pyqtSlot()
    def _on_ws_connected(self):
        self._set_status(Ui.MSG_SERVER_CONNECTED)
        self._btn_disconnect.setEnabled(True)

    @pyqtSlot(str)
    def _on_ws_disconnected(self, reason: str):
        self._set_connected(False)
        self._screen.clear_frame()
        for card in self._device_cards.values():
            card.set_online(False)
        self._online_paired_devices.clear()
        self._refresh_home_summary()
        if "10060" in reason or "timed out" in reason.lower():
            self._set_status(Ui.MSG_DISCONNECT_TIMEOUT, error=True)
        elif "already closed" in reason.lower():
            self._set_status("Baglanti kapandi.", error=True)
        else:
            self._set_status(f"Baglanti kesildi: {reason}", error=True)
        self._btn_connect.setEnabled(True)

    @pyqtSlot(str)
    def _on_paired(self, stream_url: str):
        self._set_connected(True)
        self._switch_page(1)
        self._set_status("Eslesme tamamlandi. Akis bekleniyor...")
        if stream_url and stream_url.startswith("http") and "0.0.0.0" not in stream_url and "10.0.2." not in stream_url:
            try:
                self._mjpeg.start(stream_url)
                self._set_status("Baglandi — video akisi aktif.")
                return
            except Exception:
                logger.exception("MJPEG akisi baslatilamadi")
        self._set_status(Ui.MSG_PAIRED_WS)

    @pyqtSlot(str)
    def _on_auto_paired(self, partner_device_id: str):
        self._paired_phone_id = partner_device_id
        self._set_connected(True)
        self._switch_page(1)
        self._set_status("Otomatik baglanti kuruldu.")

        self.db.save_pairing(partner_device_id, self._ws_client.device_id)
        self._ws_client.send_pair_confirm(partner_device_id)

        if partner_device_id not in self._device_cards:
            devices = self.db.get_paired_devices(self._ws_client.device_id)
            self._populate_device_cards(devices)

        card = self._device_cards.get(partner_device_id)
        if card:
            card.set_online(True)
        self._refresh_home_summary()

    @pyqtSlot(list, list)
    def _on_paired_devices_status(self, paired_devices: list, online_devices: list):
        self._online_paired_devices = set(online_devices)
        if paired_devices and any(did not in self._device_cards for did in paired_devices):
            devices = self.db.get_paired_devices(self._ws_client.device_id)
            self._populate_device_cards(devices)

        for device_id, card in self._device_cards.items():
            card.set_online(device_id in self._online_paired_devices)

        self._refresh_home_summary()

    @pyqtSlot()
    def _on_peer_disconnected(self):
        self._mjpeg.stop()
        self._screen.clear_frame()
        self._set_connected(False)
        if self._paired_phone_id and self._paired_phone_id in self._device_cards:
            self._device_cards[self._paired_phone_id].set_online(False)
        self._online_paired_devices.discard(self._paired_phone_id or "")
        self._refresh_home_summary()
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

    @pyqtSlot()
    def _on_rotate_toggle(self):
        self._rotation_step = (self._rotation_step + 1) % 4
        deg = self._rotation_step * 90
        self._screen.set_rotation(deg)
        labels = {0: "Yatay moda gec", 90: "180°", 180: "270°", 270: "Dikey moda don"}
        self._btn_rotate.setText(labels[deg])
        self._ws_client.send_rotate_screen(deg in (90, 270))

    @pyqtSlot(float, float)
    def _on_touch(self, x: float, y: float):
        if not self._connected:
            return
        self._ws_client.send_touch(x, y)
        self._lbl_coords.setText(f"x={x:.3f}  y={y:.3f}")

    @pyqtSlot(float, float, float, float)
    def _on_swipe(self, x1, y1, x2, y2):
        if not self._connected:
            return
        self._ws_client.send_swipe(x1, y1, x2, y2)
        self._lbl_coords.setText(f"({x1:.2f},{y1:.2f}) → ({x2:.2f},{y2:.2f})")

    # ── state helpers ────────────────────────────────────────────────────────
    def _set_connected(self, connected: bool):
        self._connected = connected
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)
        self._btn_rotate.setEnabled(connected)
        for btn in self._key_buttons:
            btn.setEnabled(connected)
        if connected:
            self._heartbeat.start()
            self._header_status_dot.setStyleSheet(f"background-color: {_CLR_GREEN_DOT}; border-radius: 4px;")
        else:
            self._heartbeat.stop()
            self._header_status_dot.setStyleSheet(f"background-color: {_CLR_TEXT_DIM}; border-radius: 4px;")
        self._refresh_home_summary()

    def _set_status(self, msg: str, error: bool = False):
        color = "#FF6666" if error else _CLR_TEXT_MUTED
        self._status_bar.setStyleSheet(
            f"QStatusBar {{ background-color: {_CLR_TITLEBAR}; border-top: 1px solid #333; color: {color}; font-size: 11px; }}"
        )
        self._status_bar.showMessage(msg)

    def closeEvent(self, event):
        self._mjpeg.stop()
        self._heartbeat.stop()
        self._ws_client.disconnect()
        self.db.close()
        super().closeEvent(event)
