import logging
import os

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QMenu,
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
from desktop_app.config.constants import Prefs
from desktop_app.config.prefs_store import (
    clear_logged_in,
    load_auth_token,
    clear_paired_phone_address,
    clear_paired_phone_id,
    load_paired_phone_id,
    load_paired_phone_address,
    load_user_address,
    save_paired_phone_address,
    save_user_address,
    read_prefs,
    update_prefs,
)
from desktop_app.database.db_client import DbClient
from desktop_app.network.backend_api import BackendApi
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

# ── Palette ──────────────────────────────────────────────────────────────────
_BG = "#181818"
_BG_RAISED = "#1E1E1E"
_BG_CARD = "#262626"
_BG_INPUT = "#2A2A2A"
_BORDER = "#333333"
_BORDER_SUBTLE = "#2C2C2C"
_ACCENT = "#E85D3A"
_ACCENT_HOVER = "#D04E2E"
_GREEN = "#4ADE80"
_GREEN_DIM = "rgba(74,222,128,0.35)"
_RED = "#F87171"
_TEXT = "#F0F0F0"
_TEXT_SEC = "#A0A0A0"
_TEXT_DIM = "#606060"


def _desktop_device_name() -> str:
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "Bu Bilgisayar"


def _format_address(addr: str) -> str:
    digits = "".join(ch for ch in addr if ch.isdigit())[:12]
    return "-".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def _format_address_spaced(addr: str) -> str:
    """Large hero display: '000000000001' → '0000-0000-0001'."""
    digits = "".join(ch for ch in addr if ch.isdigit())[:12]
    return "-".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def _display_device_name(device_name: str | None, address: str | None, device_id: str) -> str:
    if device_name and device_name.strip():
        return device_name.strip()
    if address and address.strip():
        return _format_address(address)
    return "..." + device_id[-8:] if len(device_id) > 8 else device_id


def _compact_label(text: str, limit: int = 24) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _address_digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:12]


def _phone_row_key(device: dict) -> str:
    """Recent kartlari: ayni emülatörde farkli hesaplar ayri device_id ile listelenir; MAC ile birlestirme yapilmaz."""
    return str(device.get("device_id") or "").strip()


def _is_accessibility_ws_error(message: str, code: str) -> bool:
    if (code or "").strip() == "accessibility_required":
        return True
    folded = (message or "").translate(str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")).lower()
    return "erisilebilirlik" in folded or "accessibility" in folded


def _merge_phone_device_row(existing: dict, row: dict) -> dict:
    did = str(row.get("device_id") or existing.get("device_id") or "").strip()
    dd = _address_digits(did)
    ra = _address_digits(row.get("address"))
    ea = _address_digits(existing.get("address"))
    if ra == dd and dd:
        addr = dd
    elif ea == dd and dd:
        addr = dd
    else:
        addr = ra or ea or dd
    out = {**existing, **row, "address": addr, "device_id": did}
    if "is_online" in row:
        out["is_online"] = bool(row["is_online"])
    for key in ("owner_name", "owner_phone", "owner_email", "owner_user_id"):
        if key in row and row.get(key) is not None:
            out[key] = row.get(key)
    return out


def _display_username(username: str | None) -> str:
    value = (username or "").strip()
    if not value:
        return "Kullanici"
    return value[:1].upper() + value[1:]


def _digits_before_cursor(text: str, cursor: int) -> int:
    """Count how many digit characters appear before `cursor` in `text`."""
    return sum(1 for ch in text[:cursor] if ch.isdigit())


def _cursor_for_digit_count(text: str, digit_count: int) -> int:
    """Return the character index in `text` after the first `digit_count` digits."""
    seen = 0
    for i, ch in enumerate(text):
        if ch.isdigit():
            seen += 1
            if seen == digit_count:
                return i + 1
    return len(text)


# ─────────────────────────────────────────────────────────────────────────────
# DeviceCard
# ─────────────────────────────────────────────────────────────────────────────
class DeviceCard(QFrame):
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
        self.device_id = device_id
        self.address = _address_digits(address)
        self.device_name = device_name
        self.owner_name = (owner_name or "").strip() or None
        self.owner_phone = (owner_phone or "").strip() or None
        self.owner_email = (owner_email or "").strip() or None
        self._online = False
        self._connect_cb = None
        self._forget_cb = None
        self.setFixedSize(230, 125)
        self._build(device_id, self.address, device_name)

    def _build(self, device_id: str, address: str | None, device_name: str | None):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(4)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._dot = QFrame()
        self._dot.setFixedSize(8, 8)
        self._dot.setStyleSheet(f"background-color: {_TEXT_DIM}; border-radius: 4px;")
        top_row.addWidget(self._dot)
        top_row.addStretch()

        self._btn_forget = QPushButton("×")
        self._btn_forget.setFixedSize(22, 22)
        self._btn_forget.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_forget.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {_TEXT_DIM}; border: none;
                border-radius: 11px; font-size: 14px; font-weight: 700;
            }}
            QPushButton:hover {{ color: {_RED}; background-color: rgba(248,113,113,0.12); }}
        """)
        self._btn_forget.clicked.connect(self._on_forget_clicked)
        top_row.addWidget(self._btn_forget)
        root.addLayout(top_row)

        root.addStretch()

        formatted = _display_device_name(device_name, address, device_id)
        title_text = self.owner_name or formatted
        self._title = QLabel(_compact_label(title_text, 24))
        self._title.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        root.addWidget(self._title)

        address_text = _format_address(address or "") if address else ""
        phone_text = (self.owner_phone or "").strip()
        if phone_text:
            subtitle = phone_text
            # Adres de varsa ikisini göster (kısa ve tanıdık)
            if address_text:
                subtitle = f"{phone_text}  •  {address_text}"
        else:
            subtitle = address_text if address_text and address_text != formatted else "Eslesmis cihaz"
        self._lbl_address = QLabel(subtitle)
        self._lbl_address.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 10px; background: transparent;")
        root.addWidget(self._lbl_address)

        self._lbl_status = QLabel("Cevrimdisi")
        self._lbl_status.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; background: transparent;")
        root.addWidget(self._lbl_status)

        self._apply_card_style()

    def display_name(self) -> str:
        return _display_device_name(self.device_name, self.address, self.device_id)

    def connection_address(self) -> str | None:
        digits = _address_digits(self.address)
        return _format_address(digits) if digits else None

    def card_key(self) -> str:
        return str(self.device_id)

    def set_connect_callback(self, cb):
        self._connect_cb = cb

    def set_forget_callback(self, cb):
        self._forget_cb = cb

    def _apply_card_style(self):
        if self._online:
            self.setStyleSheet(f"""
                DeviceCard {{
                    background-color: {_BG_CARD};
                    border: 1px solid {_GREEN_DIM};
                    border-radius: 8px;
                }}
                DeviceCard:hover {{ border-color: {_GREEN}; }}
            """)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setStyleSheet(f"""
                DeviceCard {{
                    background-color: {_BG_CARD};
                    border: 1px solid {_BORDER_SUBTLE};
                    border-radius: 8px;
                }}
                DeviceCard:hover {{ border-color: {_BORDER}; }}
            """)
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_online(self, online: bool):
        self._online = online
        if online:
            self._dot.setStyleSheet(f"background-color: {_GREEN}; border-radius: 4px;")
            self._lbl_status.setText("Cevrimici")
            self._lbl_status.setStyleSheet(f"color: {_GREEN}; font-size: 10px; font-weight: 600; background: transparent;")
        else:
            self._dot.setStyleSheet(f"background-color: {_TEXT_DIM}; border-radius: 4px;")
            self._lbl_status.setText("Cevrimdisi")
            self._lbl_status.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; background: transparent;")
        self._apply_card_style()

    def is_online(self) -> bool:
        return self._online

    def set_connecting(self):
        self._lbl_status.setText("Baglaniyor...")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._online and self._connect_cb:
            self._connect_cb(self.card_key())
        super().mousePressEvent(event)

    def _on_forget_clicked(self):
        if self._forget_cb:
            self._forget_cb(self.card_key())


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
        self._paired_phone_address: str | None = None
        self._device_cards: dict[str, DeviceCard] = {}
        self._online_paired_devices: set[str] = set()
        self._logging_out = False
        self._manual_disconnect = False
        self._ws_mode = "idle"
        self._user_id: int | None = None
        self._username = "Kullanici"
        self._user_email = ""
        self._user_address = ""
        self._auth_token = ""
        self._current_page = 0
        self._account_button: QPushButton | None = None
        self._backend_api = BackendApi()

        self.setWindowTitle(AppMeta.WINDOW_TITLE)
        self.setMinimumSize(960, 600)
        self.resize(1060, 700)
        self._load_user_prefs()
        self._apply_global_style()
        self._build_ui()
        self._connect_signals()

        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(Network.HEARTBEAT_INTERVAL_MS)
        self._heartbeat.timeout.connect(self._ws_client.send_heartbeat)

        self._presence_timer = QTimer(self)
        self._presence_timer.setInterval(4_000)
        self._presence_timer.timeout.connect(self._on_presence_tick)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._reconnect_current_mode)

        QTimer.singleShot(250, self._load_devices_from_db)

    def _load_user_prefs(self):
        prefs = read_prefs()
        self._user_id = prefs.get("user_id")
        self._username = prefs.get("username", "Kullanici")
        self._user_email = (prefs.get(Prefs.KEY_USER_EMAIL) or "").strip()
        self._auth_token = load_auth_token()
        self._user_address = load_user_address()
        if self._auth_token:
            profile, _ = self._backend_api.get_me(self._auth_token, self._ws_client.device_id)
            if profile:
                self._user_address = _address_digits(profile.get("address"))
                if self._user_address:
                    save_user_address(self._user_address)
                em = (profile.get("email") or "").strip()
                if em:
                    self._user_email = em
                    update_prefs(**{Prefs.KEY_USER_EMAIL: em})
        if not self._user_address and self._user_id:
            self._user_address = self.db.get_user_address(self._user_id) or ""
        if not self._user_email:
            self._user_email = self._username
        self._ws_client.set_device_address(self._user_address)

    def _load_paired_devices(self) -> list[dict]:
        merged: dict[str, dict] = {}
        if self._auth_token:
            devices, devices_error = self._backend_api.get_devices(self._auth_token)
            if devices is not None:
                for device in devices:
                    if device.get("device_type") == "phone" and device.get("device_id") != self._ws_client.device_id:
                        key = _phone_row_key(device)
                        if not key:
                            continue
                        merged[key] = _merge_phone_device_row(merged.get(key, {}), dict(device))
            else:
                logger.warning("Server devices alinamadi: %s", devices_error)

            recent_devices, recent_error = self._backend_api.get_recent_devices(self._auth_token, "phone")
            if recent_devices is not None:
                for device in recent_devices:
                    if device.get("device_type") == "phone" and device.get("device_id") != self._ws_client.device_id:
                        key = _phone_row_key(device)
                        if not key:
                            continue
                        existing = merged.get(key, {})
                        merged[key] = _merge_phone_device_row(existing, dict(device))
            else:
                logger.warning("Server recent devices alinamadi: %s", recent_error)

            pairings, pairings_error = self._backend_api.get_pairings(self._auth_token, self._ws_client.device_id)
            if pairings is not None:
                for device in pairings:
                    if device.get("device_type") == "phone" and device.get("device_id") != self._ws_client.device_id:
                        key = _phone_row_key(device)
                        if not key:
                            continue
                        existing = merged.get(key, {})
                        merged[key] = _merge_phone_device_row(existing, dict(device))
            else:
                logger.warning("Server pairings alinamadi: %s", pairings_error)

            if merged:
                return list(merged.values())
        return self.db.get_paired_devices(self._ws_client.device_id)

    def _connect_presence_mode(self, status_message: str | None = None):
        if self._logging_out:
            return
        if not (self._device_cards or load_paired_phone_id() or load_paired_phone_address()):
            self._ws_mode = "idle"
            self._set_status(Ui.MSG_WAITING)
            return
        self._ws_mode = "presence"
        self._reconnect_timer.stop()
        self._presence_timer.stop()
        if status_message:
            self._set_status(status_message)
        self._manual_disconnect = True
        self._ws_client.connect_with_device_id(ServerDefaults.DEFAULT_URL)

    def _connect_session_mode(
        self,
        partner_device_id: str | None = None,
        partner_address: str | None = None,
        status_message: str | None = None,
    ):
        address_digits = "".join(ch for ch in (partner_address or "") if ch.isdigit())[:12]
        if not partner_device_id and not address_digits:
            return
        self._ws_mode = "session"
        self._paired_phone_id = partner_device_id
        self._paired_phone_address = address_digits or None
        self._reconnect_timer.stop()
        self._presence_timer.stop()
        if status_message:
            self._set_status(status_message)
        self._manual_disconnect = True
        if address_digits:
            save_paired_phone_address(address_digits)
        session_code = address_digits or _address_digits(partner_device_id)
        if not session_code:
            return
        self._ws_client.connect_to_server(ServerDefaults.DEFAULT_URL, session_code)

    def _schedule_reconnect(self, delay_ms: int = 1500):
        if self._logging_out:
            return
        if not self._reconnect_timer.isActive():
            self._reconnect_timer.start(delay_ms)

    def _reconnect_current_mode(self):
        if self._logging_out:
            return
        if self._ws_mode == "session" and (self._paired_phone_id or self._paired_phone_address):
            self._connect_session_mode(
                self._paired_phone_id,
                self._paired_phone_address,
                "Baglanti yeniden kuruluyor...",
            )
            return
        self._connect_presence_mode("Cihaz durumu yeniden baglaniyor...")

    # ── Global stylesheet ────────────────────────────────────────────────────
    def _apply_global_style(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {_BG}; }}
            QWidget {{
                background: transparent; color: {_TEXT};
                font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
            }}
            QScrollArea {{ border: none; }}
            QScrollBar:vertical {{
                background: {_BG}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #444; border-radius: 3px; min-height: 24px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    # ── Build UI ─────────────────────────────────────────────────────────────
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
            f"QStatusBar {{ background-color: {_BG}; border-top: 1px solid {_BORDER_SUBTLE};"
            f" color: {_TEXT_SEC}; font-size: 11px; padding: 2px 14px; }}"
        )
        self.setStatusBar(self._status_bar)

    # ── 1. Title Bar ─────────────────────────────────────────────────────────
    _TAB_STYLE_ACTIVE = (
        f"QPushButton {{ background: transparent; color: {_TEXT}; border: none;"
        f" border-bottom: 2px solid {_ACCENT}; font-size: 12px; font-weight: 600;"
        f" padding: 6px 14px 4px 14px; }}"
    )
    _TAB_STYLE_INACTIVE = (
        f"QPushButton {{ background: transparent; color: {_TEXT_SEC}; border: none;"
        f" border-bottom: 2px solid transparent; font-size: 12px; font-weight: 500;"
        f" padding: 6px 14px 4px 14px; }}"
        f" QPushButton:hover {{ color: {_TEXT}; }}"
    )

    def _build_title_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(38)
        bar.setStyleSheet(f"background-color: {_BG}; border-bottom: 1px solid {_BORDER_SUBTLE};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(0)

        logo = QFrame()
        logo.setFixedSize(10, 10)
        logo.setStyleSheet(f"background-color: {_ACCENT}; border-radius: 5px;")
        lay.addWidget(logo)
        lay.addSpacing(10)

        self._tab_home = QPushButton("Anasayfa")
        self._tab_home.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_home.setStyleSheet(self._TAB_STYLE_ACTIVE)
        self._tab_home.clicked.connect(lambda: self._switch_page(0))
        lay.addWidget(self._tab_home)

        self._tab_session = QFrame()
        tab_session_lay = QHBoxLayout(self._tab_session)
        tab_session_lay.setContentsMargins(0, 0, 0, 0)
        tab_session_lay.setSpacing(0)

        self._tab_session_btn = QPushButton("Oturum")
        self._tab_session_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_session_btn.setStyleSheet(self._TAB_STYLE_INACTIVE)
        self._tab_session_btn.clicked.connect(lambda: self._switch_page(1))
        tab_session_lay.addWidget(self._tab_session_btn)

        self._tab_session_close = QPushButton("×")
        self._tab_session_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_session_close.setFixedSize(20, 20)
        self._tab_session_close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {_TEXT_DIM}; border: none; font-size: 13px; font-weight: 700; }}
            QPushButton:hover {{ color: {_RED}; }}
        """)
        self._tab_session_close.setToolTip("Baglantıyi kes")
        self._tab_session_close.clicked.connect(self._on_disconnect)
        tab_session_lay.addWidget(self._tab_session_close)

        self._tab_session.hide()
        lay.addWidget(self._tab_session)

        lay.addStretch()

        self._header_status_dot = QFrame()
        self._header_status_dot.setFixedSize(8, 8)
        self._header_status_dot.setStyleSheet(f"background-color: {_TEXT_DIM}; border-radius: 4px;")
        lay.addWidget(self._header_status_dot)
        lay.addSpacing(6)

        self._account_button = QPushButton(f"{self._user_email or self._username}  ▾")
        self._account_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._account_button.setFixedHeight(26)
        self._account_button.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {_TEXT_SEC}; border: 1px solid {_BORDER};
                border-radius: 4px; font-size: 11px; padding: 0 10px;
            }}
            QPushButton:hover {{ color: {_TEXT}; border-color: #555; }}
        """)
        self._account_button.clicked.connect(self._show_account_menu)
        lay.addWidget(self._account_button)

        return bar

    # ── 2. Home Page ─────────────────────────────────────────────────────────
    def _build_home_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background-color: {_BG};")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"background-color: {_BG};")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_address_input_bar())
        layout.addWidget(self._build_your_address_hero())
        layout.addWidget(self._build_warning_banner())
        layout.addWidget(self._build_feature_cards())
        layout.addWidget(self._build_tab_strip())
        layout.addWidget(self._build_recent_sessions())
        layout.addStretch()

        scroll.setWidget(content)

        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll)
        return page

    def _build_warning_banner(self) -> QWidget:
        banner = QFrame()
        banner.setStyleSheet(
            "background: transparent;"
        )
        lay = QHBoxLayout(banner)
        lay.setContentsMargins(28, 0, 28, 10)
        lay.setSpacing(10)

        card = QFrame()
        card.setStyleSheet(
            "QFrame {"
            f"  background-color: rgba(248,113,113,0.10);"
            f"  border: 1px solid rgba(248,113,113,0.35);"
            "  border-radius: 8px;"
            "}"
        )
        cl = QHBoxLayout(card)
        cl.setContentsMargins(14, 10, 14, 10)
        cl.setSpacing(10)

        icon = QLabel("!")
        icon.setFixedSize(18, 18)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            f"background-color: {_RED}; color: #1A1A1A; border-radius: 9px; font-weight: 800;"
        )
        cl.addWidget(icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._warning_title = QLabel("Uyari")
        self._warning_title.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: 700;")
        text_col.addWidget(self._warning_title)

        self._warning_text = QLabel("")
        self._warning_text.setWordWrap(True)
        self._warning_text.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px;")
        text_col.addWidget(self._warning_text)
        cl.addLayout(text_col, stretch=1)

        self._warning_close = QPushButton("Kapat")
        self._warning_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._warning_close.setFixedHeight(28)
        self._warning_close.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(248,113,113,0.14);
                color: {_RED};
                border: 1px solid rgba(248,113,113,0.30);
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
                padding: 0 12px;
            }}
            QPushButton:hover {{ background-color: rgba(248,113,113,0.20); }}
        """)
        self._warning_close.clicked.connect(self._hide_warning_banner)
        cl.addWidget(self._warning_close)

        lay.addWidget(card)
        banner.hide()
        self._warning_banner = banner
        return banner

    def _show_warning_banner(self, title: str, message: str) -> None:
        banner = getattr(self, "_warning_banner", None)
        if banner is None:
            return
        self._warning_title.setText(title)
        self._warning_text.setText(message)
        banner.show()

    def _hide_warning_banner(self) -> None:
        banner = getattr(self, "_warning_banner", None)
        if banner is not None:
            banner.hide()

    # ── 2a. Full-width address input bar ─────────────────────────────────────
    def _build_address_input_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(42)
        bar.setStyleSheet(f"background-color: {_BG_RAISED}; border-bottom: 1px solid {_BORDER_SUBTLE};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)

        dot = QFrame()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(f"background-color: {_GREEN}; border-radius: 4px;")
        lay.addWidget(dot)

        self._inp_code = QLineEdit()
        self._inp_code.setPlaceholderText("Telefon sabit adresi (12 hane)")
        self._inp_code.setFixedHeight(28)
        self._inp_code.setMaxLength(14)
        font = QFont("Segoe UI", 12)
        self._inp_code.setFont(font)
        self._inp_code.setStyleSheet(f"""
            QLineEdit {{
                background-color: {_BG_INPUT}; border: 1px solid {_BORDER};
                border-radius: 4px; padding: 0 10px; color: {_TEXT};
                selection-background-color: {_ACCENT};
            }}
            QLineEdit:focus {{ border-color: {_ACCENT}; }}
        """)
        self._inp_code.returnPressed.connect(self._on_connect)
        self._inp_code.textChanged.connect(self._on_address_text_changed)
        lay.addWidget(self._inp_code, stretch=1)

        self._btn_connect = QPushButton("→")
        self._btn_connect.setFixedSize(28, 28)
        self._btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_connect.setStyleSheet(f"""
            QPushButton {{
                background-color: {_ACCENT}; color: white; border: none;
                border-radius: 4px; font-size: 16px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}
            QPushButton:disabled {{ background-color: #444; color: #666; }}
        """)
        lay.addWidget(self._btn_connect)

        self._addr_status_label = QLabel("Hazir")
        self._addr_status_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px;")
        self._addr_status_label.setFixedWidth(50)
        lay.addWidget(self._addr_status_label)

        return bar

    # ── 2b. Your Address hero (horizontal: address left + device info right) ─
    def _build_your_address_hero(self) -> QWidget:
        hero = QFrame()
        hero.setStyleSheet(f"background-color: {_BG};")
        outer = QHBoxLayout(hero)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(4)

        lbl_title = QLabel("Senin Adresin")
        lbl_title.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 14px;")
        left.addWidget(lbl_title)

        formatted = _format_address_spaced(self._user_address) if self._user_address else "—"
        self._hero_address = QLabel(formatted)
        hero_font = QFont("Segoe UI", 36, QFont.Weight.Bold)
        hero_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0)
        self._hero_address.setFont(hero_font)
        self._hero_address.setStyleSheet(f"color: {_TEXT};")
        left.addWidget(self._hero_address)
        left.addStretch()

        outer.addLayout(left, stretch=5)

        sep = QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background-color: {_BORDER_SUBTLE};")
        outer.addWidget(sep)

        right = QVBoxLayout()
        right.setSpacing(10)

        info_title = QLabel("Bu Bilgisayar")
        info_title.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 13px; font-weight: 600;")
        right.addWidget(info_title)

        pc_name = _desktop_device_name()
        info_pc = QLabel(f"  {pc_name}")
        info_pc.setStyleSheet(f"color: {_TEXT}; font-size: 14px; font-weight: 500;")
        right.addWidget(info_pc)

        info_user = QLabel(f"  {self._user_email or _display_username(self._username)}")
        info_user.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 13px;")
        right.addWidget(info_user)

        self._hero_status_label = QLabel("  Baglanti bekleniyor")
        self._hero_status_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
        right.addWidget(self._hero_status_label)

        right.addStretch()
        outer.addLayout(right, stretch=3)

        return hero

    # ── 2c. Feature cards row (AnyDesk news-like tiles) ──────────────────────
    def _build_feature_cards(self) -> QWidget:
        wrapper = QFrame()
        wrapper.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(wrapper)
        lay.setContentsMargins(28, 0, 28, 16)
        lay.setSpacing(12)

        cards_data = [
            ("Hizli Baglanti", "Telefonunuzun sabit\nadresini ust cubuga\nyazarak baglanin.", "#C84B31", "#A33B24"),
            ("Nasil Calisir?", "1. Telefonda uygulamayi acin\n2. Sabit adresi buraya girin\n3. Baglan!", "#2D6A4F", "#1B4332"),
            ("Gizlilik ve Guvenlik", "Tum baglantilar uctan\nuca sifrelidir. Cihaz\nsahipligi korunur.", "#4A3B8F", "#362C6B"),
            ("Cihaz Yonetimi", "Eslesmis cihazlarinizi\nasagida gorebilir ve\nyonetebilirsiniz.", "#8B6914", "#6B5010"),
        ]

        for title, desc, bg_color, hover_color in cards_data:
            card = QFrame()
            card.setMinimumHeight(120)
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: {bg_color}; border-radius: 8px;
                    border: none;
                }}
                QFrame:hover {{ background-color: {hover_color}; }}
            """)
            card_lay = QVBoxLayout(card)
            card_lay.setContentsMargins(14, 12, 14, 12)
            card_lay.setSpacing(6)

            lbl_title = QLabel(title)
            lbl_title.setStyleSheet("color: white; font-size: 14px; font-weight: 700; background: transparent;")
            card_lay.addWidget(lbl_title)

            lbl_desc = QLabel(desc)
            lbl_desc.setWordWrap(True)
            lbl_desc.setStyleSheet("color: rgba(255,255,255,0.85); font-size: 12px; background: transparent;")
            card_lay.addWidget(lbl_desc)

            card_lay.addStretch()
            lay.addWidget(card, stretch=1)

        return wrapper

    # ── 2d. Tab strip ────────────────────────────────────────────────────────
    def _build_tab_strip(self) -> QWidget:
        strip = QFrame()
        strip.setFixedHeight(32)
        strip.setStyleSheet(f"background-color: {_BG}; border-bottom: 1px solid {_BORDER_SUBTLE};")
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(28, 0, 28, 0)
        lay.setSpacing(24)

        tab = QLabel("Recent Sessions")
        tab.setStyleSheet(
            f"color: {_ACCENT}; font-size: 13px; font-weight: 600;"
            f" border-bottom: 2px solid {_ACCENT}; padding-bottom: 4px;"
        )
        lay.addWidget(tab)

        lay.addStretch()

        self._lbl_device_count = QLabel("")
        self._lbl_device_count.setStyleSheet(
            f"color: {_TEXT_DIM}; font-size: 11px; padding: 0 4px;"
        )
        lay.addWidget(self._lbl_device_count)

        return strip

    # ── 2e. Recent sessions grid ─────────────────────────────────────────────
    def _build_recent_sessions(self) -> QWidget:
        section = QWidget()
        section.setStyleSheet("background: transparent;")
        inner = QVBoxLayout(section)
        inner.setContentsMargins(28, 14, 28, 20)
        inner.setSpacing(10)

        header = QHBoxLayout()
        icon_lbl = QLabel("Recent Sessions")
        icon_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px; font-weight: 600;")
        header.addWidget(icon_lbl)
        header.addStretch()
        hint = QLabel("Show all")
        hint.setStyleSheet(f"color: {_ACCENT}; font-size: 12px;")
        header.addWidget(hint)
        inner.addLayout(header)

        self._recent_cards_container = QWidget()
        self._recent_cards_container.setStyleSheet("background: transparent;")
        self._recent_devices_layout = QGridLayout(self._recent_cards_container)
        self._recent_devices_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_devices_layout.setHorizontalSpacing(12)
        self._recent_devices_layout.setVerticalSpacing(12)
        self._recent_devices_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        inner.addWidget(self._recent_cards_container)

        self._lbl_no_devices = QFrame()
        self._lbl_no_devices.setStyleSheet(
            f"background-color: {_BG_CARD}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 8px;"
        )
        no_dev_lay = QVBoxLayout(self._lbl_no_devices)
        no_dev_lay.setContentsMargins(0, 30, 0, 30)
        no_dev_lay.setSpacing(8)
        no_dev_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        empty_icon = QLabel("📱")
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setStyleSheet("font-size: 32px; background: transparent;")
        no_dev_lay.addWidget(empty_icon)

        empty_title = QLabel("Henuz eslesmis cihaz yok")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 14px; font-weight: 600; background: transparent;")
        no_dev_lay.addWidget(empty_title)

        empty_desc = QLabel(
            "Telefonunuzdaki uygulamayi acin ve 12 haneli sabit adresi\n"
            "yukardaki adres cubuguna girerek ilk baglantiyi kurun."
        )
        empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_desc.setWordWrap(True)
        empty_desc.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px; background: transparent;")
        no_dev_lay.addWidget(empty_desc)

        inner.addWidget(self._lbl_no_devices)
        self._lbl_no_devices.hide()

        return section

    # ── 3. Remote Page ───────────────────────────────────────────────────────
    def _build_remote_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background-color: {_BG};")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(8)

        top_bar = QFrame()
        top_bar.setStyleSheet(
            f"background-color: {_BG_CARD}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
        )
        tbl = QHBoxLayout(top_bar)
        tbl.setContentsMargins(14, 6, 14, 6)
        tbl.setSpacing(10)

        self._remote_device_badge = QLabel("Bagli cihaz yok")
        self._remote_device_badge.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px;")
        tbl.addStretch()
        tbl.addWidget(self._remote_device_badge)

        self._btn_disconnect = QPushButton("Baglantıyi Kes")
        self._btn_disconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_disconnect.setFixedHeight(28)
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.setStyleSheet(f"""
            QPushButton {{
                background-color: #3A2020; color: #FF8888; border: 1px solid #553333;
                border-radius: 4px; font-size: 11px; font-weight: 600; padding: 0 12px;
            }}
            QPushButton:hover {{ background-color: #4A2828; }}
            QPushButton:disabled {{ background-color: {_BG_INPUT}; color: {_TEXT_DIM}; border-color: {_BORDER_SUBTLE}; }}
        """)
        tbl.addWidget(self._btn_disconnect)
        left.addWidget(top_bar)

        self._remote_pair_row = QFrame()
        self._remote_pair_row.setStyleSheet(
            f"background-color: {_BG_RAISED}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
        )
        rpl = QHBoxLayout(self._remote_pair_row)
        rpl.setContentsMargins(12, 8, 12, 8)
        rpl.setSpacing(10)
        rpl_lbl = QLabel("Telefon sabit adresi")
        rpl_lbl.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px; font-weight: 600;")
        rpl.addWidget(rpl_lbl)
        self._inp_remote_code = QLineEdit()
        self._inp_remote_code.setPlaceholderText("Ornek: 4399-0314-5105")
        self._inp_remote_code.setFixedHeight(28)
        self._inp_remote_code.setMaxLength(14)
        rfont = QFont("Segoe UI", 12)
        self._inp_remote_code.setFont(rfont)
        self._inp_remote_code.setStyleSheet(f"""
            QLineEdit {{
                background-color: {_BG_INPUT}; border: 1px solid {_BORDER};
                border-radius: 4px; padding: 0 10px; color: {_TEXT};
                selection-background-color: {_ACCENT};
            }}
            QLineEdit:focus {{ border-color: {_ACCENT}; }}
        """)
        self._inp_remote_code.returnPressed.connect(self._on_remote_connect)
        self._inp_remote_code.textChanged.connect(self._on_remote_address_text_changed)
        rpl.addWidget(self._inp_remote_code, stretch=1)
        self._btn_remote_connect = QPushButton("Baglan")
        self._btn_remote_connect.setFixedHeight(28)
        self._btn_remote_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_remote_connect.setStyleSheet(f"""
            QPushButton {{
                background-color: {_ACCENT}; color: white; border: none;
                border-radius: 4px; font-size: 11px; font-weight: 600; padding: 0 14px;
            }}
            QPushButton:hover {{ background-color: {_ACCENT_HOVER}; }}
            QPushButton:disabled {{ background-color: #444; color: #666; }}
        """)
        rpl.addWidget(self._btn_remote_connect)
        left.addWidget(self._remote_pair_row)

        screen_frame = QFrame()
        screen_frame.setStyleSheet(
            f"background-color: #0E0E0E; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
        )
        sl = QVBoxLayout(screen_frame)
        sl.setContentsMargins(4, 4, 4, 4)
        self._screen = ScreenWidget()
        sl.addWidget(self._screen, stretch=1)

        self._lbl_coords = QLabel("")
        self._lbl_coords.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px;")
        self._lbl_coords.setAlignment(Qt.AlignmentFlag.AlignRight)
        sl.addWidget(self._lbl_coords)
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
        panel.setStyleSheet(
            f"background-color: {_BG_CARD}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel("Kontroller")
        title.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px; font-weight: 600;")
        lay.addWidget(title)

        self._btn_rotate = QPushButton("Yatay moda gec")
        self._btn_rotate.setFixedHeight(30)
        self._btn_rotate.setEnabled(False)
        self._btn_rotate.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_rotate.setStyleSheet(f"""
            QPushButton {{
                background-color: {_BG_INPUT}; color: {_TEXT_SEC};
                border: 1px solid {_BORDER}; border-radius: 4px; font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #383838; color: {_TEXT}; }}
            QPushButton:disabled {{ color: {_TEXT_DIM}; }}
        """)
        lay.addWidget(self._btn_rotate)
        return panel

    def _build_key_controls_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(
            f"background-color: {_BG_CARD}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel("Tus Kontrolleri")
        title.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px; font-weight: 600;")
        lay.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(4)
        self._key_buttons = []
        key_codes = AndroidKeyCodes.as_mapping()

        _btn_style = f"""
            QPushButton {{
                background-color: {_BG_INPUT}; color: {_TEXT_SEC};
                border: 1px solid {_BORDER}; border-radius: 4px;
                font-size: 10px; padding: 6px 2px;
            }}
            QPushButton:hover {{ background-color: #383838; color: {_TEXT}; }}
            QPushButton:disabled {{ color: {_TEXT_DIM}; }}
        """

        for label, group, row, col, key_id in AndroidKeyCodes.button_specs():
            btn = QPushButton(label)
            btn.setEnabled(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_btn_style)
            btn.clicked.connect(lambda _, code=key_codes[key_id]: self._ws_client.send_key_event(code))
            grid.addWidget(btn, row, col)
            self._key_buttons.append(btn)
        lay.addLayout(grid)
        return panel

    # ── Signals ──────────────────────────────────────────────────────────────
    def _connect_signals(self):
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_remote_connect.clicked.connect(self._on_remote_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        self._btn_rotate.clicked.connect(self._on_rotate_toggle)
        self._ws_client.connected.connect(self._on_ws_connected)
        self._ws_client.disconnected.connect(self._on_ws_disconnected)
        self._ws_client.paired.connect(self._on_paired)
        self._ws_client.peer_disconnected.connect(self._on_peer_disconnected)
        self._ws_client.error_occurred.connect(self._on_error)
        self._ws_client.paired_devices_status.connect(
            self._on_paired_devices_status,
            Qt.ConnectionType.QueuedConnection,
        )
        self._ws_client.frame_received.connect(self._on_frame_received)
        self._mjpeg.frame_ready.connect(self._screen.set_frame)
        self._mjpeg.error_occurred.connect(self._on_mjpeg_error)
        self._mjpeg.stream_stopped.connect(self._on_stream_stopped)
        self._screen.touch_event.connect(self._on_touch)
        self._screen.swipe_event.connect(self._on_swipe)

    def _switch_page(self, index: int):
        self._current_page = index
        self._pages.setCurrentIndex(index)
        if index == 0:
            self._tab_home.setStyleSheet(self._TAB_STYLE_ACTIVE)
            self._tab_session_btn.setStyleSheet(self._TAB_STYLE_INACTIVE)
        else:
            self._tab_home.setStyleSheet(self._TAB_STYLE_INACTIVE)
            self._tab_session_btn.setStyleSheet(self._TAB_STYLE_ACTIVE)

    # ── Data loading ─────────────────────────────────────────────────────────
    @pyqtSlot()
    def _load_devices_from_db(self):
        if self._user_id:
            self.db.upsert_device(self._user_id, self._ws_client.device_id, "pc", _desktop_device_name())
        devices = self._load_paired_devices()
        self._populate_device_cards(devices)
        self._connect_presence_channel("Cihaz durumu izleniyor...")

    def _populate_device_cards(self, devices: list[dict]):
        for card in self._device_cards.values():
            self._recent_devices_layout.removeWidget(card)
            card.deleteLater()
        self._device_cards.clear()
        db_online_devices = {
            str(device["device_id"])
            for device in devices
            if bool(device.get("is_online"))
        }
        self._online_paired_devices = set(db_online_devices)

        if not devices:
            self._lbl_no_devices.show()
            self._lbl_device_count.setText("")
            return

        self._lbl_no_devices.hide()
        for device in devices:
            card = DeviceCard(
                device["device_id"],
                device.get("address"),
                device.get("device_name"),
                device.get("owner_name"),
                device.get("owner_phone"),
                device.get("owner_email"),
            )
            card_key = card.card_key()
            online_hint = card_key in self._online_paired_devices
            card.set_online(online_hint)
            card.set_connect_callback(self._on_card_connect)
            card.set_forget_callback(self._on_card_forget)
            self._device_cards[card_key] = card

        online_count = sum(1 for device in devices if str(device["device_id"]) in self._online_paired_devices)
        self._lbl_device_count.setText(
            f"{online_count} aktif / {len(devices)} cihaz" if devices else ""
        )
        self._reflow_device_cards()
        self._refresh_home_summary()

    def _card_for_member_device(self, device_id: str) -> DeviceCard | None:
        for card in self._device_cards.values():
            if device_id == card.device_id:
                return card
        return None

    def _reflow_device_cards(self):
        while self._recent_devices_layout.count():
            self._recent_devices_layout.takeAt(0)

        ordered = sorted(
            self._device_cards.items(),
            key=lambda item: (not item[1].is_online(),),
        )
        cols = max(1, (self.width() - 60) // 236)
        for idx, (_, card) in enumerate(ordered):
            self._recent_devices_layout.addWidget(card, idx // cols, idx % cols)

    def _refresh_home_summary(self):
        if self._connected:
            self._addr_status_label.setText("Bagli")
            self._hero_status_label.setText("  Aktif baglanti var")
            self._hero_status_label.setStyleSheet(f"color: {_GREEN}; font-size: 12px;")
        else:
            self._addr_status_label.setText("Hazir")
            online = len(self._online_paired_devices)
            if online:
                self._hero_status_label.setText(f"  {online} cihaz cevrimici")
                self._hero_status_label.setStyleSheet(f"color: {_GREEN}; font-size: 12px;")
            else:
                self._hero_status_label.setText("  Baglanti bekleniyor")
                self._hero_status_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")

        active_card = None
        if self._paired_phone_id:
            active_card = self._device_cards.get(str(self._paired_phone_id))
        if active_card is None and self._paired_phone_address:
            addr = _address_digits(self._paired_phone_address)
            active_card = next(
                (c for c in self._device_cards.values() if c.address == addr),
                None,
            )
        if self._connected and (active_card or self._paired_phone_id):
            display_name = active_card.display_name() if active_card else f"...{self._paired_phone_id[-8:]}"
            compact_name = _compact_label(display_name, 20)
            self._remote_device_badge.setText(f"Aktif: {compact_name}")
            self._tab_session_btn.setText(f"  {compact_name}")
            self._tab_session.show()
        else:
            self._remote_device_badge.setText("Bagli cihaz yok")
            self._tab_session.hide()

        if self._account_button is not None:
            acct = self._user_email or self._username
            self._account_button.setText(f"{acct}  ▾")

    def _show_account_menu(self):
        if self._account_button is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {_BG_CARD}; color: {_TEXT}; border: 1px solid {_BORDER};
                padding: 4px;
            }}
            QMenu::item {{ padding: 8px 20px; }}
            QMenu::item:selected {{ background-color: #333; }}
            QMenu::separator {{ height: 1px; background: {_BORDER_SUBTLE}; margin: 4px 8px; }}
        """)
        profile_action = menu.addAction("Profil")
        menu.addSeparator()
        logout_action = menu.addAction("Cikis Yap")
        selected = menu.exec(self._account_button.mapToGlobal(self._account_button.rect().bottomLeft()))
        if selected == profile_action:
            self._show_profile_dialog()
        elif selected == logout_action:
            self._on_logout()

    def _show_profile_dialog(self):
        lines = []
        if self._user_email:
            lines.append(f"E-posta:  {self._user_email}")
        lines.append(f"Ad:  {_display_username(self._username)}")
        if self._user_address:
            lines.append(f"Bu bilgisayarin adresi:  {_format_address(self._user_address)}")
        lines.append(f"Bilgisayar:  {_desktop_device_name()}")
        QMessageBox.information(self, "Profil", "\n".join(lines))

    # ── Card actions ─────────────────────────────────────────────────────────
    def _on_card_connect(self, card_key: str):
        card = self._device_cards.get(card_key)
        if not card:
            return
        address = card.connection_address()
        if not card.is_online():
            self._set_status("Bu cihaz su an cevrimici degil.", error=True)
            return
        if address:
            self._inp_code.setText(address)
            self._inp_code.setFocus()
            self._paired_phone_address = _address_digits(address)
        self._paired_phone_id = card.device_id
        display_name = _compact_label(card.display_name(), 20)
        self._remote_device_badge.setText(f"Baglaniyor: {display_name}")
        self._tab_session_btn.setText(f"  {display_name}")
        self._tab_session.show()
        self._switch_page(1)
        self._connect_session_mode(
            partner_device_id=None if address else card.device_id,
            partner_address=address,
            status_message="Secilen cihaza baglaniliyor...",
        )

    def _on_card_forget(self, card_key: str):
        card = self._device_cards.get(card_key)
        if not card:
            return
        answer = QMessageBox.question(
            self, "Eslesmeyi Kaldir",
            "Bu eslesme kaldirilsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        if not self._auth_token:
            self._set_status("Eslesmeyi sunucudan silmek icin yeniden giris yapin.", error=True)
            return

        success, error_message = self._backend_api.delete_pairing(
            self._auth_token,
            self._ws_client.device_id,
            card.device_id,
            card.address,
        )
        if not success:
            self._set_status(error_message or "Eslesme silinemedi.", error=True)
            return

        devices = self._load_paired_devices()
        self._populate_device_cards(devices)
        self._online_paired_devices.discard(str(card.device_id))

        if self._paired_phone_address == card.address or self._paired_phone_id == card.device_id:
            self._paired_phone_id = None
            self._paired_phone_address = None
            clear_paired_phone_address()
            clear_paired_phone_id()
            self._ws_client.forget_paired_phone()
            self._on_disconnect()
            return

        self._ws_client.send_request_presence()
        self._refresh_home_summary()
        self._set_status("Eslesme kaldirildi.")

    def _connect_presence_channel(self, status_message: str | None = None):
        self._connect_presence_mode(status_message)

    def _on_presence_tick(self):
        self._ws_client.send_request_presence()

    # ── Connect button ───────────────────────────────────────────────────────
    def _submit_static_address(self, raw_value: str) -> None:
        if not raw_value:
            self._set_status("Adres girilmedi.", error=True)
            return
        if not raw_value.isdigit():
            self._set_status("Adres sadece rakam olmali.", error=True)
            return
        if len(raw_value) != 12:
            self._set_status("12 haneli sabit adresi girin.", error=True)
            return

        self._manual_disconnect = True
        self._btn_connect.setEnabled(False)
        self._btn_remote_connect.setEnabled(False)
        self._set_status("Cihaz adresine baglaniliyor...")
        matching_card = next(
            (card for card in self._device_cards.values() if (card.connection_address() or "") == _format_address(raw_value)),
            None,
        )
        self._paired_phone_id = matching_card.device_id if matching_card else None
        self._paired_phone_address = raw_value
        save_paired_phone_address(raw_value)
        display_name = None
        if matching_card:
            display_name = _compact_label(matching_card.display_name(), 20)
        self._remote_device_badge.setText(f"Baglaniyor: {display_name or 'cihaz'}")
        self._tab_session_btn.setText(f"  {display_name or 'Baglaniyor'}")
        self._tab_session.show()
        self._switch_page(1)
        self._connect_session_mode(
            partner_device_id=self._paired_phone_id,
            partner_address=raw_value,
            status_message="Cihaz adresine baglaniliyor...",
        )
        self._refresh_home_summary()

    @pyqtSlot()
    def _on_connect(self):
        self._submit_static_address("".join(ch for ch in self._inp_code.text() if ch.isdigit()))

    @pyqtSlot()
    def _on_remote_connect(self):
        self._submit_static_address("".join(ch for ch in self._inp_remote_code.text() if ch.isdigit()))

    @pyqtSlot(str)
    def _on_address_text_changed(self, text: str):
        digits = "".join(ch for ch in text if ch.isdigit())[:12]
        formatted = _format_address(digits)
        if text != formatted:
            old_cursor = self._inp_code.cursorPosition()
            digit_pos = _digits_before_cursor(text, old_cursor)
            self._inp_code.blockSignals(True)
            self._inp_code.setText(formatted)
            self._inp_code.blockSignals(False)
            new_cursor = _cursor_for_digit_count(formatted, digit_pos)
            self._inp_code.setCursorPosition(new_cursor)

    @pyqtSlot(str)
    def _on_remote_address_text_changed(self, text: str):
        digits = "".join(ch for ch in text if ch.isdigit())[:12]
        formatted = _format_address(digits)
        if text != formatted:
            old_cursor = self._inp_remote_code.cursorPosition()
            digit_pos = _digits_before_cursor(text, old_cursor)
            self._inp_remote_code.blockSignals(True)
            self._inp_remote_code.setText(formatted)
            self._inp_remote_code.blockSignals(False)
            new_cursor = _cursor_for_digit_count(formatted, digit_pos)
            self._inp_remote_code.setCursorPosition(new_cursor)

    @pyqtSlot()
    def _on_disconnect(self):
        self._ws_mode = "presence"
        self._reconnect_timer.stop()
        self._manual_disconnect = True
        self._mjpeg.stop()
        self._ws_client.disconnect()
        self._screen.clear_frame()
        self._set_connected(False)
        self._switch_page(0)
        for card in self._device_cards.values():
            card.set_online(False)
        QTimer.singleShot(150, lambda: self._connect_presence_channel("Cihaz durumu izleniyor..."))

    @pyqtSlot()
    def _on_logout(self):
        if self._logging_out:
            return
        self._logging_out = True

        self._mjpeg.stop()
        self._heartbeat.stop()
        self._presence_timer.stop()
        self._manual_disconnect = True
        self._ws_client.disconnect(send_logout=True)
        self._screen.clear_frame()
        clear_logged_in()
        clear_paired_phone_id()

        from desktop_app.ui.login_window import LoginWindow

        self.hide()
        new_db = DbClient()
        login = LoginWindow(new_db)
        if login.exec() == QDialog.DialogCode.Accepted:
            replacement = MainWindow(new_db)
            app = QApplication.instance()
            if app is not None:
                setattr(app, "_rpc_main_window", replacement)
            replacement.show()
            self.close()
        else:
            new_db.close()
            app = QApplication.instance()
            self.close()
            if app is not None:
                app.quit()
            return
        self._logging_out = False

    # ── WS slots ─────────────────────────────────────────────────────────────
    @pyqtSlot()
    def _on_ws_connected(self):
        self._manual_disconnect = False
        self._set_status(Ui.MSG_SERVER_CONNECTED)
        self._btn_disconnect.setEnabled(True)
        if not self._presence_timer.isActive():
            self._presence_timer.start()
        if self._ws_mode == "presence":
            devices = self._load_paired_devices()
            if devices:
                self._populate_device_cards(devices)
            self._ws_client.send_request_presence()

    @pyqtSlot(str)
    def _on_ws_disconnected(self, reason: str):
        was_manual = self._manual_disconnect
        self._manual_disconnect = False
        self._btn_connect.setEnabled(True)
        self._btn_remote_connect.setEnabled(True)
        if was_manual:
            return
        self._set_connected(False)
        self._switch_page(0)
        self._screen.clear_frame()
        self._presence_timer.stop()
        self._reconnect_timer.stop()
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
        self._schedule_reconnect()

    @pyqtSlot(str)
    def _on_paired(self, stream_url: str):
        self._reconnect_timer.stop()
        paired_phone_id = load_paired_phone_id()
        paired_phone_address = load_paired_phone_address()
        if paired_phone_id or paired_phone_address:
            pid = str(paired_phone_id) if paired_phone_id else ""
            addr = _address_digits(paired_phone_address) if paired_phone_address else ""
            missing = (pid and pid not in self._device_cards) or (
                bool(addr) and not any(c.address == addr for c in self._device_cards.values())
            )
            if missing:
                devices = self._load_paired_devices()
                self._populate_device_cards(devices)
            card = self._device_cards.get(pid) if pid else None
            if card is None and addr:
                card = next((c for c in self._device_cards.values() if c.address == addr), None)
            if card is None and paired_phone_id:
                card = self._card_for_member_device(paired_phone_id)
            if card:
                self._paired_phone_id = card.device_id
                self._paired_phone_address = card.address
                card.set_online(True)
        self._set_connected(True)
        self._switch_page(1)
        self._set_status("Eslesme tamamlandi. Akis bekleniyor...")
        self._refresh_home_summary()
        if stream_url and stream_url.startswith("http") and "0.0.0.0" not in stream_url and "10.0.2." not in stream_url:
            try:
                self._mjpeg.start(stream_url)
                self._set_status("Baglandi — video akisi aktif.")
                return
            except Exception:
                logger.exception("MJPEG akisi baslatilamadi")
        self._set_status(Ui.MSG_PAIRED_WS)

    @pyqtSlot(list, list)
    def _on_paired_devices_status(self, paired_devices: list, online_devices: list):
        online_set = {d for x in (online_devices or []) if (d := _address_digits(str(x)))}
        incoming_paired = {d for x in (paired_devices or []) if (d := _address_digits(str(x)))}

        if self._auth_token:
            current_keys = {_address_digits(k) for k in self._device_cards.keys() if _address_digits(k)}
            if incoming_paired != current_keys or not self._device_cards:
                devices = self._load_paired_devices()
                self._populate_device_cards(devices)
            self._online_paired_devices.clear()
            for key, card in self._device_cards.items():
                ck = _address_digits(key)
                on = bool(ck) and ck in online_set
                card.set_online(on)
                if on:
                    self._online_paired_devices.add(key)
            self._reflow_device_cards()
            online_count = len(self._online_paired_devices)
            self._lbl_device_count.setText(
                f"{online_count} aktif / {len(self._device_cards)} cihaz" if self._device_cards else ""
            )
        else:
            current_ids = {_address_digits(k) for k in self._device_cards.keys() if _address_digits(k)}
            if incoming_paired != current_ids:
                devices = self._load_paired_devices()
                self._populate_device_cards(devices)

            self._online_paired_devices.clear()
            for ck_raw, card in self._device_cards.items():
                ck = _address_digits(ck_raw)
                on = bool(ck) and ck in online_set
                card.set_online(on)
                if on:
                    self._online_paired_devices.add(ck_raw)

            self._reflow_device_cards()
            online_count = sum(1 for c in self._device_cards.values() if c.is_online())
            self._lbl_device_count.setText(
                f"{online_count} aktif / {len(self._device_cards)} cihaz" if self._device_cards else ""
            )
        if not self._connected:
            online_count = sum(1 for card in self._device_cards.values() if card._online)
            if online_count:
                self._set_status(f"Sunucuya baglandi  —  {online_count} cihaz cevrimici")
            else:
                self._set_status(Ui.MSG_SERVER_CONNECTED)
        self._refresh_home_summary()

    @pyqtSlot()
    def _on_peer_disconnected(self):
        self._ws_mode = "presence"
        self._mjpeg.stop()
        self._screen.clear_frame()
        self._set_connected(False)
        self._switch_page(0)
        if self._auth_token:
            devices = self._load_paired_devices()
            self._populate_device_cards(devices)
        else:
            pid = str(self._paired_phone_id) if self._paired_phone_id else ""
            if pid and pid in self._device_cards:
                self._device_cards[pid].set_online(False)
            self._online_paired_devices.discard(pid)
        self._refresh_home_summary()
        self._ws_client.send_request_presence()
        self._set_status(Ui.MSG_PEER_DISCONNECTED, error=True)

    @pyqtSlot(str, str)
    def _on_error(self, msg: str, code: str = ""):
        text = (msg or "").strip()
        if _is_accessibility_ws_error(text, code):
            banner_title = "Erisilebilirlik kapali"
            banner_body = text or "Telefonda Erisilebilirlik servisini acmadan baglanti baslatilamaz."

            def _apply_banner() -> None:
                self._show_warning_banner(banner_title, banner_body)
                self._switch_page(0)

            QTimer.singleShot(0, _apply_banner)
        self._set_status(f"Hata: {msg}", error=True)

    @pyqtSlot(QPixmap)
    def _on_frame_received(self, pixmap: QPixmap):
        if not self._connected:
            self._set_connected(True)
            self._switch_page(1)
            self._set_status(Ui.MSG_PAIRED_WS)
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

    # ── State helpers ────────────────────────────────────────────────────────
    def _set_connected(self, connected: bool):
        self._connected = connected
        self._btn_connect.setEnabled(not connected)
        self._btn_remote_connect.setEnabled(not connected)
        self._remote_pair_row.setVisible(not connected)
        self._btn_disconnect.setEnabled(connected)
        self._btn_rotate.setEnabled(connected)
        for btn in self._key_buttons:
            btn.setEnabled(connected)
        if connected:
            self._hide_warning_banner()
            self._heartbeat.start()
            self._header_status_dot.setStyleSheet(f"background-color: {_GREEN}; border-radius: 4px;")
        else:
            self._heartbeat.stop()
            self._header_status_dot.setStyleSheet(f"background-color: {_TEXT_DIM}; border-radius: 4px;")
        self._refresh_home_summary()

    def _set_status(self, msg: str, error: bool = False):
        color = _RED if error else _TEXT_SEC
        self._status_bar.setStyleSheet(
            f"QStatusBar {{ background-color: {_BG}; border-top: 1px solid {_BORDER_SUBTLE};"
            f" color: {color}; font-size: 11px; padding: 2px 14px; }}"
        )
        self._status_bar.showMessage(msg)

    def closeEvent(self, event):
        self._mjpeg.stop()
        self._heartbeat.stop()
        self._presence_timer.stop()
        self._reconnect_timer.stop()
        self._manual_disconnect = True
        self._ws_client.disconnect()
        self.db.close()
        super().closeEvent(event)
