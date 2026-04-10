import logging
import os

from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QPoint
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QMenu,
    QApplication,
    QDialog,
    QDialogButtonBox,
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


def _ws_device_id_set(items: list | None) -> set[str]:
    """device_ack listeleri tam device_id; 12 hane kirpmasi REST yenilemeyi surekli tetikler."""
    return {str(x).strip() for x in (items or []) if str(x).strip()}


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
    def __init__(self, db: DbClient, backend_api: BackendApi | None = None):
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
        self._phone_accessibility_enabled: bool | None = None
        self._remote_frame_visible = False
        self._logging_out = False
        self._manual_disconnect = False
        self._ws_mode = "idle"
        self._user_id: int | None = None
        self._username = "Kullanici"
        self._user_email = ""
        self._user_first_name = ""
        self._user_last_name = ""
        self._user_address = ""
        self._auth_token = ""
        self._current_page = 0
        self._account_button: QPushButton | None = None
        self._backend_api = backend_api if backend_api is not None else BackendApi()
        self._reconnect_session_code: str | None = None
        self._profile_drawer_open = False
        self._profile_drawer_width = 432
        self._profile_cache: dict = {}
        self._profile_anim: QPropertyAnimation | None = None

        self.setWindowTitle(AppMeta.WINDOW_TITLE)
        self.setMinimumSize(960, 600)
        self.resize(1060, 700)
        self._load_user_prefs()
        self._apply_global_style()
        self._build_ui()
        self._connect_signals()

        self._presence_timer = QTimer(self)
        self._presence_timer.setInterval(8_000)
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
        self._user_first_name = (prefs.get(Prefs.KEY_USER_FIRST_NAME) or "").strip()
        self._user_last_name = (prefs.get(Prefs.KEY_USER_LAST_NAME) or "").strip()
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
                fn = (profile.get("first_name") or "").strip()
                ln = (profile.get("last_name") or "").strip()
                if fn or ln:
                    self._user_first_name = fn
                    self._user_last_name = ln
                    update_prefs(**{Prefs.KEY_USER_FIRST_NAME: fn, Prefs.KEY_USER_LAST_NAME: ln})
        if not self._user_address and self._user_id:
            self._user_address = self.db.get_user_address(self._user_id) or ""
        if not self._user_email:
            self._user_email = self._username
        self._ws_client.set_device_address(self._user_address)

    def _load_paired_devices(self) -> list[dict]:
        merged: dict[str, dict] = {}
        pc_id = self._ws_client.device_id

        def _ingest_phone_rows(rows: list[dict] | None) -> None:
            for device in rows or []:
                if device.get("device_type") != "phone" or device.get("device_id") == pc_id:
                    continue
                key = _phone_row_key(device)
                if not key:
                    continue
                merged[key] = _merge_phone_device_row(merged.get(key, {}), dict(device))

        if self._auth_token:
            bundle, bundle_err = self._backend_api.get_phone_device_bundle(self._auth_token, pc_id)
            if bundle and bundle.get("ok"):
                _ingest_phone_rows(list(bundle.get("devices") or []))
                _ingest_phone_rows(list(bundle.get("recent_devices") or []))
                _ingest_phone_rows(list(bundle.get("pairings") or []))
                if merged:
                    return list(merged.values())
                return self.db.get_paired_devices(pc_id)
            if bundle_err and bundle_err != "bundle_missing":
                logger.warning("phone-bundle alinamadi: %s", bundle_err)

            devices, devices_error = self._backend_api.get_devices(self._auth_token)
            if devices is not None:
                _ingest_phone_rows(devices)
            else:
                logger.warning("Server devices alinamadi: %s", devices_error)

            recent_devices, recent_error = self._backend_api.get_recent_devices(self._auth_token, "phone")
            if recent_devices is not None:
                _ingest_phone_rows(recent_devices)
            else:
                logger.warning("Server recent devices alinamadi: %s", recent_error)

            pairings, pairings_error = self._backend_api.get_pairings(self._auth_token, pc_id)
            if pairings is not None:
                _ingest_phone_rows(pairings)
            else:
                logger.warning("Server pairings alinamadi: %s", pairings_error)

            if merged:
                return list(merged.values())
        return self.db.get_paired_devices(pc_id)

    def _connect_presence_mode(self, status_message: str | None = None):
        if self._logging_out:
            return
        if self._ws_mode == "session" and self._connected:
            logger.info("Presence baglantisi atlandi: aktif uzak oturum korunuyor")
            return
        self._ws_mode = "presence"
        self._mjpeg.stop()
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
        self._mjpeg.stop()
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
        code = self._reconnect_session_code
        self._reconnect_session_code = None
        if code and len(code) == 12:
            logger.info("Yeniden baglanti: oturum kodu ile (presence yerine)")
            self._connect_session_mode(
                partner_device_id=self._paired_phone_id,
                partner_address=code,
                status_message="Oturum yeniden kuruluyor...",
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

        # Sağdan açılan profil sekmesi (drawer)
        self._profile_drawer = self._build_profile_drawer(central)
        self._profile_drawer.hide()

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

        display_name = f"{self._user_first_name} {self._user_last_name}".strip()
        if not display_name:
            display_name = self._user_email or _display_username(self._username)
        info_user = QLabel(f"  {display_name}")
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
        self._ws_client.frame_received.connect(
            self._on_frame_received,
            Qt.ConnectionType.QueuedConnection,
        )
        self._mjpeg.frame_ready.connect(self._on_mjpeg_frame)
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
        if self._ws_mode == "session":
            logger.debug("Cihaz listesi guncellendi; uzak oturum varken presence WS acilmadi")
            return
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
            acct = (f"{self._user_first_name} {self._user_last_name}".strip() or self._user_email or self._username)
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
            self._open_profile_drawer()
        elif selected == logout_action:
            self._on_logout()

    def _show_profile_modal(self) -> None:
        if not self._auth_token:
            self._set_status("Profil icin yeniden giris yapin.", error=True)
            return

        profile, err = self._backend_api.get_me(self._auth_token, self._ws_client.device_id)
        if err:
            self._set_status(err, error=True)
        p = dict(profile or {})
        # fallback yerel
        if not p.get("email") and self._user_email:
            p["email"] = self._user_email
        if not p.get("first_name") and self._user_first_name:
            p["first_name"] = self._user_first_name
        if not p.get("last_name") and self._user_last_name:
            p["last_name"] = self._user_last_name

        dlg = QDialog(self)
        dlg.setWindowTitle("Profil")
        dlg.setModal(True)
        dlg.setMinimumWidth(540)
        dlg.setStyleSheet(f"""
            QDialog {{ background-color: {_BG}; }}
            QLabel {{ background: transparent; }}
        """)

        root = QVBoxLayout(dlg)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Header card
        card = QFrame()
        card.setStyleSheet(f"background-color: {_BG_CARD}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 14px;")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(14)

        fn = str(p.get("first_name") or "").strip()
        ln = str(p.get("last_name") or "").strip()
        em = str(p.get("email") or "").strip()
        ph = str(p.get("phone") or "").strip()
        full = f"{fn} {ln}".strip() or "Kullanici"

        avatar = QLabel(self._profile_initials(fn, ln, em))
        avatar.setFixedSize(64, 64)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"background-color: {_ACCENT}; color: white; border-radius: 32px;"
            f" font-size: 20px; font-weight: 900;"
        )
        cl.addWidget(avatar)

        meta_col = QVBoxLayout()
        meta_col.setSpacing(4)
        lbl_name = QLabel(full)
        lbl_name.setStyleSheet(f"color: {_TEXT}; font-size: 18px; font-weight: 800;")
        meta_col.addWidget(lbl_name)
        lbl_email = QLabel(em or "—")
        lbl_email.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 13px;")
        meta_col.addWidget(lbl_email)
        lbl_phone = QLabel(ph or "—")
        lbl_phone.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
        meta_col.addWidget(lbl_phone)
        meta_col.addStretch()
        cl.addLayout(meta_col, stretch=1)
        root.addWidget(card)

        # Edit panel
        edit = QFrame()
        edit.setStyleSheet(f"background-color: {_BG_RAISED}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 14px;")
        el = QVBoxLayout(edit)
        el.setContentsMargins(16, 14, 16, 14)
        el.setSpacing(10)

        section = QLabel("Hesabi duzenle")
        section.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px; font-weight: 800; letter-spacing: 0.08em;")
        el.addWidget(section)

        ro = QLabel("Ad ve soyad (degistirilemez)")
        ro.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px; font-weight: 600;")
        el.addWidget(ro)
        ro_box = QLabel(full)
        ro_box.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 13px; padding: 10px 12px;"
            f" background-color: {_BG_INPUT}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 8px;"
        )
        el.addWidget(ro_box)

        def _field(title: str) -> QLabel:
            l = QLabel(title)
            l.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px; font-weight: 600;")
            return l

        inp_email = QLineEdit(em)
        inp_email.setFixedHeight(38)
        inp_email.setStyleSheet(line_edit_style())
        el.addWidget(_field("E-posta"))
        el.addWidget(inp_email)

        inp_phone = QLineEdit(ph)
        inp_phone.setFixedHeight(38)
        inp_phone.setStyleSheet(line_edit_style())
        el.addWidget(_field("Telefon"))
        el.addWidget(inp_phone)

        pw_section = QLabel("Sifre degistir")
        pw_section.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px; font-weight: 800; letter-spacing: 0.08em;")
        el.addWidget(pw_section)

        inp_pw1 = QLineEdit()
        inp_pw1.setEchoMode(QLineEdit.EchoMode.Password)
        inp_pw1.setFixedHeight(38)
        inp_pw1.setStyleSheet(line_edit_style())
        el.addWidget(_field("Yeni sifre"))
        el.addWidget(inp_pw1)

        inp_pw2 = QLineEdit()
        inp_pw2.setEchoMode(QLineEdit.EchoMode.Password)
        inp_pw2.setFixedHeight(38)
        inp_pw2.setStyleSheet(line_edit_style())
        el.addWidget(_field("Yeni sifre (tekrar)"))
        el.addWidget(inp_pw2)

        hint = QLabel("Bos birakirsaniz sifre degismez. Degistirmek icin iki alani da ayni girin.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px;")
        el.addWidget(hint)

        err_lbl = QLabel("")
        err_lbl.setWordWrap(True)
        err_lbl.setStyleSheet(f"color: {_RED}; font-size: 12px;")
        err_lbl.hide()
        el.addWidget(err_lbl)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgec")
        btns.button(QDialogButtonBox.StandardButton.Save).setText("Kaydet")
        btns.setStyleSheet("QDialogButtonBox { background: transparent; }")
        el.addWidget(btns)

        def _on_save():
            err_lbl.hide()
            err_lbl.setText("")
            new_em = inp_email.text().strip().lower()
            if not new_em or "@" not in new_em or len(new_em) < 5:
                err_lbl.setText("Gecerli bir e-posta girin.")
                err_lbl.show()
                return
            new_phone = inp_phone.text().strip()
            p1 = inp_pw1.text()
            p2 = inp_pw2.text()
            if p1 or p2:
                if not p1 or not p2:
                    err_lbl.setText("Sifre iki kere girilmelidir.")
                    err_lbl.show()
                    return
                if p1 != p2:
                    err_lbl.setText("Sifreler eslesmiyor.")
                    err_lbl.show()
                    return
                if len(p1) < 6:
                    err_lbl.setText("Sifre en az 6 karakter olmali.")
                    err_lbl.show()
                    return

            data, api_err = self._backend_api.update_profile(
                self._auth_token,
                email=new_em,
                phone=new_phone,
                password=p1 if (p1 or p2) else None,
                password2=p2 if (p1 or p2) else None,
            )
            if api_err:
                err_lbl.setText(api_err)
                err_lbl.show()
                return

            user = (data or {}).get("user") or {}
            token = str((data or {}).get("token") or "")
            if token:
                self._auth_token = token
                update_prefs(**{Prefs.KEY_AUTH_TOKEN: token})
            new_email = str(user.get("email") or new_em).strip().lower()
            update_prefs(**{Prefs.KEY_USER_EMAIL: new_email})
            self._user_email = new_email
            fn2 = str(user.get("first_name") or fn).strip()
            ln2 = str(user.get("last_name") or ln).strip()
            self._user_first_name = fn2
            self._user_last_name = ln2
            update_prefs(**{Prefs.KEY_USER_FIRST_NAME: fn2, Prefs.KEY_USER_LAST_NAME: ln2})
            self._refresh_home_summary()
            self._set_status("Profil guncellendi.")
            dlg.accept()

        btns.accepted.connect(_on_save)
        btns.rejected.connect(dlg.reject)
        root.addWidget(edit)

        dlg.exec()

    # ── Profil Drawer ────────────────────────────────────────────────────────
    def _build_profile_drawer(self, parent: QWidget) -> QFrame:
        drawer = QFrame(parent)
        drawer.setObjectName("profile_drawer")
        drawer.setStyleSheet(
            f"QFrame#profile_drawer {{ background-color: {_BG_RAISED}; border-left: 1px solid {_BORDER_SUBTLE}; }}"
        )
        drawer.setFixedWidth(self._profile_drawer_width)

        root = QVBoxLayout(drawer)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(0)

        header = QHBoxLayout()
        title = QLabel("Profil")
        title.setStyleSheet(f"color: {_TEXT}; font-size: 16px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()

        btn_close = QPushButton("Kapat")
        btn_close.setFixedHeight(28)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet(outline_button_style())
        btn_close.clicked.connect(self._close_profile_drawer)
        header.addWidget(btn_close)
        root.addLayout(header)

        hint = QLabel("Hesap özeti ve iletişim bilgileri.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px; margin-top: 6px;")
        root.addWidget(hint)

        self._profile_load_err = QLabel("")
        self._profile_load_err.setWordWrap(True)
        self._profile_load_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
        self._profile_load_err.hide()
        root.addWidget(self._profile_load_err)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 14, 0, 8)
        lay.setSpacing(14)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        def _field_lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px; font-weight: 600;")
            return l

        def _section_lbl(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: 600;")
            return l

        card_css = (
            f"QFrame {{ background-color: {_BG_INPUT}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px; }}"
        )

        # — Hesap kartı
        account_card = QFrame()
        account_card.setStyleSheet(card_css)
        summary_lay = QVBoxLayout(account_card)
        summary_lay.setContentsMargins(14, 12, 14, 14)
        summary_lay.setSpacing(12)

        summary_lay.addWidget(_section_lbl("Hesap"))

        head_row = QHBoxLayout()
        head_row.setSpacing(12)
        self._profile_avatar_lbl = QLabel("")
        self._profile_avatar_lbl.setFixedSize(40, 40)
        self._profile_avatar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._profile_avatar_lbl.setStyleSheet(
            f"QLabel {{ background-color: {_BG_RAISED}; color: {_TEXT_SEC}; font-size: 13px; font-weight: 700;"
            f" border: 1px solid {_BORDER_SUBTLE}; border-radius: 8px; }}"
        )
        head_row.addWidget(self._profile_avatar_lbl, alignment=Qt.AlignmentFlag.AlignTop)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._profile_view_name = QLabel("")
        self._profile_view_name.setWordWrap(True)
        self._profile_view_name.setStyleSheet(f"color: {_TEXT}; font-size: 15px; font-weight: 600;")
        title_col.addWidget(self._profile_view_name)
        acc_lbl = QLabel("Kayıtlı kullanıcı")
        acc_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px;")
        title_col.addWidget(acc_lbl)
        head_row.addLayout(title_col, stretch=1)
        summary_lay.addLayout(head_row)

        sep1 = QFrame()
        sep1.setFixedHeight(1)
        sep1.setStyleSheet(f"background-color: {_BORDER_SUBTLE}; border: none;")
        summary_lay.addWidget(sep1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnMinimumWidth(0, 100)
        grid.setColumnStretch(1, 1)

        def _grid_key(t: str) -> QLabel:
            w = QLabel(t)
            w.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px;")
            w.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            return w

        def _grid_val() -> QLabel:
            w = QLabel("")
            w.setWordWrap(True)
            w.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            w.setStyleSheet(f"color: {_TEXT}; font-size: 13px;")
            return w

        grid.addWidget(_grid_key("E-posta"), 0, 0)
        self._profile_view_email = _grid_val()
        grid.addWidget(self._profile_view_email, 0, 1)

        grid.addWidget(_grid_key("Telefon"), 1, 0)
        self._profile_view_phone = _grid_val()
        grid.addWidget(self._profile_view_phone, 1, 1)

        summary_lay.addLayout(grid)
        lay.addWidget(account_card)

        lay.addWidget(_section_lbl("İşlemler"))

        ops_col = QVBoxLayout()
        ops_col.setSpacing(8)
        self._profile_action_edit = QPushButton("Bilgileri düzenle…")
        self._profile_action_edit.setMinimumHeight(38)
        self._profile_action_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._profile_action_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        self._profile_action_edit.setStyleSheet(filled_button_style())
        self._profile_action_edit.clicked.connect(lambda: self._set_profile_panel("edit"))
        ops_col.addWidget(self._profile_action_edit)

        self._profile_action_pwd = QPushButton("Şifre değiştir…")
        self._profile_action_pwd.setMinimumHeight(38)
        self._profile_action_pwd.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._profile_action_pwd.setCursor(Qt.CursorShape.PointingHandCursor)
        self._profile_action_pwd.setStyleSheet(outline_button_style())
        self._profile_action_pwd.clicked.connect(lambda: self._set_profile_panel("password"))
        ops_col.addWidget(self._profile_action_pwd)
        lay.addLayout(ops_col)

        # — Düzenleme kartı (email/telefon)
        self._profile_edit_block = QFrame()
        self._profile_edit_block.setStyleSheet(
            f"QFrame {{ background-color: {_BG_INPUT}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 4px; }}"
        )
        edit_lay = QVBoxLayout(self._profile_edit_block)
        edit_lay.setContentsMargins(14, 14, 14, 14)
        edit_lay.setSpacing(8)

        edit_lay.addWidget(_section_lbl("İletişim bilgileri"))

        edit_lay.addWidget(_field_lbl("Ad ve soyad (salt okunur)"))
        self._profile_readonly_name = QLabel("")
        self._profile_readonly_name.setWordWrap(True)
        self._profile_readonly_name.setMinimumHeight(32)
        self._profile_readonly_name.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 12px; padding: 8px 10px;"
            f" background-color: {_BG_INPUT}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
        )
        edit_lay.addWidget(self._profile_readonly_name)

        cap = QLabel("Kayıt sırasında belirlenir; buradan değiştirilemez.")
        cap.setWordWrap(True)
        cap.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px;")
        edit_lay.addWidget(cap)

        self._profile_inp_email = QLineEdit()
        self._profile_inp_email.setFixedHeight(34)
        self._profile_inp_email.setStyleSheet(line_edit_style())
        edit_lay.addWidget(_field_lbl("E-posta"))
        edit_lay.addWidget(self._profile_inp_email)

        self._profile_inp_phone = QLineEdit()
        self._profile_inp_phone.setFixedHeight(34)
        self._profile_inp_phone.setStyleSheet(line_edit_style())
        edit_lay.addWidget(_field_lbl("Telefon"))
        edit_lay.addWidget(self._profile_inp_phone)

        self._profile_err = QLabel("")
        self._profile_err.setWordWrap(True)
        self._profile_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
        edit_lay.addWidget(self._profile_err)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._profile_btn_cancel = QPushButton("Vazgeç")
        self._profile_btn_cancel.setFixedHeight(36)
        self._profile_btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._profile_btn_cancel.setStyleSheet(outline_button_style())
        self._profile_btn_cancel.clicked.connect(self._on_profile_cancel)
        btn_row.addWidget(self._profile_btn_cancel)
        self._profile_btn_save = QPushButton("Kaydet")
        self._profile_btn_save.setFixedHeight(36)
        self._profile_btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._profile_btn_save.setStyleSheet(filled_button_style())
        self._profile_btn_save.clicked.connect(self._save_profile_from_drawer)
        btn_row.addWidget(self._profile_btn_save)
        edit_lay.addLayout(btn_row)

        lay.addWidget(self._profile_edit_block)
        self._profile_edit_block.hide()

        # — Şifre kartı (eski/yeni/yeni2)
        self._profile_pwd_block = QFrame()
        self._profile_pwd_block.setStyleSheet(
            f"QFrame {{ background-color: {_BG_INPUT}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 4px; }}"
        )
        pw_lay = QVBoxLayout(self._profile_pwd_block)
        pw_lay.setContentsMargins(14, 14, 14, 14)
        pw_lay.setSpacing(8)
        pw_lay.addWidget(_section_lbl("Şifre değiştirme"))

        self._profile_inp_old = QLineEdit()
        self._profile_inp_old.setFixedHeight(34)
        self._profile_inp_old.setEchoMode(QLineEdit.EchoMode.Password)
        self._profile_inp_old.setStyleSheet(line_edit_style())
        pw_lay.addWidget(_field_lbl("Mevcut şifre"))
        pw_lay.addWidget(self._profile_inp_old)

        self._profile_inp_pwd1 = QLineEdit()
        self._profile_inp_pwd1.setFixedHeight(34)
        self._profile_inp_pwd1.setEchoMode(QLineEdit.EchoMode.Password)
        self._profile_inp_pwd1.setStyleSheet(line_edit_style())
        pw_lay.addWidget(_field_lbl("Yeni şifre"))
        pw_lay.addWidget(self._profile_inp_pwd1)

        self._profile_inp_pwd2 = QLineEdit()
        self._profile_inp_pwd2.setFixedHeight(34)
        self._profile_inp_pwd2.setEchoMode(QLineEdit.EchoMode.Password)
        self._profile_inp_pwd2.setStyleSheet(line_edit_style())
        pw_lay.addWidget(_field_lbl("Yeni şifre (tekrar)"))
        pw_lay.addWidget(self._profile_inp_pwd2)

        self._profile_pwd_err = QLabel("")
        self._profile_pwd_err.setWordWrap(True)
        self._profile_pwd_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
        pw_lay.addWidget(self._profile_pwd_err)

        pw_btn = QHBoxLayout()
        pw_btn.setSpacing(8)
        self._profile_pwd_cancel = QPushButton("Vazgeç")
        self._profile_pwd_cancel.setFixedHeight(36)
        self._profile_pwd_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._profile_pwd_cancel.setStyleSheet(outline_button_style())
        self._profile_pwd_cancel.clicked.connect(self._on_profile_pwd_cancel)
        pw_btn.addWidget(self._profile_pwd_cancel)
        self._profile_pwd_save = QPushButton("Kaydet")
        self._profile_pwd_save.setFixedHeight(36)
        self._profile_pwd_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._profile_pwd_save.setStyleSheet(filled_button_style())
        self._profile_pwd_save.clicked.connect(self._save_password_from_drawer)
        pw_btn.addWidget(self._profile_pwd_save)
        pw_lay.addLayout(pw_btn)

        lay.addWidget(self._profile_pwd_block)
        self._profile_pwd_block.hide()

        lay.addStretch()
        return drawer

    def _open_profile_drawer(self) -> None:
        if not self._auth_token:
            self._set_status("Profil icin yeniden giris yapin.", error=True)
            return
        self._profile_err.setText("")

        # Sunucudan en güncel profil
        profile, err = self._backend_api.get_me(self._auth_token, self._ws_client.device_id)
        self._profile_cache = dict(profile) if profile else {}
        self._profile_load_err.hide()
        self._profile_load_err.setText("")
        if err:
            self._profile_load_err.setText(err)
            self._profile_load_err.show()
        if profile:
            fn = str(profile.get("first_name") or "").strip()
            ln = str(profile.get("last_name") or "").strip()
            em = str(profile.get("email") or self._user_email or "").strip()
            ph = str(profile.get("phone") or "").strip()
            full = f"{fn} {ln}".strip() or "—"
            self._profile_view_name.setText(full)
            self._profile_view_email.setText(em or "—")
            self._profile_view_phone.setText(ph or "—")
            self._profile_readonly_name.setText(full)
            self._profile_inp_email.setText(em)
            self._profile_inp_phone.setText(ph)
            self._profile_avatar_lbl.setText(self._profile_initials(fn, ln, em))
        else:
            fn, ln = self._user_first_name, self._user_last_name
            full = f"{fn} {ln}".strip() or "—"
            self._profile_view_name.setText(full)
            self._profile_view_email.setText(self._user_email or "—")
            self._profile_view_phone.setText("—")
            self._profile_readonly_name.setText(full)
            self._profile_inp_email.setText(self._user_email or "")
            self._profile_inp_phone.setText("")
            self._profile_avatar_lbl.setText(self._profile_initials(fn, ln, self._user_email))

        self._profile_inp_old.setText("")
        self._profile_inp_pwd1.setText("")
        self._profile_inp_pwd2.setText("")

        self._set_profile_drawer_open(True)
        self._set_profile_panel(None)

    @staticmethod
    def _profile_initials(first_name: str, last_name: str, email: str) -> str:
        a = (first_name or "").strip()[:1].upper()
        b = (last_name or "").strip()[:1].upper()
        if a and b:
            return f"{a}{b}"
        if a:
            return a
        em = (email or "").strip()
        return em[:1].upper() if em else "?"

    def _on_profile_cancel(self) -> None:
        self._profile_err.setText("")
        p = self._profile_cache
        if p:
            em = str(p.get("email") or "").strip()
            ph = str(p.get("phone") or "").strip()
            fn = str(p.get("first_name") or "").strip()
            ln = str(p.get("last_name") or "").strip()
        else:
            em = (self._user_email or "").strip()
            ph = ""
            fn = (self._user_first_name or "").strip()
            ln = (self._user_last_name or "").strip()
        self._profile_inp_email.setText(em)
        self._profile_inp_phone.setText(ph)
        self._profile_readonly_name.setText(f"{fn} {ln}".strip() or "—")
        self._profile_inp_pwd1.setText("")
        self._profile_inp_pwd2.setText("")
        self._set_profile_panel(None)

    def _on_profile_pwd_cancel(self) -> None:
        self._profile_pwd_err.setText("")
        self._profile_inp_old.setText("")
        self._profile_inp_pwd1.setText("")
        self._profile_inp_pwd2.setText("")
        self._set_profile_panel(None)

    def _set_profile_panel(self, which: str | None) -> None:
        # none => sadece özet
        self._profile_err.setText("")
        self._profile_pwd_err.setText("")
        self._profile_edit_block.setVisible(which == "edit")
        self._profile_pwd_block.setVisible(which == "password")
        # buton stilleri
        if which == "edit":
            self._profile_action_edit.setStyleSheet(filled_button_style())
            self._profile_action_pwd.setStyleSheet(outline_button_style())
        elif which == "password":
            self._profile_action_edit.setStyleSheet(outline_button_style())
            self._profile_action_pwd.setStyleSheet(filled_button_style())
        else:
            self._profile_action_edit.setStyleSheet(filled_button_style())
            self._profile_action_pwd.setStyleSheet(outline_button_style())

    def _close_profile_drawer(self) -> None:
        self._set_profile_drawer_open(False)

    def _set_profile_drawer_open(self, open_: bool) -> None:
        if self._profile_drawer_open == open_:
            return
        self._profile_drawer_open = open_

        # Parent alanı kaplaması için: yükseklik tam olsun
        parent = self.centralWidget()
        if parent is not None:
            self._profile_drawer.setFixedHeight(parent.height())

        if open_:
            self._profile_drawer.show()

        start_x = self.width() if open_ else (self.width() - self._profile_drawer_width)
        end_x = (self.width() - self._profile_drawer_width) if open_ else self.width()
        y = 0
        start_pos = QPoint(start_x, y)
        end_pos = QPoint(end_x, y)
        self._profile_drawer.move(start_pos)

        if self._profile_anim is not None:
            try:
                self._profile_anim.stop()
            except Exception:
                pass

        anim = QPropertyAnimation(self._profile_drawer, b"pos", self)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.setStartValue(start_pos)
        anim.setEndValue(end_pos)

        def _on_finished():
            if not self._profile_drawer_open:
                self._profile_drawer.hide()

        anim.finished.connect(_on_finished)
        self._profile_anim = anim
        anim.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Drawer açıksa sağa yapışık kalsın.
        if hasattr(self, "_profile_drawer"):
            if self._profile_drawer_open:
                self._profile_drawer.setFixedHeight(self.centralWidget().height() if self.centralWidget() else self.height())
                self._profile_drawer.move(self.width() - self._profile_drawer_width, 0)
            else:
                self._profile_drawer.move(self.width(), 0)

    def _save_profile_from_drawer(self) -> None:
        if not self._auth_token:
            self._profile_err.setText("Oturum bulunamadi. Tekrar giris yapin.")
            return
        em = self._profile_inp_email.text().strip().lower()
        if not em or "@" not in em or len(em) < 5:
            self._profile_err.setText("Gecerli bir e-posta girin.")
            return
        phone = self._profile_inp_phone.text().strip()

        data, err = self._backend_api.update_profile(
            self._auth_token,
            email=em,
            phone=phone,
            old_password=None,
            password=None,
            password2=None,
        )
        if err:
            self._profile_err.setText(err)
            return
        user = (data or {}).get("user") or {}
        token = str((data or {}).get("token") or "")
        if token:
            self._auth_token = token
            update_prefs(**{Prefs.KEY_AUTH_TOKEN: token})
        new_email = str(user.get("email") or em).strip().lower()
        self._user_email = new_email
        update_prefs(**{Prefs.KEY_USER_EMAIL: new_email})
        fn = str(user.get("first_name") or "").strip()
        ln = str(user.get("last_name") or "").strip()
        if fn or ln:
            self._user_first_name = fn
            self._user_last_name = ln
            update_prefs(**{Prefs.KEY_USER_FIRST_NAME: fn, Prefs.KEY_USER_LAST_NAME: ln})
        self._profile_cache = dict(user)
        full = f"{fn} {ln}".strip() or "—"
        ph_disp = str(user.get("phone") or phone or "").strip()
        self._profile_view_name.setText(full)
        self._profile_view_email.setText(new_email or "—")
        self._profile_view_phone.setText(ph_disp or "—")
        self._profile_readonly_name.setText(full)
        self._profile_avatar_lbl.setText(self._profile_initials(fn, ln, new_email))
        self._set_status("Profil guncellendi.")
        self._refresh_home_summary()
        self._close_profile_drawer()

    def _save_password_from_drawer(self) -> None:
        if not self._auth_token:
            self._profile_pwd_err.setText("Oturum bulunamadi. Tekrar giris yapin.")
            return
        oldp = self._profile_inp_old.text()
        p1 = self._profile_inp_pwd1.text()
        p2 = self._profile_inp_pwd2.text()
        if not oldp:
            self._profile_pwd_err.setText("Mevcut sifre gerekli.")
            return
        if not p1 or not p2:
            self._profile_pwd_err.setText("Yeni sifre iki kere girilmelidir.")
            return
        if p1 != p2:
            self._profile_pwd_err.setText("Yeni sifreler eslesmiyor.")
            return
        if len(p1) < 6:
            self._profile_pwd_err.setText("Sifre en az 6 karakter olmali.")
            return

        # mevcut email/phone korunur
        email = (self._profile_inp_email.text() or "").strip().lower() or (self._user_email or "")
        phone = (self._profile_inp_phone.text() or "").strip()
        data, err = self._backend_api.update_profile(
            self._auth_token,
            email=email,
            phone=phone,
            old_password=oldp,
            password=p1,
            password2=p2,
        )
        if err:
            self._profile_pwd_err.setText(err)
            return
        token = str((data or {}).get("token") or "")
        if token:
            self._auth_token = token
            update_prefs(**{Prefs.KEY_AUTH_TOKEN: token})
        self._set_status("Sifre guncellendi.")
        self._on_profile_pwd_cancel()

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
        self._reconnect_session_code = None
        self._reconnect_timer.stop()
        self._presence_timer.stop()
        self._manual_disconnect = True
        self._mjpeg.stop()
        self._ws_client.disconnect()
        self._screen.clear_frame()
        self._phone_accessibility_enabled = None
        self._remote_frame_visible = False
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
        self._presence_timer.stop()
        self._manual_disconnect = True
        self._ws_client.disconnect(send_logout=True)
        self._screen.clear_frame()
        self._phone_accessibility_enabled = None
        self._remote_frame_visible = False
        clear_logged_in()
        clear_paired_phone_id()

        from desktop_app.ui.login_window import LoginWindow

        self.hide()
        new_db = DbClient()
        login = LoginWindow(new_db)
        if login.exec() == QDialog.DialogCode.Accepted:
            replacement = MainWindow(new_db, backend_api=login.shared_backend_api)
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
        if self._ws_mode == "presence":
            if not self._presence_timer.isActive():
                self._presence_timer.start()
            devices = self._load_paired_devices()
            if devices:
                self._populate_device_cards(devices)
            self._ws_client.send_request_presence()
        else:
            self._presence_timer.stop()

    @pyqtSlot(str)
    def _on_ws_disconnected(self, reason: str):
        was_manual = self._manual_disconnect
        was_remote_session = self._ws_mode == "session" and self._connected
        restore_digits = ""
        if was_remote_session and not was_manual:
            restore_digits = _address_digits(self._paired_phone_address or "")
            if len(restore_digits) != 12:
                restore_digits = _address_digits(load_paired_phone_address() or "")
            if len(restore_digits) != 12:
                restore_digits = _address_digits(self._ws_client.join_session_code or "")
        if was_remote_session and not was_manual and len(restore_digits) == 12:
            self._reconnect_session_code = restore_digits
        else:
            self._reconnect_session_code = None
        self._manual_disconnect = False
        self._btn_connect.setEnabled(True)
        self._btn_remote_connect.setEnabled(True)
        if was_manual:
            return
        self._set_connected(False)
        self._switch_page(0)
        self._screen.clear_frame()
        self._phone_accessibility_enabled = None
        self._remote_frame_visible = False
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
        self._remote_frame_visible = False
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
        su = (stream_url or "").strip()
        su_lower = su.lower()
        mjpeg_unreachable = (
            not su.startswith("http")
            or "0.0.0.0" in su
            or "10.0.2." in su
            or "127.0.0.1" in su_lower
            or "localhost" in su_lower
        )
        if su and not mjpeg_unreachable:
            try:
                self._mjpeg.start(su)
                self._set_status("Baglandi — video akisi aktif.")
                return
            except Exception:
                logger.exception("MJPEG akisi baslatilamadi")
        QTimer.singleShot(700, self._request_phone_screen_capture)
        self._refresh_paired_stream_status()

    @pyqtSlot(list, list, object)
    def _on_paired_devices_status(self, paired_devices: list, online_devices: list, phone_a11y: object):
        online_ids = _ws_device_id_set(online_devices)
        incoming_paired_ids = _ws_device_id_set(paired_devices)

        if self._auth_token:
            current_ids = {str(k).strip() for k in self._device_cards.keys() if str(k).strip()}
            if incoming_paired_ids != current_ids or not self._device_cards:
                devices = self._load_paired_devices()
                self._populate_device_cards(devices)
            self._online_paired_devices.clear()
            for key, card in self._device_cards.items():
                ck = str(key).strip()
                on = bool(ck) and ck in online_ids
                card.set_online(on)
                if on:
                    self._online_paired_devices.add(key)
            self._reflow_device_cards()
            online_count = len(self._online_paired_devices)
            self._lbl_device_count.setText(
                f"{online_count} aktif / {len(self._device_cards)} cihaz" if self._device_cards else ""
            )
        else:
            current_ids = {str(k).strip() for k in self._device_cards.keys() if str(k).strip()}
            if incoming_paired_ids != current_ids:
                devices = self._load_paired_devices()
                self._populate_device_cards(devices)

            self._online_paired_devices.clear()
            for ck_raw, card in self._device_cards.items():
                ck = str(ck_raw).strip()
                on = bool(ck) and ck in online_ids
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
        if phone_a11y is not WsClient.PHONE_A11Y_UNCHANGED:
            self._phone_accessibility_enabled = None if phone_a11y is None else bool(phone_a11y)
        self._refresh_home_summary()
        if self._connected:
            self._refresh_paired_stream_status()

    @pyqtSlot()
    def _on_peer_disconnected(self):
        self._ws_mode = "presence"
        self._mjpeg.stop()
        self._screen.clear_frame()
        self._phone_accessibility_enabled = None
        self._remote_frame_visible = False
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
                # Oturumu duzgun sekilde kapat, anasayfaya don
                self._mjpeg.stop()
                self._screen.clear_frame()
                self._phone_accessibility_enabled = False
                self._remote_frame_visible = False
                self._set_connected(False)
                self._switch_page(0)
                self._show_warning_banner(banner_title, banner_body)
                self._refresh_home_summary()
                # Presence moduna gec (cihaz listesi canli kalsin)
                if self._ws_mode == "session":
                    self._ws_mode = "presence"
                    QTimer.singleShot(300, lambda: self._connect_presence_channel("Cihaz durumu izleniyor..."))

            QTimer.singleShot(0, _apply_banner)
        self._set_status(f"Hata: {msg}", error=True)

    @pyqtSlot(bytes)
    def _on_frame_received(self, frame_bytes: bytes):
        if not frame_bytes:
            return
            
        pixmap = QPixmap()
        # "JPEG" format kısıtlamasını SİLDİK. Qt formatı (PNG, WEBP, JPEG) kendi algılayacak.
        if not pixmap.loadFromData(frame_bytes):
            img = QImage()
            if not img.loadFromData(frame_bytes):
                # Eğer buraya düşerse Android tarafı resmi bozuyor veya başka format yolluyor demektir.
                import logging
                logging.getLogger(__name__).warning(f"Görüntü decode basarisiz! Gelen byte boyutu: {len(frame_bytes)}")
                return
            pixmap = QPixmap.fromImage(img)
            
        if pixmap.isNull():
            return
            
        if not self._connected:
            self._set_connected(True)
            self._switch_page(1)
        self._remote_frame_visible = True
        self._screen.set_frame(pixmap)
        self._refresh_paired_stream_status()

    @pyqtSlot(QPixmap)
    def _on_mjpeg_frame(self, pm: QPixmap):
        if pm.isNull():
            return
        self._remote_frame_visible = True
        self._screen.set_frame(pm)
        if self._connected:
            self._refresh_paired_stream_status()

    @pyqtSlot(str)
    def _on_mjpeg_error(self, _: str):
        self._remote_frame_visible = False
        if self._connected:
            self._refresh_paired_stream_status()

    @pyqtSlot()
    def _on_stream_stopped(self):
        if self._connected:
            self._remote_frame_visible = False
            self._refresh_paired_stream_status()
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
    def _request_phone_screen_capture(self) -> None:
        if not self._connected:
            return
        self._ws_client.send_screen_capture_on()

    def _refresh_paired_stream_status(self) -> None:
        if not self._connected:
            return
        if self._phone_accessibility_enabled is False:
            self._set_status(Ui.MSG_PAIRED_A11Y_OFF)
            return
        if self._remote_frame_visible:
            self._set_status(Ui.MSG_PAIRED_WS)
            return
        self._set_status(Ui.MSG_PAIRED_WAIT_STREAM)

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
            self._header_status_dot.setStyleSheet(f"background-color: {_GREEN}; border-radius: 4px;")
        else:
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
        self._presence_timer.stop()
        self._reconnect_timer.stop()
        self._manual_disconnect = True
        self._ws_client.disconnect()
        self.db.close()
        super().closeEvent(event)
