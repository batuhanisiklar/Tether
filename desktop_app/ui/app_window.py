"""
MainWindow — Uzak Telefon Kontrol Masaüstü Uygulaması
======================================================
Uygulama ana penceresi. Yalnızca durum yönetimi, sinyal bağlama ve
UI kurulumu içerir. Olay işleyicileri handler mixin'lerinde tanımlıdır:

    • ui/handlers/ws_handlers.py        — WebSocket olayları
    • ui/handlers/stream_handlers.py    — Frame/MJPEG/audio/rotation
    • ui/handlers/profile_handlers.py   — Profil drawer iş mantığı
    • ui/handlers/device_handlers.py    — Cihaz yönetimi
    • ui/handlers/session_handlers.py   — Oturum/adres yönetimi
    • ui/handlers/screenshot_handlers.py — Ekran görüntüsü/pano

UI bileşenleri:
    • ui/pages/home_page.py      — Ana sayfa builder'ları
    • ui/pages/remote_page.py    — Remote sayfa builder'ları
    • ui/pages/profile_drawer.py — Profil drawer builder'ları
    • ui/components/             — DeviceCard, DraggableTitleBar, ConfirmDialog
    • ui/styles/app_styles.py    — Tüm stylesheet sabitleri
    • ui/utils.py                — Saf yardımcı fonksiyonlar
"""

import logging
import os

from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, pyqtSlot, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_app.config import AppMeta, ServerDefaults, Ui, Colors
from desktop_app.config.constants import Prefs, AndroidKeyCodes
from desktop_app.audio.player import DesktopAudioPlayer
from desktop_app.config.prefs_store import (
    load_auth_token,
    load_user_address,
    save_user_address,
    read_prefs,
    update_prefs,
)
from desktop_app.network.backend_api import BackendApi
from desktop_app.network.mjpeg_receiver import MjpegReceiver
from desktop_app.network.ws_client import WsClient
from desktop_app.ui.theme import card_style, text_style
from desktop_app.ui.styles.app_styles import (
    ACCOUNT_BTN_SS,
    GLOBAL_STYLESHEET,
    MAIN_FOOTER_BAR_HEIGHT,
    MAIN_NAV_BAR_HEIGHT,
    MAIN_SHELL_MARGIN,
    TAB_STYLE_ACTIVE,
    TAB_STYLE_INACTIVE,
    WIN_CHROME_BAR_HEIGHT,
    WIN_CLOSE_BTN_SS,
    WIN_TOOL_BTN_SS,
    _ACCENT,
    _BG,
    _BG_CARD,
    _BORDER,
    _BORDER_SUBTLE,
    _GREEN,
    _RED,
    _TEXT,
    _TEXT_DIM,
    _TEXT_SEC,
)
from desktop_app.ui.utils import address_digits, load_logo_pixmap, session_tab_label
from desktop_app.ui.components.device_card import DeviceCard
from desktop_app.ui.components.draggable_title_bar import DraggableTitleBar
from desktop_app.ui.pages.home_page import build_home_page
from desktop_app.ui.pages.remote_page import build_remote_page
from desktop_app.ui.pages.profile_drawer import build_profile_drawer

# ── Handler mixin'leri ────────────────────────────────────────────────────
from desktop_app.ui.handlers.ws_handlers import WsHandlersMixin
from desktop_app.ui.handlers.stream_handlers import StreamHandlersMixin
from desktop_app.ui.handlers.profile_handlers import ProfileHandlersMixin
from desktop_app.ui.handlers.device_handlers import DeviceHandlersMixin
from desktop_app.ui.handlers.session_handlers import SessionHandlersMixin
from desktop_app.ui.handlers.screenshot_handlers import ScreenshotHandlersMixin

logger = logging.getLogger(__name__)
_C = Colors


class DeviceLoadThread(QThread):
    finished_loading = pyqtSignal(list)

    def __init__(self, fetch_func, parent=None):
        super().__init__(parent)
        self.fetch_func = fetch_func

    def run(self):
        devices = self.fetch_func()
        self.finished_loading.emit(devices)


class MainWindow(
    WsHandlersMixin,
    StreamHandlersMixin,
    ProfileHandlersMixin,
    DeviceHandlersMixin,
    SessionHandlersMixin,
    ScreenshotHandlersMixin,
    QMainWindow,
):
    """
    Ana uygulama penceresi.
    __init__ → durum değişkenleri → UI kurulumu → sinyal bağlama → timer başlatma.
    """

    def __init__(self, backend_api: BackendApi | None = None):
        super().__init__()

        self._ws_client   = WsClient()
        self._mjpeg       = MjpegReceiver()
        self._backend_api = backend_api if backend_api is not None else BackendApi()

        self._connected                  = False
        self._rotation_step              = 0
        self._paired_phone_id: str | None = None
        self._paired_phone_address: str | None = None
        self._online_paired_devices: set[str]  = set()
        self._phone_accessibility_enabled: bool | None = None
        self._remote_frame_visible       = False
        self._logging_out                = False
        self._manual_disconnect          = False
        self._ws_mode                    = "idle"
        
        self._audio_player: DesktopAudioPlayer | None = None

        self._user_id: int | None = None
        self._username            = "Kullanıcı"
        self._user_email          = ""
        self._user_first_name     = ""
        self._user_last_name      = ""
        self._user_address        = ""
        self._auth_token          = ""

        self._current_page           = 0
        self._account_button: QPushButton | None = None
        self._device_cards: dict[str, DeviceCard] = {}

        self._reconnect_session_code: str | None = None
        self._a11y_pending_reconnect_code: str | None = None
        self._a11y_recovery_token: int = 0
        self._profile_drawer_open    = False
        self._profile_drawer_width   = 432
        self._profile_cache: dict    = {}
        self._profile_anim: QPropertyAnimation | None = None

        self._screen_capture_prompt_sent = False
        self._last_stream_size: tuple[int, int] = (0, 0)

        self.setWindowTitle(AppMeta.WINDOW_TITLE)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(1320, 920)

        self._load_user_prefs()
        self.setStyleSheet(GLOBAL_STYLESHEET)
        self._build_ui()
        self._connect_signals()

        self._presence_timer = QTimer(self)
        self._presence_timer.setInterval(8_000)
        self._presence_timer.timeout.connect(self._on_presence_tick)

        QTimer.singleShot(250, self._load_devices_from_db)
        
        self._audio_player = DesktopAudioPlayer(parent=self)

    # ── Preferences ───────────────────────────────────────────────────────

    def _load_user_prefs(self):
        prefs = read_prefs()
        self._user_id         = prefs.get("user_id")
        self._username        = prefs.get("username", "Kullanıcı")
        self._user_email      = (prefs.get(Prefs.KEY_USER_EMAIL) or "").strip()
        self._user_first_name = (prefs.get(Prefs.KEY_USER_FIRST_NAME) or "").strip()
        self._user_last_name  = (prefs.get(Prefs.KEY_USER_LAST_NAME) or "").strip()
        self._auth_token      = load_auth_token()
        self._user_address    = load_user_address()

        if self._auth_token:
            profile, _ = self._backend_api.get_me(self._auth_token, self._ws_client.device_id)
            if profile:
                self._user_address = address_digits(profile.get("address"))
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
                    self._user_last_name  = ln
                    update_prefs(**{Prefs.KEY_USER_FIRST_NAME: fn, Prefs.KEY_USER_LAST_NAME: ln})

        if not self._user_address and self._user_id:
            self._user_address = load_user_address() or ""
        if not self._user_email:
            self._user_email = self._username
        self._ws_client.set_auth_token(self._auth_token)
        self._ws_client.set_device_address(self._user_address)

    # ── UI Build ──────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(
            MAIN_SHELL_MARGIN, MAIN_SHELL_MARGIN,
            MAIN_SHELL_MARGIN, MAIN_SHELL_MARGIN,
        )
        outer.setSpacing(0)

        card = QFrame()
        card.setObjectName("main_shell_card")
        self._main_card = card
        card.setStyleSheet(
            f"QFrame#main_shell_card {{ {card_style(background=_C.BG_SURFACE)} }}"
        )
        outer.addWidget(card, stretch=1)

        root = QVBoxLayout(card)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_chrome_bar())
        root.addWidget(self._build_nav_bar())

        self._pages = QStackedWidget()
        self._pages.addWidget(build_home_page(self))
        self._pages.addWidget(build_remote_page(self))
        root.addWidget(self._pages, stretch=1)

        root.addWidget(self._build_footer_bar())

        self._profile_drawer = build_profile_drawer(self, getattr(self, "_main_card", central))
        self._profile_drawer.hide()

    def _build_chrome_bar(self) -> QWidget:
        bar = DraggableTitleBar(self)
        bar.setFixedHeight(WIN_CHROME_BAR_HEIGHT)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {_BG_CARD};
                border-bottom: 1px solid {_BORDER};
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
        pm = load_logo_pixmap(18)
        if pm is not None:
            mini.setPixmap(pm)
        else:
            mini.setStyleSheet(
                f"background-color: {_ACCENT}; border-radius: 4px;"
                f" font-size: 9px; color: #1A1A1A; font-weight: 800;"
            )
            mini.setText("R")
        lay.addWidget(mini)

        lbl = QLabel(AppMeta.NAME)
        lbl.setStyleSheet(text_style(_C.TEXT_MUTED, size=11))
        lay.addWidget(lbl)
        lay.addStretch()

        self._btn_win_min = QPushButton("−")
        self._btn_win_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_win_min.setStyleSheet(WIN_TOOL_BTN_SS)
        self._btn_win_min.setToolTip("Simge durumuna küçült")
        self._btn_win_min.clicked.connect(self.showMinimized)
        lay.addWidget(self._btn_win_min)

        self._btn_win_close = QPushButton("×")
        self._btn_win_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_win_close.setStyleSheet(WIN_CLOSE_BTN_SS)
        self._btn_win_close.setToolTip("Kapat")
        self._btn_win_close.clicked.connect(self.close)
        lay.addWidget(self._btn_win_close)

        return bar

    def _build_nav_bar(self) -> QWidget:
        bar = QFrame()
        bar.setFixedHeight(MAIN_NAV_BAR_HEIGHT)
        bar.setStyleSheet(
            f"background-color: {_BG}; border-bottom: 1px solid {_BORDER_SUBTLE};"
        )
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
        self._tab_home.setStyleSheet(TAB_STYLE_ACTIVE)
        self._tab_home.clicked.connect(lambda: self._switch_page(0))
        lay.addWidget(self._tab_home)

        self._tab_session = QFrame()
        tsl = QHBoxLayout(self._tab_session)
        tsl.setContentsMargins(0, 0, 0, 0)
        tsl.setSpacing(0)

        self._tab_session_btn = QPushButton("Oturum")
        self._tab_session_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_session_btn.setStyleSheet(TAB_STYLE_INACTIVE)
        self._tab_session_btn.clicked.connect(lambda: self._switch_page(1))
        tsl.addWidget(self._tab_session_btn)

        self._tab_session_close = QPushButton("×")
        self._tab_session_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_session_close.setFixedSize(20, 20)
        self._tab_session_close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {_TEXT_DIM}; border: none;
                font-size: 13px; font-weight: 700; }}
            QPushButton:hover {{ color: {_RED}; }}
        """)
        self._tab_session_close.setToolTip("Bağlantıyı kes")
        self._tab_session_close.clicked.connect(self._on_disconnect)
        tsl.addWidget(self._tab_session_close)

        self._tab_session.hide()
        lay.addWidget(self._tab_session)
        lay.addStretch()

        self._header_status_dot = QFrame()
        self._header_status_dot.setFixedSize(8, 8)
        self._header_status_dot.setStyleSheet(
            f"background-color: {_TEXT_DIM}; border-radius: 4px;"
        )
        lay.addWidget(self._header_status_dot)
        lay.addSpacing(6)

        self._account_button = QPushButton(
            f"{self._user_email or self._username}  ▾"
        )
        self._account_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._account_button.setFixedHeight(26)
        self._account_button.setStyleSheet(ACCOUNT_BTN_SS)
        self._account_button.clicked.connect(self._show_account_menu)
        lay.addWidget(self._account_button)

        return bar

    def _build_footer_bar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(MAIN_FOOTER_BAR_HEIGHT)
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

    # ── Signal Connections ────────────────────────────────────────────────

    def _connect_signals(self):
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)

        self._ws_client.connected.connect(self._on_ws_connected)
        self._ws_client.disconnected.connect(self._on_ws_disconnected)
        self._ws_client.paired.connect(self._on_paired)
        self._ws_client.peer_disconnected.connect(self._on_peer_disconnected)
        self._ws_client.error_occurred.connect(self._on_error)
        self._ws_client.paired_devices_status.connect(
            self._on_paired_devices_status, Qt.ConnectionType.QueuedConnection
        )
        self._ws_client.frame_received.connect(
            self._on_frame_received, Qt.ConnectionType.QueuedConnection
        )
        self._ws_client.audio_received.connect(
            self._on_audio_received, Qt.ConnectionType.QueuedConnection
        )
        self._ws_client.rotation_received.connect(
            self._on_rotation_received, Qt.ConnectionType.QueuedConnection
        )
        self._ws_client.reconnecting.connect(
            self._on_reconnecting, Qt.ConnectionType.QueuedConnection
        )

        self._mjpeg.frame_ready.connect(self._on_mjpeg_frame)
        self._mjpeg.error_occurred.connect(self._on_mjpeg_error)
        self._mjpeg.stream_stopped.connect(self._on_stream_stopped)

        self._screen.touch_event.connect(self._on_touch)
        self._screen.swipe_event.connect(self._on_swipe)
        self._screen.remote_key_pressed.connect(self._on_screen_remote_key)

    # ── Page Navigation ──────────────────────────────────────────────────

    def _switch_page(self, index: int):
        self._current_page = index
        self._pages.setCurrentIndex(index)
        if index == 0:
            self._tab_home.setStyleSheet(TAB_STYLE_ACTIVE)
            self._tab_session_btn.setStyleSheet(TAB_STYLE_INACTIVE)
        else:
            self._tab_home.setStyleSheet(TAB_STYLE_INACTIVE)
            self._tab_session_btn.setStyleSheet(TAB_STYLE_ACTIVE)

    # ── Device Loading ────────────────────────────────────────────────────

    @pyqtSlot()
    def _load_devices_from_db(self):
        if hasattr(self, "_device_loader") and self._device_loader.isRunning():
            return
        self._device_loader = DeviceLoadThread(self._load_paired_devices, self)
        self._device_loader.finished_loading.connect(self._on_devices_loaded)
        self._device_loader.start()

    @pyqtSlot(list)
    def _on_devices_loaded(self, devices: list):
        self._populate_device_cards(devices)
        if self._ws_mode == "session":
            logger.debug("Cihaz listesi güncellendi; uzak oturum varken presence WS açılmadı")
            return
        if not self._ws_client._ws:
            self._connect_presence_channel("Cihaz durumu izleniyor...")
        self._refresh_home_summary()

    # ── Home Summary / Status ─────────────────────────────────────────────

    def _refresh_home_summary(self):
        if self._connected:
            self._addr_status_label.setText("Bağlı")
            self._hero_status_label.setText("  Aktif bağlantı var")
            self._hero_status_label.setStyleSheet(f"color: {_GREEN}; font-size: 12px;")
        else:
            self._addr_status_label.setText("Hazır")
            online = len(self._online_paired_devices)
            if online:
                self._hero_status_label.setText(f"  {online} cihaz çevrimiçi")
                self._hero_status_label.setStyleSheet(f"color: {_GREEN}; font-size: 12px;")
            else:
                self._hero_status_label.setText("  Bağlantı bekleniyor")
                self._hero_status_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")

        active_card = None
        if self._paired_phone_id:
            active_card = self._device_cards.get(str(self._paired_phone_id))
        if active_card is None and self._paired_phone_address:
            addr = address_digits(self._paired_phone_address)
            active_card = next(
                (c for c in self._device_cards.values() if c.address == addr), None
            )

        if self._connected and (active_card or self._paired_phone_id):
            if active_card:
                label = session_tab_label(
                    active_card.owner_name,
                    active_card.display_name(),
                    active_card.address,
                )
            else:
                label = session_tab_label(
                    None,
                    f"...{self._paired_phone_id[-8:]}",
                    self._paired_phone_address,
                )
            self._tab_session_btn.setText(f"  {label}")
            self._tab_session.show()
        else:
            self._tab_session.hide()

        if self._account_button is not None:
            acct = (
                f"{self._user_first_name} {self._user_last_name}".strip()
                or self._user_email
                or self._username
            )
            self._account_button.setText(f"{acct}  ▾")

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

    # ── Account Menu ──────────────────────────────────────────────────────

    def _show_account_menu(self):
        if self._account_button is None:
            return
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {_BG_CARD}; color: {_TEXT};
                border: 1px solid {_BORDER}; padding: 4px;
            }}
            QMenu::item {{ padding: 8px 20px; }}
            QMenu::item:selected {{ background-color: #333; }}
            QMenu::separator {{
                height: 1px; background: {_BORDER_SUBTLE}; margin: 4px 8px;
            }}
        """)
        profile_action = menu.addAction("Profil")
        menu.addSeparator()
        logout_action = menu.addAction("Çıkış yap")
        selected = menu.exec(
            self._account_button.mapToGlobal(
                self._account_button.rect().bottomLeft()
            )
        )
        if selected == profile_action:
            self._open_profile_drawer()
        elif selected == logout_action:
            self._on_logout()

    # ── Input Events ──────────────────────────────────────────────────────

    @pyqtSlot(float, float)
    def _on_touch(self, x: float, y: float):
        if self._connected:
            self._ws_client.send_touch(x, y)

    @pyqtSlot(float, float, float, float)
    def _on_swipe(self, x1, y1, x2, y2):
        if self._connected:
            self._ws_client.send_swipe(x1, y1, x2, y2)

    def _on_screen_remote_key(self, key_code: int) -> None:
        if self._connected:
            self._ws_client.send_key_event(int(key_code))
            if self._audio_player is not None:
                self._audio_player.adjust_for_android_key(
                    int(key_code),
                    volume_up=AndroidKeyCodes.VOL_UP,
                    volume_down=AndroidKeyCodes.VOL_DOWN,
                    volume_mute=AndroidKeyCodes.VOL_MUTE,
                )

    def _set_remote_controls_enabled(self, enabled: bool) -> None:
        for btn in getattr(self, "_key_buttons", []):
            btn.setEnabled(enabled)
        for attr in ("_btn_sess_clip", "_btn_sess_save", "_btn_sess_paste"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setEnabled(enabled)

    # ── Presence ──────────────────────────────────────────────────────────

    def _on_presence_tick(self):
        self._ws_client.send_request_presence()

    # ── Connected State ───────────────────────────────────────────────────

    def _set_connected(self, connected: bool):
        self._connected = connected
        if not connected:
            self._screen_capture_prompt_sent = False
            self._sync_stream_aspect_fit()
            if self._audio_player is not None:
                self._audio_player.reset()
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

    # ── Resize / Close ────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_profile_drawer"):
            top, dh, cw_w = self._profile_drawer_geometry()
            self._profile_drawer.setFixedHeight(dh)
            x = (cw_w - self._profile_drawer_width) if self._profile_drawer_open else cw_w
            self._profile_drawer.move(x, top)

    def closeEvent(self, event):
        self._mjpeg.stop()
        self._presence_timer.stop()
        self._manual_disconnect = True
        self._ws_client.disconnect()
        super().closeEvent(event)
