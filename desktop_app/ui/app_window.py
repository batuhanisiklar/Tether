"""
Remote Phone Control — Desktop Shell  (AnyDesk-inspired)
=========================================================
Layout (home page, top → bottom):
  1. Title bar           (logo · session chip · account pill)
  2. Address input bar   (full-width dark bar like AnyDesk)
  3. Your Address hero   (large formatted number)
  4. Tab strip           (Recent Sessions)
  5. Device card grid    (paired phones)
When a connection is active, page 1 shows live remote control.
"""

import logging
import os
from datetime import datetime, timezone

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
    """Large hero display: '000000000001' → '0000 0000 0001'."""
    digits = "".join(ch for ch in addr if ch.isdigit())[:12]
    return "  ".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def _display_device_name(device_name: str | None, address: str | None, device_id: str) -> str:
    if device_name and device_name.strip():
        return device_name.strip()
    if address and address.strip():
        return _format_address(address)
    return "..." + device_id[-8:] if len(device_id) > 8 else device_id


def _compact_label(text: str, limit: int = 24) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _display_username(username: str | None) -> str:
    value = (username or "").strip()
    if not value:
        return "Kullanici"
    return value[:1].upper() + value[1:]


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
        last_seen: datetime | None,
        address: str | None = None,
        device_name: str | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.device_id = device_id
        self.address = address
        self.device_name = device_name
        self._last_seen = last_seen
        self._online = False
        self._connect_cb = None
        self._forget_cb = None
        self.setFixedSize(230, 125)
        self._build(device_id, last_seen, address, device_name)

    def _build(self, device_id: str, last_seen: datetime | None, address: str | None, device_name: str | None):
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
        self._title = QLabel(_compact_label(formatted, 24))
        self._title.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: 600; background: transparent;")
        root.addWidget(self._title)

        address_text = _format_address(address or "") if address else ""
        self._lbl_address = QLabel(address_text if address_text and address_text != formatted else "Eslesmis cihaz")
        self._lbl_address.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 10px; background: transparent;")
        root.addWidget(self._lbl_address)

        self._lbl_time = QLabel(_relative_time(last_seen))
        self._lbl_time.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; background: transparent;")
        root.addWidget(self._lbl_time)

        self._apply_card_style()

    def display_name(self) -> str:
        return _display_device_name(self.device_name, self.address, self.device_id)

    def connection_address(self) -> str | None:
        digits = "".join(ch for ch in (self.address or "") if ch.isdigit())[:12]
        return _format_address(digits) if digits else None

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
            self._lbl_time.setText("Cevrimici")
            self._lbl_time.setStyleSheet(f"color: {_GREEN}; font-size: 10px; font-weight: 600; background: transparent;")
        else:
            self._dot.setStyleSheet(f"background-color: {_TEXT_DIM}; border-radius: 4px;")
            self._lbl_time.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; background: transparent;")
            self._lbl_time.setText(_relative_time(self._last_seen))
        self._apply_card_style()

    def set_last_seen(self, dt: datetime | None):
        self._last_seen = dt
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
        self._manual_disconnect = False
        self._user_id: int | None = None
        self._username = "Kullanici"
        self._user_address = ""
        self._current_page = 0
        self._session_chip: QFrame | None = None
        self._session_chip_btn: QPushButton | None = None
        self._account_button: QPushButton | None = None

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

        QTimer.singleShot(250, self._load_devices_from_db)

    def _load_user_prefs(self):
        prefs = read_prefs()
        self._user_id = prefs.get("user_id")
        self._username = prefs.get("username", "Kullanici")
        if self._user_id:
            self._user_address = self.db.get_user_address(self._user_id) or ""

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
        lay.addSpacing(8)

        title = QLabel("Remote Phone Control")
        title.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: 700;")
        lay.addWidget(title)
        lay.addSpacing(16)

        self._session_chip = QFrame()
        self._session_chip.setStyleSheet(
            f"background-color: rgba(232,93,58,0.10); border: 1px solid rgba(232,93,58,0.25); border-radius: 12px;"
        )
        chip_lay = QHBoxLayout(self._session_chip)
        chip_lay.setContentsMargins(0, 0, 0, 0)
        chip_lay.setSpacing(0)

        self._session_chip_btn = QPushButton("Aktif Oturum")
        self._session_chip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._session_chip_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {_ACCENT}; border: none; font-size: 11px; font-weight: 600; padding: 4px 8px 4px 10px; }}
            QPushButton:hover {{ color: {_TEXT}; }}
        """)
        self._session_chip_btn.clicked.connect(lambda: self._switch_page(1))
        chip_lay.addWidget(self._session_chip_btn)

        chip_close = QPushButton("×")
        chip_close.setCursor(Qt.CursorShape.PointingHandCursor)
        chip_close.setFixedSize(22, 22)
        chip_close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {_ACCENT}; border: none; font-size: 14px; font-weight: 700; }}
            QPushButton:hover {{ color: {_TEXT}; }}
        """)
        chip_close.clicked.connect(self._on_disconnect)
        chip_lay.addWidget(chip_close)

        self._session_chip.hide()
        lay.addWidget(self._session_chip)

        lay.addStretch()

        self._header_status_dot = QFrame()
        self._header_status_dot.setFixedSize(8, 8)
        self._header_status_dot.setStyleSheet(f"background-color: {_TEXT_DIM}; border-radius: 4px;")
        lay.addWidget(self._header_status_dot)
        lay.addSpacing(6)

        self._account_button = QPushButton(f"{_display_username(self._username)}  ▾")
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
        self._inp_code.setPlaceholderText("Uzak adres girin")
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

        info_user = QLabel(f"  {_display_username(self._username)}")
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

        btn_back = QPushButton("← Anasayfa")
        btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_back.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {_ACCENT}; border: none; font-size: 12px; font-weight: 600; }}
            QPushButton:hover {{ color: {_TEXT}; }}
        """)
        btn_back.clicked.connect(lambda: self._switch_page(0))
        tbl.addWidget(btn_back)

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

    # ── Data loading ─────────────────────────────────────────────────────────
    @pyqtSlot()
    def _load_devices_from_db(self):
        if self._user_id:
            self.db.upsert_device(self._user_id, self._ws_client.device_id, "pc", _desktop_device_name())
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
        for device in devices:
            card = DeviceCard(
                device["device_id"],
                device.get("last_seen"),
                device.get("address"),
                device.get("device_name"),
            )
            card.set_connect_callback(self._on_card_connect)
            card.set_forget_callback(self._on_card_forget)
            self._device_cards[device["device_id"]] = card

        self._lbl_device_count.setText(f"{len(devices)} cihaz")
        self._reflow_device_cards()
        self._refresh_home_summary()

    def _reflow_device_cards(self):
        while self._recent_devices_layout.count():
            self._recent_devices_layout.takeAt(0)

        ordered = sorted(
            self._device_cards.items(),
            key=lambda item: (item[0] not in self._online_paired_devices,),
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

        if self._connected and self._paired_phone_id:
            card = self._device_cards.get(self._paired_phone_id)
            display_name = card.display_name() if card else f"...{self._paired_phone_id[-8:]}"
            compact_name = _compact_label(display_name, 20)
            self._remote_device_badge.setText(f"Aktif: {compact_name}")
            if self._session_chip is not None and self._session_chip_btn is not None:
                self._session_chip_btn.setText(compact_name)
                self._session_chip.show()
        else:
            self._remote_device_badge.setText("Bagli cihaz yok")
            if self._session_chip is not None:
                self._session_chip.hide()

        if self._account_button is not None:
            self._account_button.setText(f"{_display_username(self._username)}  ▾")

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
        lines = [f"Kullanici:  {_display_username(self._username)}"]
        if self._user_address:
            lines.append(f"Hesap adresi:  {_format_address(self._user_address)}")
        lines.append(f"Bilgisayar:  {_desktop_device_name()}")
        QMessageBox.information(self, "Profil", "\n".join(lines))

    # ── Card actions ─────────────────────────────────────────────────────────
    def _on_card_connect(self, device_id: str):
        card = self._device_cards.get(device_id)
        if not card:
            return
        address = card.connection_address()
        if not address:
            self._set_status("Bu cihazin baglanti adresi bulunamadi.", error=True)
            return
        self._inp_code.setText(address)
        self._inp_code.setFocus()
        self._set_status("Aktif cihazin adresi baglanti alanina eklendi.")

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

    def _connect_presence_channel(self, status_message: str | None = None):
        if self._logging_out:
            return
        if not (self._device_cards or load_paired_phone_id()):
            self._set_status(Ui.MSG_WAITING)
            return
        if status_message:
            self._set_status(status_message)
        self._manual_disconnect = True
        self._ws_client.connect_with_device_id(ServerDefaults.DEFAULT_URL, auto_pair=False)

    # ── Auto connect ─────────────────────────────────────────────────────────
    @pyqtSlot()
    def _try_auto_connect(self):
        paired_id = load_paired_phone_id()
        if paired_id or self._device_cards:
            self._paired_phone_id = paired_id
            self._refresh_home_summary()
            self._connect_presence_channel("Kayitli cihazlar kontrol ediliyor...")
        else:
            self._set_status(Ui.MSG_WAITING)

    # ── Connect button ───────────────────────────────────────────────────────
    @pyqtSlot()
    def _on_connect(self):
        raw_value = "".join(ch for ch in self._inp_code.text() if ch.isdigit())
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
        self._manual_disconnect = True
        self._btn_connect.setEnabled(False)
        self._set_status("Adres cozuldu, baglaniliyor...")
        self._paired_phone_id = partner_device_id
        self._ws_client.connect_with_device_id(
            ServerDefaults.DEFAULT_URL,
            preferred_partner_id=partner_device_id,
            auto_pair=True,
        )
        self._refresh_home_summary()

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
        self._manual_disconnect = True
        self._ws_client.disconnect()
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

    @pyqtSlot(str)
    def _on_ws_disconnected(self, reason: str):
        self._set_connected(False)
        self._switch_page(0)
        self._screen.clear_frame()
        for card in self._device_cards.values():
            card.set_online(False)
        self._online_paired_devices.clear()
        self._refresh_home_summary()
        if self._manual_disconnect:
            self._manual_disconnect = False
            self._btn_connect.setEnabled(True)
            return
        if "10060" in reason or "timed out" in reason.lower():
            self._set_status(Ui.MSG_DISCONNECT_TIMEOUT, error=True)
        elif "already closed" in reason.lower():
            self._set_status("Baglanti kapandi.", error=True)
        else:
            self._set_status(f"Baglanti kesildi: {reason}", error=True)
        self._btn_connect.setEnabled(True)
        QTimer.singleShot(1000, lambda: self._connect_presence_channel("Cihaz durumu yeniden baglaniyor..."))

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

        self._reflow_device_cards()
        online_count = sum(1 for d in self._device_cards if d in self._online_paired_devices)
        self._lbl_device_count.setText(
            f"{online_count} aktif / {len(self._device_cards)} cihaz" if self._device_cards else ""
        )
        self._refresh_home_summary()

    @pyqtSlot()
    def _on_peer_disconnected(self):
        self._mjpeg.stop()
        self._screen.clear_frame()
        self._set_connected(False)
        self._switch_page(0)
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
        self._btn_disconnect.setEnabled(connected)
        self._btn_rotate.setEnabled(connected)
        for btn in self._key_buttons:
            btn.setEnabled(connected)
        if connected:
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
        self._manual_disconnect = True
        self._ws_client.disconnect()
        self.db.close()
        super().closeEvent(event)
