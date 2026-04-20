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
    QVBoxLayout,
    QWidget,
    QFileDialog,
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
from desktop_app.network.backend_api import BackendApi
from desktop_app.network.mjpeg_receiver import MjpegReceiver
from desktop_app.network.ws_client import WsClient
from desktop_app.ui.screen_widget import PhoneDeviceFrame, ScreenWidget, StreamAspectFitContainer
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

# Profil drawer konumu (_build_ui ile aynı margin ve sabit çubuk yükseklikleri)
_MAIN_SHELL_MARGIN = 10
_WIN_CHROME_BAR_HEIGHT = 36
_MAIN_NAV_BAR_HEIGHT = 38
_MAIN_FOOTER_BAR_HEIGHT = 28
_PROFILE_DRAWER_TOP_OFFSET = (
    _MAIN_SHELL_MARGIN + _WIN_CHROME_BAR_HEIGHT + _MAIN_NAV_BAR_HEIGHT
)
_PROFILE_DRAWER_BOTTOM_GAP = _MAIN_SHELL_MARGIN + _MAIN_FOOTER_BAR_HEIGHT

# Oturum (yayın) sayfası — güncel düğüm stilleri
_REMOTE_BTN_PRIMARY_SS = f"""
    QPushButton {{
        color: #FFFFFF;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F07858, stop:1 {_ACCENT_HOVER});
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 10px;
        font-size: 14px;
        font-weight: 700;
        padding: 0 18px;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #FF8A6A, stop:1 {_ACCENT});
        border-color: rgba(255, 255, 255, 0.24);
    }}
    QPushButton:pressed {{ background: {_ACCENT_HOVER}; padding-top: 1px; }}
    QPushButton:disabled {{
        background: #3D3D3D;
        color: #777777;
        border-color: #505050;
    }}
"""
_REMOTE_BTN_ICON_PRIMARY_SS = f"""
    QPushButton {{
        color: #FFFFFF;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #F07858, stop:1 {_ACCENT_HOVER});
        border: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 10px;
        font-size: 15px;
        font-weight: 700;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #FF8A6A, stop:1 {_ACCENT});
        border-color: rgba(255, 255, 255, 0.24);
    }}
    QPushButton:pressed {{ background: {_ACCENT_HOVER}; }}
    QPushButton:disabled {{
        background: #3D3D3D;
        color: #777777;
        border-color: #505050;
    }}
"""
_REMOTE_BTN_DANGER_SS = f"""
    QPushButton {{
        color: #FFB8B8;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #4A2A2A, stop:1 #3A2222);
        border: 1px solid rgba(248, 113, 113, 0.35);
        border-radius: 10px;
        font-size: 14px;
        font-weight: 700;
        padding: 0 14px;
    }}
    QPushButton:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #5C3434, stop:1 #452828);
        border-color: rgba(248, 113, 113, 0.55);
    }}
    QPushButton:pressed {{ background: #361818; }}
    QPushButton:disabled {{
        background-color: {_BG_INPUT};
        color: {_TEXT_DIM};
        border-color: {_BORDER_SUBTLE};
    }}
"""
_REMOTE_BTN_GHOST_SS = f"""
    QPushButton {{
        color: {_TEXT_SEC};
        background-color: {_BG_INPUT};
        border: 1px solid {_BORDER};
        border-radius: 10px;
        font-size: 14px;
        font-weight: 700;
        padding: 8px 10px;
    }}
    QPushButton:hover {{
        background-color: #383838;
        color: {_TEXT};
        border-color: #555555;
    }}
    QPushButton:pressed {{ background-color: #303030; }}
    QPushButton:disabled {{ color: {_TEXT_DIM}; border-color: {_BORDER_SUBTLE}; }}
"""
_REMOTE_KEY_BTN_SS = f"""
    QPushButton {{
        background-color: {_BG_INPUT};
        color: {_TEXT_SEC};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        font-size: 12px;
        font-weight: 700;
        padding: 8px 4px;
    }}
    QPushButton:hover {{
        background-color: #3A3A3A;
        color: {_TEXT};
        border-color: #555555;
    }}
    QPushButton:disabled {{ color: {_TEXT_DIM}; }}
"""
_PROFILE_DRAWER_CLOSE_BTN_SS = f"""
    QPushButton {{
        color: {_TEXT};
        background-color: {_BG_INPUT};
        border: 1px solid {_BORDER};
        border-radius: 10px;
        font-size: 11px;
        font-weight: 700;
        padding: 0 16px;
        min-height: 32px;
    }}
    QPushButton:hover {{
        background-color: #3A3A3A;
        border-color: {_ACCENT};
        color: {_TEXT};
    }}
    QPushButton:pressed {{ background-color: #2C2C2C; }}
"""


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


def _session_tab_label(owner_name: str | None, device_label: str | None, address_digits: str | None) -> str:
    owner = (owner_name or "").strip()
    device = (device_label or "").strip()
    addr = _address_digits(address_digits)
    addr_fmt = _format_address(addr) if addr else ""
    parts = [p for p in (owner, device, addr_fmt) if p]
    return " - ".join(parts) if parts else "Oturum"


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
    # Bazı endpoint'ler owner bilgisini farklı formatta döndürebilir; tek alana indir.
    if not (str(out.get("owner_name") or "").strip()):
        owner_obj = row.get("owner")
        if isinstance(owner_obj, dict):
            fn = str(owner_obj.get("first_name") or owner_obj.get("firstName") or "").strip()
            ln = str(owner_obj.get("last_name") or owner_obj.get("lastName") or "").strip()
            full = f"{fn} {ln}".strip()
            if full:
                out["owner_name"] = full
            else:
                name = str(owner_obj.get("name") or "").strip()
                if name:
                    out["owner_name"] = name
        else:
            fn = str(row.get("owner_first_name") or row.get("ownerFirstName") or "").strip()
            ln = str(row.get("owner_last_name") or row.get("ownerLastName") or "").strip()
            full = f"{fn} {ln}".strip()
            if full:
                out["owner_name"] = full
    return out


def _display_username(username: str | None) -> str:
    value = (username or "").strip()
    if not value:
        return "Kullanici"
    return value[:1].upper() + value[1:]


class _DraggableTitleBar(QFrame):
    """Frameless pencerede boş başlık alanından sürükleyerek taşıma (sekmeler/hesap düğmeleri etkilenmez)."""

    def __init__(self, window: QMainWindow, parent: QWidget | None = None):
        super().__init__(parent)
        self._window = window
        self._drag_pos: QPoint | None = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_pos is not None
            and event.buttons() == Qt.MouseButton.LeftButton
        ):
            self._window.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)


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
    CARD_W = 270
    CARD_H = 150

    def __init__(
        self,
        device_id: str,
        address: str | None = None,
        device_name: str | None = None,
        owner_name: str | None = None,
        owner_phone: str | None = None,  # left for backcompat, but will not be shown
        owner_email: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.device_id = device_id
        self.address = _address_digits(address)
        self.device_name = device_name
        self.owner_name = (owner_name or "").strip() or None
        self.owner_phone = (owner_phone or "").strip() or None  # not shown anymore
        self.owner_email = (owner_email or "").strip() or None
        self._online = False
        self._connect_cb = None
        self._forget_cb = None
        self.setFixedSize(self.CARD_W, self.CARD_H)
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

        owner = (self.owner_name or "").strip()
        self._owner = QLabel(_compact_label(owner, 34) if owner else "")
        self._owner.setVisible(bool(owner))
        self._owner.setStyleSheet(
            f"color: {_ACCENT}; font-size: 14px; font-weight: 800; background: transparent;"
        )
        root.addWidget(self._owner)

        formatted = _display_device_name(device_name, address, device_id)
        self._title = QLabel(_compact_label(formatted, 28))
        self._title.setStyleSheet(f"color: {_TEXT}; font-size: 15px; font-weight: 800; background: transparent;")
        root.addWidget(self._title)

        address_text = _format_address(address or "") if address else ""
        # Remove phone number from subtitle, only show address or fallback
        subtitle = address_text if address_text and address_text != formatted else "Eslesmis cihaz"
        self._lbl_address = QLabel(subtitle)
        self._lbl_address.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px; background: transparent;")
        root.addWidget(self._lbl_address)

        self._lbl_status = QLabel("Cevrimdisi")
        self._lbl_status.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px; background: transparent;")
        root.addWidget(self._lbl_status)

        root.addStretch()
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
    def __init__(self, backend_api: BackendApi | None = None):
        super().__init__()
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
        self._a11y_pending_reconnect_code: str | None = None  # erişilebilirlik açılınca otomatik yeniden bağlantı için
        self._profile_drawer_open = False
        self._profile_drawer_width = 432
        self._profile_cache: dict = {}
        self._profile_anim: QPropertyAnimation | None = None
        # Telefona birden fazla paired gelince screen_capture_on spamını önlemek için
        self._screen_capture_prompt_sent: bool = False
        self._fps_frame_counter: int = 0
        self._last_stream_size: tuple[int, int] = (0, 0)

        self.setWindowTitle(AppMeta.WINDOW_TITLE)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Kart marjinleri + sağ sütun (oturum paneli) için biraz daha ferah alan
        self.setFixedSize(1320, 920)
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

        self._fps_histogram_timer = QTimer(self)
        self._fps_histogram_timer.setInterval(1000)
        self._fps_histogram_timer.timeout.connect(self._tick_stream_fps_label)

        self._session_ping_timer = QTimer(self)
        self._session_ping_timer.setInterval(2500)
        self._session_ping_timer.timeout.connect(self._tick_session_ping)

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
            # BackendAPI başarısız olduysa prefs'teki cached değeri kullan
            self._user_address = load_user_address() or ""
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
                return []  # API başarısız, boş liste dön
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
        return []  # Auth token yok ya da API başarısız

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
        c = Colors
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {c.BG_APP}; }}
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
        outer = QVBoxLayout(central)
        outer.setContentsMargins(_MAIN_SHELL_MARGIN, _MAIN_SHELL_MARGIN, _MAIN_SHELL_MARGIN, _MAIN_SHELL_MARGIN)
        outer.setSpacing(0)

        c = Colors
        card = QFrame(objectName="main_shell_card")
        card.setStyleSheet(
            f"QFrame#main_shell_card {{ {card_style(background=c.BG_SURFACE)} }}"
        )
        outer.addWidget(card, stretch=1)

        root = QVBoxLayout(card)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_window_chrome_bar())
        root.addWidget(self._build_title_bar())

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_home_page())
        self._pages.addWidget(self._build_remote_page())
        root.addWidget(self._pages, stretch=1)

        root.addWidget(self._build_footer_status())

        # Sağdan açılan profil sekmesi (drawer)
        self._profile_drawer = self._build_profile_drawer(central)
        self._profile_drawer.hide()

    # ── 1. Üst pencere şeridi (login ile aynı mantık: logo + başlık + küçült/kapat) ──
    def _build_window_chrome_bar(self) -> QWidget:
        c = Colors
        bar = _DraggableTitleBar(self)
        bar.setFixedHeight(_WIN_CHROME_BAR_HEIGHT)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {c.BG_CARD};
                border-bottom: 1px solid {c.BORDER};
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(8)

        mini = QLabel()
        mini.setFixedSize(18, 18)
        mini.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pm = self._load_logo_pixmap(18)
        if pm is not None:
            mini.setPixmap(pm)
        else:
            mini.setStyleSheet(
                f"background-color: {_ACCENT}; border-radius: 4px; font-size: 9px;"
                f" color: #1A1A1A; font-weight: 800;"
            )
            mini.setText("R")
        lay.addWidget(mini)

        lbl = QLabel(AppMeta.NAME)
        lbl.setStyleSheet(text_style(c.TEXT_MUTED, size=11))
        lay.addWidget(lbl)
        lay.addStretch()

        _win_tool = f"""
            QPushButton {{
                background: transparent; color: {_TEXT_SEC}; border: none;
                border-radius: 8px; font-size: 16px; font-weight: 500;
                min-width: 38px; min-height: 28px;
            }}
            QPushButton:hover {{ background-color: rgba(255, 255, 255, 0.08); color: {_TEXT}; }}
        """
        _win_close = f"""
            QPushButton {{
                background: transparent; color: {_TEXT_SEC}; border: none;
                border-radius: 8px; font-size: 17px; font-weight: 600;
                min-width: 38px; min-height: 28px;
            }}
            QPushButton:hover {{ background-color: rgba(248, 113, 113, 0.22); color: {_RED}; }}
        """
        self._btn_win_min = QPushButton("−")
        self._btn_win_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_win_min.setStyleSheet(_win_tool)
        self._btn_win_min.setToolTip("Simge durumuna kucult")
        self._btn_win_min.clicked.connect(self.showMinimized)
        lay.addWidget(self._btn_win_min)

        self._btn_win_close = QPushButton("×")
        self._btn_win_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_win_close.setStyleSheet(_win_close)
        self._btn_win_close.setToolTip("Kapat")
        self._btn_win_close.clicked.connect(self.close)
        lay.addWidget(self._btn_win_close)

        return bar

    def _build_footer_status(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(_MAIN_FOOTER_BAR_HEIGHT)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {_BG};
                border-top: 1px solid {_BORDER_SUBTLE};
                border-bottom-left-radius: 6px;
                border-bottom-right-radius: 6px;
            }}
        """)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 4, 14, 4)
        self._footer_status_label = QLabel(Ui.MSG_WAITING)
        self._footer_status_label.setStyleSheet(
            f"color: {_TEXT_SEC}; font-size: 11px; background: transparent;"
        )
        lay.addWidget(self._footer_status_label)
        return bar

    def _load_logo_pixmap(self, size: int) -> QPixmap | None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        logo_path = os.path.join(root, "logo.png")
        pm = QPixmap(logo_path)
        if pm.isNull():
            return None
        return pm.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    # ── 2. Sekmeler + hesap (profil burada, pencere düğmeleri üst şeritte) ─────
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
        bar.setFixedHeight(_MAIN_NAV_BAR_HEIGHT)
        bar.setStyleSheet(f"background-color: {_BG}; border-bottom: 1px solid {_BORDER_SUBTLE};")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(0)

        logo = QFrame()
        logo.setFixedSize(10, 10)
        logo.setStyleSheet(f"background-color: {_ACCENT}; border-radius: 5px;")
        lay.addWidget(logo)
        lay.addSpacing(10)

        self._tab_home = QPushButton("Ana Sayfa")
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

    # ── 3. Home Page ─────────────────────────────────────────────────────────
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
        self._warning_close.setFixedHeight(30)
        self._warning_close.setStyleSheet(f"""
            QPushButton {{
                color: #FFCCCC;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(248,113,113,0.28), stop:1 rgba(220,80,80,0.18));
                border: 1px solid rgba(248,113,113,0.45);
                border-radius: 10px;
                font-size: 11px;
                font-weight: 700;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(255,140,140,0.35), stop:1 rgba(248,113,113,0.25));
                border-color: rgba(255,160,160,0.55);
            }}
            QPushButton:pressed {{ background-color: rgba(248,113,113,0.22); }}
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
        self._inp_code.setFixedHeight(34)
        self._inp_code.setMaxLength(14)
        font = QFont("Segoe UI", 14)
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
        self._btn_connect.setFixedSize(40, 40)
        self._btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_connect.setStyleSheet(_REMOTE_BTN_ICON_PRIMARY_SS)
        lay.addWidget(self._btn_connect)

        self._addr_status_label = QLabel("Hazir")
        self._addr_status_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
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
        # Mobil temadaki primary/primary_surface tonlarıyla uyumlu border.
        self._hero_address.setStyleSheet(f"""
            QLabel {{
                color: {_TEXT};
                background-color: rgba(42, 31, 26, 0.65);  /* primary_surface (#2A1F1A) */
                border: 1px solid rgba(232, 93, 58, 0.45); /* primary (#E85D3A) */
                border-radius: 12px;
                padding: 10px 14px;
            }}
        """)
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
        tbl.setContentsMargins(14, 8, 14, 8)
        tbl.setSpacing(14)

        tbl.addStretch(1)

        stats_row = QWidget()
        stats_row.setStyleSheet("background: transparent;")
        srl = QHBoxLayout(stats_row)
        srl.setContentsMargins(0, 0, 0, 0)
        srl.setSpacing(16)
        stat_ss = (
            f"color: {_TEXT_SEC}; font-size: 10px; font-weight: 600; background: transparent;"
        )
        self._lbl_sess_res = QLabel("— × —")
        self._lbl_sess_fps = QLabel("FPS —")
        self._lbl_sess_rtt = QLabel("RTT —")
        for lb in (self._lbl_sess_res, self._lbl_sess_fps, self._lbl_sess_rtt):
            lb.setStyleSheet(stat_ss)
            srl.addWidget(lb)
        tbl.addWidget(stats_row, stretch=0)

        self._btn_disconnect = QPushButton("Baglantıyi Kes")
        self._btn_disconnect.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_disconnect.setFixedHeight(32)
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.setStyleSheet(_REMOTE_BTN_DANGER_SS)
        tbl.addWidget(self._btn_disconnect)
        left.addWidget(top_bar)

        screen_frame = QFrame()
        screen_frame.setStyleSheet(
            f"background-color: #0d0d0f; border: 1px solid {_BORDER_SUBTLE}; border-radius: 8px;"
        )
        sl = QVBoxLayout(screen_frame)
        sl.setContentsMargins(8, 8, 8, 8)
        self._screen = ScreenWidget()
        self._stream_aspect_host = StreamAspectFitContainer(PhoneDeviceFrame(self._screen))
        sl.addWidget(self._stream_aspect_host, stretch=1)
        left.addWidget(screen_frame, stretch=1)

        self._remote_summary_label = QLabel("")
        layout.addLayout(left, stretch=7)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_controls_panel())
        right.addWidget(self._build_key_controls_panel())
        right.addWidget(self._build_session_actions_panel())
        right.addWidget(self._build_remote_shortcuts_panel())
        right.addStretch(1)
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

        title = QLabel("Ekran Kontrolleri")
        title.setStyleSheet(f"color: {_ACCENT}; font-size: 11px; font-weight: 600;")
        lay.addWidget(title)

        rot_row = QHBoxLayout()
        rot_row.setSpacing(8)
        self._btn_rotate_left = QPushButton("Sola dön")
        self._btn_rotate_right = QPushButton("Sağa dön")
        for b in (self._btn_rotate_left, self._btn_rotate_right):
            b.setFixedHeight(36)
            b.setEnabled(False)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(_REMOTE_BTN_GHOST_SS)
        rot_row.addWidget(self._btn_rotate_left, stretch=1)
        rot_row.addWidget(self._btn_rotate_right, stretch=1)
        lay.addLayout(rot_row)
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
        title.setStyleSheet(f"color: {_ACCENT}; font-size: 11px; font-weight: 600;")
        lay.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(4)
        self._key_buttons = []
        key_codes = AndroidKeyCodes.as_mapping()

        for label, group, row, col, key_id, colspan in AndroidKeyCodes.button_specs():
            btn = QPushButton(label)
            btn.setEnabled(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(_REMOTE_KEY_BTN_SS)
            btn.clicked.connect(lambda _, code=key_codes[key_id]: self._ws_client.send_key_event(code))
            if colspan > 1:
                grid.addWidget(btn, row, col, 1, colspan)
            else:
                grid.addWidget(btn, row, col)
            self._key_buttons.append(btn)
        lay.addLayout(grid)
        return panel

    def _build_session_actions_panel(self) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(
            f"background-color: {_BG_CARD}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        title = QLabel("Ekran ve pano")
        title.setStyleSheet(f"color: {_ACCENT}; font-size: 11px; font-weight: 700;")
        lay.addWidget(title)

        self._btn_sess_clip = QPushButton("Görüntüyü panoya kopyala")
        self._btn_sess_clip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sess_clip.setStyleSheet(_REMOTE_BTN_GHOST_SS)
        self._btn_sess_clip.setFixedHeight(34)
        self._btn_sess_clip.clicked.connect(self._screenshot_to_clipboard)
        lay.addWidget(self._btn_sess_clip)

        self._btn_sess_save = QPushButton("PNG olarak kaydet…")
        self._btn_sess_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sess_save.setStyleSheet(_REMOTE_BTN_GHOST_SS)
        self._btn_sess_save.setFixedHeight(34)
        self._btn_sess_save.clicked.connect(self._screenshot_save_png)
        lay.addWidget(self._btn_sess_save)

        self._btn_sess_paste = QPushButton("Panodaki metni telefona gönder")
        self._btn_sess_paste.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_sess_paste.setStyleSheet(_REMOTE_BTN_PRIMARY_SS)
        self._btn_sess_paste.setFixedHeight(36)
        self._btn_sess_paste.clicked.connect(self._send_clipboard_text_to_phone)
        self._btn_sess_paste.setEnabled(False)
        lay.addWidget(self._btn_sess_paste)

        return panel

    def _build_remote_shortcuts_panel(self) -> QFrame:
        """Tam genişlikte tuş + alt satır açıklama; dar panelde iki sütun kısılmaz."""
        panel = QFrame()
        panel.setStyleSheet(
            f"background-color: {_BG_CARD}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
        )
        root = QVBoxLayout(panel)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        title = QLabel("Klavye kısayolları")
        title.setStyleSheet(f"color: {_ACCENT}; font-size: 12px; font-weight: 700;")
        root.addWidget(title)

        intro = QLabel(
            "Tuşlar yalnızca sol taraftaki canlı görüntü odaktayken çalışır; önce görüntüye tıklayın."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px; background: transparent;")
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(136)
        scroll.setViewportMargins(0, 0, 10, 0)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background-color: {_BG_RAISED};
                width: 11px;
                margin: 4px 6px 4px 4px;
                border-radius: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background-color: {_ACCENT};
                border-radius: 5px;
                min-height: 44px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: #e07a62;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)

        shortcuts_rows: list[tuple[str, str]] = [
            ("Esc", "Geri: bir önceki ekrana veya uygulamadan çıkışa benzer."),
            ("Ctrl+H", "Ana ekran: telefonun ana sayfasına döner."),
            ("Ctrl+Tab", "Son uygulamalar: çoklu görev / uygulama geçiş listesini açar."),
            ("Ctrl+M", "Medya sesini sessize alır veya sessizi açar (aynı düğme)."),
            ("Ctrl+↑ / Ctrl+↓", "Ses aç / kıs (medya akışı)."),
        ]

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(inner)
        vl.setContentsMargins(2, 4, 2, 8)
        vl.setSpacing(0)

        key_ss = (
            f"color: {_ACCENT}; font-size: 12px; font-weight: 700;"
            f" font-family: 'Cascadia Mono', 'Consolas', 'Segoe UI', monospace;"
            f" background: transparent;"
        )
        desc_ss = f"color: {_TEXT_SEC}; font-size: 12px; background: transparent;"

        for idx, (key_text, explanation) in enumerate(shortcuts_rows):
            kl = QLabel(key_text)
            kl.setStyleSheet(key_ss)
            kl.setAlignment(Qt.AlignmentFlag.AlignLeft)
            kl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            vl.addWidget(kl)

            dl = QLabel(explanation)
            dl.setWordWrap(True)
            dl.setStyleSheet(desc_ss)
            dl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            dl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            vl.addWidget(dl)
            if idx < len(shortcuts_rows) - 1:
                vl.addSpacing(10)

        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)
        return panel

    # ── Signals ──────────────────────────────────────────────────────────────
    def _connect_signals(self):
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        self._btn_rotate_left.clicked.connect(self._on_rotate_left)
        self._btn_rotate_right.clicked.connect(self._on_rotate_right)
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
        self._screen.remote_key_pressed.connect(self._on_screen_remote_key)
        self._ws_client.session_rtt_ms.connect(
            self._on_session_rtt,
            Qt.ConnectionType.QueuedConnection,
        )

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
        cols = max(1, (self.width() - 60) // (DeviceCard.CARD_W + 18))
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
            if active_card:
                label = _session_tab_label(active_card.owner_name, active_card.display_name(), active_card.address)
            else:
                label = _session_tab_label(None, f"...{self._paired_phone_id[-8:]}", self._paired_phone_address)
            self._tab_session_btn.setText(f"  {label}")
            self._tab_session.show()
        else:
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
        btn_close.setFixedHeight(32)
        btn_close.setMinimumWidth(86)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet(_PROFILE_DRAWER_CLOSE_BTN_SS)
        btn_close.setToolTip("Profil panelini kapat")
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

        edit_lay.addWidget(_field_lbl("Ad ve soyad"))
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

    def _profile_drawer_geometry(self) -> tuple[int, int, int]:
        """
        Profil paneli: üstteki taşıma / küçült / kapat şeritlerini örtmez.
        Dönüş: (top_y, height, central_width).
        """
        cw = self.centralWidget()
        if cw is None:
            h = max(
                160,
                self.height() - _PROFILE_DRAWER_TOP_OFFSET - _PROFILE_DRAWER_BOTTOM_GAP,
            )
            return _PROFILE_DRAWER_TOP_OFFSET, h, self.width()
        inner_h = cw.height() - _PROFILE_DRAWER_TOP_OFFSET - _PROFILE_DRAWER_BOTTOM_GAP
        h = max(160, inner_h)
        return _PROFILE_DRAWER_TOP_OFFSET, h, cw.width()

    def _set_profile_drawer_open(self, open_: bool) -> None:
        if self._profile_drawer_open == open_:
            return
        self._profile_drawer_open = open_

        top, drawer_h, cw_w = self._profile_drawer_geometry()
        self._profile_drawer.setFixedHeight(drawer_h)

        m = _MAIN_SHELL_MARGIN
        start_x = cw_w if open_ else (cw_w - self._profile_drawer_width - m)
        end_x = (cw_w - self._profile_drawer_width - m) if open_ else cw_w

        if open_:
            self._profile_drawer.show()
            self._profile_drawer.raise_()

        start_pos = QPoint(start_x, top)
        end_pos = QPoint(end_x, top)
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
        if hasattr(self, "_profile_drawer"):
            top, dh, cw_w = self._profile_drawer_geometry()
            self._profile_drawer.setFixedHeight(dh)
            m = _MAIN_SHELL_MARGIN
            if self._profile_drawer_open:
                self._profile_drawer.move(cw_w - self._profile_drawer_width - m, top)
            else:
                self._profile_drawer.move(cw_w, top)

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
        label = _session_tab_label(card.owner_name, card.display_name(), card.address)
        self._tab_session_btn.setText(f"  {label}")
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
        self._set_status("Cihaz adresine baglaniliyor...")
        matching_card = next(
            (card for card in self._device_cards.values() if (card.connection_address() or "") == _format_address(raw_value)),
            None,
        )
        self._paired_phone_id = matching_card.device_id if matching_card else None
        self._paired_phone_address = raw_value
        save_paired_phone_address(raw_value)
        if matching_card:
            label = _session_tab_label(matching_card.owner_name, matching_card.display_name(), matching_card.address)
            self._tab_session_btn.setText(f"  {label}")
        else:
            # Kart yoksa owner/device adı bilinmeyebilir; adresi yine göster.
            label = _session_tab_label(None, "Baglaniyor", raw_value)
            self._tab_session_btn.setText(f"  {label}")
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

    @pyqtSlot()
    def _on_disconnect(self):
        self._ws_mode = "presence"
        self._reconnect_session_code = None
        self._a11y_pending_reconnect_code = None  # manuel disconnect → otomatik yeniden bağlantı iptal
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
        login = LoginWindow()
        if login.exec() == QDialog.DialogCode.Accepted:
            replacement = MainWindow(backend_api=login.shared_backend_api)
            app = QApplication.instance()
            if app is not None:
                setattr(app, "_rpc_main_window", replacement)
            replacement.show()
            self.close()
        else:
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
        if not self._screen_capture_prompt_sent:
            self._screen_capture_prompt_sent = True
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

        # Erişilebilirlik False→True geçişini yakala
        prev_a11y = self._phone_accessibility_enabled
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

            # Erişilebilirlik sonrası otomatik yeniden bağlantı için session kodunu sakla
            session_code = _address_digits(self._paired_phone_address or "")
            if len(session_code) != 12:
                session_code = _address_digits(load_paired_phone_address() or "")
            if len(session_code) != 12:
                session_code = _address_digits(self._ws_client.join_session_code or "")
            if len(session_code) == 12:
                self._a11y_pending_reconnect_code = session_code
                logger.info("Erisilebilirlik hatası — yeniden baglanti kodu saklandı: %s", session_code)

            def _apply_banner() -> None:
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
        self._note_stream_frame(pixmap.width(), pixmap.height())
        self._refresh_paired_stream_status()

    @pyqtSlot(QPixmap)
    def _on_mjpeg_frame(self, pm: QPixmap):
        if pm.isNull():
            return
        self._remote_frame_visible = True
        self._screen.set_frame(pm)
        self._note_stream_frame(pm.width(), pm.height())
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

    def _apply_rotation_step(self) -> None:
        """Mevcut adımı ekrana ve telefona uygula (0°–270°)."""
        deg = self._rotation_step * 90
        self._screen.set_rotation(deg)
        self._sync_stream_aspect_fit()
        self._ws_client.send_rotate_screen(deg)

    @pyqtSlot()
    def _on_rotate_left(self):
        """Saat yönünün tersine 90° (sola)."""
        self._rotation_step = (self._rotation_step + 3) % 4
        self._apply_rotation_step()

    @pyqtSlot()
    def _on_rotate_right(self):
        """Saat yönünde 90° (sağa)."""
        self._rotation_step = (self._rotation_step + 1) % 4
        self._apply_rotation_step()

    @pyqtSlot(float, float)
    def _on_touch(self, x: float, y: float):
        if not self._connected:
            return
        self._ws_client.send_touch(x, y)

    @pyqtSlot(float, float, float, float)
    def _on_swipe(self, x1, y1, x2, y2):
        if not self._connected:
            return
        self._ws_client.send_swipe(x1, y1, x2, y2)

    def _set_remote_controls_enabled(self, enabled: bool) -> None:
        """Remote sayfası kontrol butonları: akış gelmeden kapalı kalsın."""
        if hasattr(self, "_btn_rotate_left"):
            self._btn_rotate_left.setEnabled(enabled)
        if hasattr(self, "_btn_rotate_right"):
            self._btn_rotate_right.setEnabled(enabled)
        if hasattr(self, "_key_buttons"):
            for btn in self._key_buttons:
                btn.setEnabled(enabled)
        if hasattr(self, "_btn_sess_clip"):
            self._btn_sess_clip.setEnabled(enabled)
        if hasattr(self, "_btn_sess_save"):
            self._btn_sess_save.setEnabled(enabled)
        if hasattr(self, "_btn_sess_paste"):
            self._btn_sess_paste.setEnabled(enabled)

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
            self._set_remote_controls_enabled(False)
            return
        if self._remote_frame_visible:
            self._set_status(Ui.MSG_PAIRED_WS)
            self._set_remote_controls_enabled(True)
            return
        self._set_status(Ui.MSG_PAIRED_WAIT_STREAM)
        self._set_remote_controls_enabled(False)

    def _sync_stream_aspect_fit(self, ew: int | None = None, eh: int | None = None) -> None:
        if not hasattr(self, "_stream_aspect_host"):
            return
        if ew is None or eh is None:
            ew, eh = self._screen.effective_frame_size()
        if ew <= 0 or eh <= 0:
            return
        self._stream_aspect_host.set_stream_dimensions(ew, eh)

    def _note_stream_frame(self, w: int, h: int) -> None:
        """Gelen kare boyutu + döndürme ile çerçeve oranı ve çözünürlük etiketi güncellenir."""
        ew, eh = self._screen.displayed_size_for_incoming(w, h)
        if ew > 0 and eh > 0 and hasattr(self, "_lbl_sess_res"):
            self._lbl_sess_res.setText(f"{ew}×{eh}")
        self._sync_stream_aspect_fit(ew, eh)
        self._fps_frame_counter += 1

    @pyqtSlot()
    def _tick_stream_fps_label(self) -> None:
        if not hasattr(self, "_lbl_sess_fps"):
            return
        if not self._connected:
            self._lbl_sess_fps.setText("FPS —")
            self._fps_frame_counter = 0
            return
        fps = self._fps_frame_counter
        self._fps_frame_counter = 0
        self._lbl_sess_fps.setText(f"FPS {fps}")

    @pyqtSlot()
    def _tick_session_ping(self) -> None:
        if self._connected:
            self._ws_client.send_session_ping()

    @pyqtSlot(float)
    def _on_session_rtt(self, ms: float) -> None:
        if hasattr(self, "_lbl_sess_rtt"):
            self._lbl_sess_rtt.setText(f"RTT {ms:.0f} ms")

    def _reset_session_stats_labels(self) -> None:
        if not hasattr(self, "_lbl_sess_res"):
            return
        self._lbl_sess_res.setText("— × —")
        self._lbl_sess_fps.setText("FPS —")
        self._lbl_sess_rtt.setText("RTT —")

    def _on_screen_remote_key(self, key_code: int) -> None:
        if not self._connected:
            return
        self._ws_client.send_key_event(int(key_code))

    def _screenshot_to_clipboard(self) -> None:
        pm = self._screen.get_export_pixmap()
        if pm is None or pm.isNull():
            self._set_status("Kopyalanacak goruntu yok.", error=True)
            return
        QApplication.clipboard().setPixmap(pm)
        self._set_status(f"Panoya kopyalandi ({pm.width()}x{pm.height()}).")

    def _screenshot_save_png(self) -> None:
        pm = self._screen.get_export_pixmap()
        if pm is None or pm.isNull():
            self._set_status("Kaydedilecek goruntu yok.", error=True)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "PNG olarak kaydet", "remote_ekran.png", "PNG (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if pm.save(path, "PNG"):
            self._set_status(f"Kaydedildi: {path}")
        else:
            self._set_status("PNG kaydedilemedi.", error=True)

    def _send_clipboard_text_to_phone(self) -> None:
        if not self._connected:
            self._set_status("Once oturum ile baglanin.", error=True)
            return
        text = QApplication.clipboard().text()
        if not (text or "").strip():
            self._set_status("Pano bos.", error=True)
            return
        self._ws_client.send_paste_text(text)
        self._set_status(f"Pano metni gonderildi ({len(text)} karakter).")

    def _set_connected(self, connected: bool):
        self._connected = connected
        if not connected:
            self._screen_capture_prompt_sent = False
            self._fps_histogram_timer.stop()
            self._session_ping_timer.stop()
            self._reset_session_stats_labels()
            self._sync_stream_aspect_fit()
        else:
            self._fps_histogram_timer.start()
            self._session_ping_timer.start()
        # Stream gelmeden kontrol butonları kapalı kalsın.
        self._set_remote_controls_enabled(bool(connected and self._remote_frame_visible))
        self._btn_connect.setEnabled(not connected)
        self._btn_disconnect.setEnabled(connected)
        if connected:
            self._hide_warning_banner()
            self._header_status_dot.setStyleSheet(f"background-color: {_GREEN}; border-radius: 4px;")
        else:
            self._header_status_dot.setStyleSheet(f"background-color: {_TEXT_DIM}; border-radius: 4px;")
        self._refresh_home_summary()

    def _set_status(self, msg: str, error: bool = False):
        color = _RED if error else _TEXT_SEC
        label = getattr(self, "_footer_status_label", None)
        if label is None:
            return
        label.setStyleSheet(f"color: {color}; font-size: 11px; background: transparent;")
        label.setText(msg)

    def closeEvent(self, event):
        self._mjpeg.stop()
        self._presence_timer.stop()
        self._reconnect_timer.stop()
        self._fps_histogram_timer.stop()
        self._session_ping_timer.stop()
        self._manual_disconnect = True
        self._ws_client.disconnect()
        super().closeEvent(event)
