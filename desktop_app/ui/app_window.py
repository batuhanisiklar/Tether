"""
MainWindow — Uzak Telefon Kontrol Masaüstü Uygulaması
======================================================
Uygulama ana penceresi. Yalnızca durum yönetimi, sinyal bağlama ve
WS/MJPEG/UI olay işleyicilerini içerir.

UI bileşenleri ayrı modüllerdedir:
    • ui/pages/home_page.py      — Ana sayfa builder'ları
    • ui/pages/remote_page.py    — Remote sayfa builder'ları
    • ui/pages/profile_drawer.py — Profil drawer builder'ları
    • ui/components/             — DeviceCard, DraggableTitleBar
    • ui/styles/app_styles.py    — Tüm stylesheet sabitleri
    • ui/utils.py                — Saf yardımcı fonksiyonlar
"""

import logging
import os

from PyQt6.QtCore import Qt, QPoint, QTimer, QPropertyAnimation, QEasingCurve, pyqtSlot, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtMultimedia import QAudio, QAudioSink, QAudioFormat, QMediaDevices
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QFileDialog,
)

from desktop_app.config import AppMeta, ServerDefaults, Ui, Colors
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
from desktop_app.ui.theme import (
    card_style,
    filled_button_style,
    line_edit_style,
    outline_button_style,
    text_style,
)

from desktop_app.ui.styles.app_styles import (
    ACCOUNT_BTN_SS,
    GLOBAL_STYLESHEET,
    MAIN_FOOTER_BAR_HEIGHT,
    MAIN_NAV_BAR_HEIGHT,
    MAIN_SHELL_MARGIN,
    PROFILE_DRAWER_BOTTOM_GAP,
    PROFILE_DRAWER_TOP_OFFSET,
    TAB_STYLE_ACTIVE,
    TAB_STYLE_INACTIVE,
    WIN_CHROME_BAR_HEIGHT,
    WIN_CLOSE_BTN_SS,
    WIN_TOOL_BTN_SS,
    _ACCENT,
    _BG,
    _BG_CARD,
    _BG_INPUT,
    _BG_RAISED,
    _BORDER,
    _BORDER_SUBTLE,
    _GREEN,
    _RED,
    _TEXT,
    _TEXT_DIM,
    _TEXT_SEC,
)

from desktop_app.ui.utils import (
    address_digits,
    cursor_for_digit_count,
    digits_before_cursor,
    format_address,
    is_accessibility_ws_error,
    merge_phone_device_row,
    phone_row_key,
    session_tab_label,
    ws_device_id_set,
)

from desktop_app.ui.components.device_card import DeviceCard
from desktop_app.ui.components.draggable_title_bar import DraggableTitleBar

from desktop_app.ui.pages.home_page import build_home_page
from desktop_app.ui.pages.remote_page import build_remote_page
from desktop_app.ui.pages.profile_drawer import build_profile_drawer

logger = logging.getLogger(__name__)
_C = Colors


class AudioJitterBuffer:
    """
    Basit ring buffer — ağ titreşimini (jitter) emerek ses çıkışını düzgünleştirir.
    İlk `pre_buffer_ms` kadar PCM biriktirir, ardından gelen her chunk'ı derhal döndürür.
    """

    def __init__(self, pre_buffer_ms: int = 100, sample_rate: int = 16000, channels: int = 1, sample_bytes: int = 2):
        self._pre_buffer_bytes = int(sample_rate * channels * sample_bytes * (pre_buffer_ms / 1000))
        self._buffer = bytearray()
        self._started = False

    def push(self, pcm: bytes) -> bytes | None:
        """PCM verisini ekle; oynatmaya hazırsa bytes döndürür, değilse None."""
        self._buffer.extend(pcm)
        if not self._started:
            if len(self._buffer) >= self._pre_buffer_bytes:
                self._started = True
                chunk = bytes(self._buffer)
                self._buffer.clear()
                return chunk
            return None
        chunk = bytes(self._buffer)
        self._buffer.clear()
        return chunk

    def reset(self):
        """Bağlantı kesildiğinde veya akış durduğunda sıfırla."""
        self._buffer.clear()
        self._started = False


class DeviceLoadThread(QThread):
    finished_loading = pyqtSignal(list)

    def __init__(self, fetch_func, parent=None):
        super().__init__(parent)
        self.fetch_func = fetch_func

    def run(self):
        devices = self.fetch_func()
        self.finished_loading.emit(devices)


class MainWindow(QMainWindow):
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
        
        self._audio_sink = None
        self._audio_device = None
        self._audio_jitter = AudioJitterBuffer(pre_buffer_ms=60, sample_rate=16000)

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
        self._fps_frame_counter          = 0
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

        self._fps_histogram_timer = QTimer(self)
        self._fps_histogram_timer.setInterval(1000)
        self._fps_histogram_timer.timeout.connect(self._tick_stream_fps_label)

        QTimer.singleShot(250, self._load_devices_from_db)
        
        self._init_audio_player()

    def _init_audio_player(self):
        try:
            format = QAudioFormat()
            format.setSampleRate(16000)
            format.setChannelCount(1)
            format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            
            default_device = QMediaDevices.defaultAudioOutput()
            if not default_device.isNull():
                self._audio_sink = QAudioSink(default_device, format, self)
                self._audio_device = self._audio_sink.start()
            else:
                logger.warning("No default audio output device found.")
        except Exception as e:
            logger.error("Audio player baslatilamadi: %s", e, exc_info=True)

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
        self._ws_client.set_device_address(self._user_address)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(
            MAIN_SHELL_MARGIN, MAIN_SHELL_MARGIN,
            MAIN_SHELL_MARGIN, MAIN_SHELL_MARGIN,
        )
        outer.setSpacing(0)

        card = QFrame(objectName="main_shell_card")
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
        pm = self._load_logo_pixmap(18)
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

    def _load_logo_pixmap(self, size: int) -> QPixmap | None:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        logo_path = os.path.join(root, "logo.png")
        pm = QPixmap(logo_path)
        if pm.isNull():
            return None
        return pm.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

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

    def _switch_page(self, index: int):
        self._current_page = index
        self._pages.setCurrentIndex(index)
        if index == 0:
            self._tab_home.setStyleSheet(TAB_STYLE_ACTIVE)
            self._tab_session_btn.setStyleSheet(TAB_STYLE_INACTIVE)
        else:
            self._tab_home.setStyleSheet(TAB_STYLE_INACTIVE)
            self._tab_session_btn.setStyleSheet(TAB_STYLE_ACTIVE)

    def _connect_presence_mode(self, status_message: str | None = None):
        if self._logging_out:
            return
        if self._ws_mode == "session" and self._connected:
            logger.info("Presence baglantisi atlandi: aktif uzak oturum korunuyor")
            return
        self._ws_mode = "presence"
        self._mjpeg.stop()
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
        addr_digits = address_digits(partner_address or "")
        if not partner_device_id and not addr_digits:
            return
        self._a11y_recovery_token += 1
        self._ws_mode = "session"
        self._mjpeg.stop()
        self._rotation_step = 0
        self._apply_rotation_step()
        self._paired_phone_id      = partner_device_id
        self._paired_phone_address = addr_digits or None
        self._presence_timer.stop()
        if status_message:
            self._set_status(status_message)
        self._manual_disconnect = True
        if addr_digits:
            save_paired_phone_address(addr_digits)
        session_code = addr_digits or address_digits(partner_device_id or "")
        if not session_code:
            return
        self._ws_client.connect_to_server(ServerDefaults.DEFAULT_URL, session_code)

    def _connect_presence_channel(self, status_message: str | None = None):
        self._connect_presence_mode(status_message)

    def _schedule_reconnect(self, delay_ms: int = 1500):
        if self._logging_out:
            return

    def _load_paired_devices(self) -> list[dict]:
        merged: dict[str, dict] = {}
        pc_id = self._ws_client.device_id

        def _ingest(rows: list[dict] | None) -> None:
            for device in rows or []:
                if device.get("device_type") != "phone" or device.get("device_id") == pc_id:
                    continue
                key = phone_row_key(device)
                if not key:
                    continue
                merged[key] = merge_phone_device_row(merged.get(key, {}), dict(device))

        if self._auth_token:
            bundle, bundle_err = self._backend_api.get_phone_device_bundle(
                self._auth_token, pc_id
            )
            if bundle and bundle.get("ok"):
                _ingest(list(bundle.get("devices") or []))
                _ingest(list(bundle.get("recent_devices") or []))
                _ingest(list(bundle.get("pairings") or []))
                return list(merged.values()) if merged else []
            if bundle_err and bundle_err != "bundle_missing":
                logger.warning("phone-bundle alinamadi: %s", bundle_err)

            devices, err = self._backend_api.get_devices(self._auth_token)
            if devices is not None:
                _ingest(devices)
            else:
                logger.warning("Server devices alinamadi: %s", err)

            recent, err = self._backend_api.get_recent_devices(self._auth_token, "phone")
            if recent is not None:
                _ingest(recent)
            else:
                logger.warning("Server recent devices alinamadi: %s", err)

            pairings, err = self._backend_api.get_pairings(self._auth_token, pc_id)
            if pairings is not None:
                _ingest(pairings)
            else:
                if "Bu cihaza erisim yetkiniz yok" in (err or ""):
                    logger.warning("Pairings yetkisiz (oturum sifirlanacak): %s", err)
                    clear_logged_in()
                    self._auth_token = ""
                    return []
                logger.warning("Server pairings alinamadi: %s", err)

            return list(merged.values()) if merged else []
        return []

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

    def _populate_device_cards(self, devices: list[dict]):
        for card in self._device_cards.values():
            self._recent_devices_layout.removeWidget(card)
            card.deleteLater()
        self._device_cards.clear()

        db_online = {
            str(d["device_id"]) for d in devices if bool(d.get("is_online"))
        }
        self._online_paired_devices = set(db_online)

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
            key = card.card_key()
            card.set_online(key in self._online_paired_devices)
            card.set_connect_callback(self._on_card_connect)
            card.set_forget_callback(self._on_card_forget)
            self._device_cards[key] = card

        online_count = sum(
            1 for d in devices if str(d["device_id"]) in self._online_paired_devices
        )
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
            self._addr_status_label.setText("Bağlı")
            self._hero_status_label.setText("  Aktif baglanti var")
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

    def _open_profile_drawer(self) -> None:
        if not self._auth_token:
            self._set_status("Profil bilgilerine erişmek için tekrar giriş yapın.", error=True)
            return
        self._profile_err.setText("")

        profile, err = self._backend_api.get_me(self._auth_token, self._ws_client.device_id)
        self._profile_cache = dict(profile) if profile else {}
        self._profile_load_err.hide()
        self._profile_load_err.setText("")
        if err:
            self._profile_load_err.setText(err)
            self._profile_load_err.show()

        if profile:
            fn   = str(profile.get("first_name") or "").strip()
            ln   = str(profile.get("last_name") or "").strip()
            em   = str(profile.get("email") or self._user_email or "").strip()
            ph   = str(profile.get("phone") or "").strip()
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
            full   = f"{fn} {ln}".strip() or "—"
            self._profile_view_name.setText(full)
            self._profile_view_email.setText(self._user_email or "—")
            self._profile_view_phone.setText("—")
            self._profile_readonly_name.setText(full)
            self._profile_inp_email.setText(self._user_email or "")
            self._profile_inp_phone.setText("")
            self._profile_avatar_lbl.setText(
                self._profile_initials(fn, ln, self._user_email)
            )

        self._profile_inp_old.setText("")
        self._profile_inp_pwd1.setText("")
        self._profile_inp_pwd2.setText("")
        self._set_profile_drawer_open(True)
        self._set_profile_panel(None)

    @staticmethod
    def _profile_initials(first_name: str, last_name: str, email: str) -> str:
        a = (first_name or "").strip()[:1].upper()
        b = (last_name  or "").strip()[:1].upper()
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
            ln = (self._user_last_name  or "").strip()
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
        self._profile_err.setText("")
        self._profile_pwd_err.setText("")
        self._profile_edit_block.setVisible(which == "edit")
        self._profile_pwd_block.setVisible(which == "password")
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
        cw = getattr(self, "_main_card", self.centralWidget())
        if cw is None:
            return 0, 160, self.width()
        top = WIN_CHROME_BAR_HEIGHT + MAIN_NAV_BAR_HEIGHT
        bottom_gap = MAIN_FOOTER_BAR_HEIGHT
        inner_h = cw.height() - top - bottom_gap
        return top, max(160, inner_h), cw.width()

    def _set_profile_drawer_open(self, open_: bool) -> None:
        if self._profile_drawer_open == open_:
            return
        self._profile_drawer_open = open_

        top, drawer_h, cw_w = self._profile_drawer_geometry()
        self._profile_drawer.setFixedHeight(drawer_h)

        start_x = cw_w if open_ else (cw_w - self._profile_drawer_width)
        end_x   = (cw_w - self._profile_drawer_width) if open_ else cw_w

        if open_:
            self._profile_drawer.show()
            self._profile_drawer.raise_()

        start_pos = QPoint(start_x, top)
        end_pos   = QPoint(end_x, top)
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
        anim.finished.connect(
            lambda: self._profile_drawer.hide() if not self._profile_drawer_open else None
        )
        self._profile_anim = anim
        anim.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_profile_drawer"):
            top, dh, cw_w = self._profile_drawer_geometry()
            self._profile_drawer.setFixedHeight(dh)
            x = (cw_w - self._profile_drawer_width) if self._profile_drawer_open else cw_w
            self._profile_drawer.move(x, top)

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
            self._auth_token, email=em, phone=phone,
            old_password=None, password=None, password2=None,
        )
        if err:
            self._profile_err.setText(err)
            return

        user  = (data or {}).get("user") or {}
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
            self._user_last_name  = ln
            update_prefs(**{Prefs.KEY_USER_FIRST_NAME: fn, Prefs.KEY_USER_LAST_NAME: ln})

        self._profile_cache = dict(user)
        full    = f"{fn} {ln}".strip() or "—"
        ph_disp = str(user.get("phone") or phone or "").strip()
        self._profile_view_name.setText(full)
        self._profile_view_email.setText(new_email or "—")
        self._profile_view_phone.setText(ph_disp or "—")
        self._profile_readonly_name.setText(full)
        self._profile_avatar_lbl.setText(self._profile_initials(fn, ln, new_email))
        self._set_status("Profil güncellendi.")
        self._refresh_home_summary()
        self._close_profile_drawer()

    def _save_password_from_drawer(self) -> None:
        if not self._auth_token:
            self._profile_pwd_err.setText("Oturum bulunamadi. Tekrar giris yapin.")
            return
        oldp = self._profile_inp_old.text()
        p1   = self._profile_inp_pwd1.text()
        p2   = self._profile_inp_pwd2.text()
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
            self._profile_pwd_err.setText("Şifre en az 6 karakter olmalıdır.")
            return

        email = (self._profile_inp_email.text() or "").strip().lower() or self._user_email
        phone = (self._profile_inp_phone.text() or "").strip()
        data, err = self._backend_api.update_profile(
            self._auth_token, email=email, phone=phone,
            old_password=oldp, password=p1, password2=p2,
        )
        if err:
            self._profile_pwd_err.setText(err)
            return
        token = str((data or {}).get("token") or "")
        if token:
            self._auth_token = token
            update_prefs(**{Prefs.KEY_AUTH_TOKEN: token})
        self._set_status("Şifre güncellendi.")
        self._on_profile_pwd_cancel()

    def _on_card_connect(self, card_key: str):
        card = self._device_cards.get(card_key)
        if not card:
            return
        addr = card.connection_address()
        if not card.is_online():
            self._set_status("Bu cihaz su an çevrimiçi degil.", error=True)
            return
        if addr:
            self._inp_code.setText(addr)
            self._inp_code.setFocus()
            self._paired_phone_address = address_digits(addr)
        self._paired_phone_id = card.device_id
        label = session_tab_label(card.owner_name, card.display_name(), card.address)
        self._tab_session_btn.setText(f"  {label}")
        self._tab_session.show()
        self._switch_page(1)
        self._connect_session_mode(
            partner_device_id=None if addr else card.device_id,
            partner_address=addr,
            status_message="Secilen cihaza baglaniliyor...",
        )

    def _on_card_forget(self, card_key: str):
        card = self._device_cards.get(card_key)
        if not card:
            return
        if not self._confirm_forget_pairing(card.display_name()):
            return
        if not self._auth_token:
            self._set_status("Eslesmeyi sunucudan silmek icin tekrar giris yapin.", error=True)
            return

        success, error_msg = self._backend_api.delete_pairing(
            self._auth_token, self._ws_client.device_id, card.device_id, card.address,
        )
        if not success:
            self._set_status(error_msg or "Eslesme silinemedi.", error=True)
            return

        self._load_devices_from_db()
        self._online_paired_devices.discard(str(card.device_id))

        if self._paired_phone_address == card.address or self._paired_phone_id == card.device_id:
            self._paired_phone_id      = None
            self._paired_phone_address = None
            clear_paired_phone_address()
            clear_paired_phone_id()
            self._ws_client.forget_paired_phone()
            self._on_disconnect()
            return

        self._ws_client.send_request_presence()
        self._refresh_home_summary()
        self._set_status("Eslesme kaldirildi.")

    def _confirm_forget_pairing(self, device_label: str) -> bool:
        dialog = QDialog(self)
        dialog.setModal(True)
        dialog.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.CustomizeWindowHint
        )
        dialog.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        dialog.setMinimumWidth(420)
        dialog.setStyleSheet(f"""
            QDialog {{
                background: transparent;
            }}
            QLabel {{
                background: transparent;
            }}
            QPushButton {{
                min-height: 40px;
                border-radius: 10px;
                padding: 0 16px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton#cancelButton {{
                background-color: {_BG_RAISED};
                color: {_TEXT};
                border: 1px solid {_BORDER};
            }}
            QPushButton#cancelButton:hover {{
                border-color: {_ACCENT};
            }}
            QPushButton#confirmButton {{
                color: #1A1A1A;
                border: 1px solid rgba(255,138,128,0.55);
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #FF8A80,
                    stop:1 #FF6E6E
                );
            }}
            QPushButton#confirmButton:hover {{
                border: 1px solid rgba(255,165,156,0.75);
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #FF9C93,
                    stop:1 #FF7C7C
                );
            }}
            QPushButton#confirmButton:pressed {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #F07F77,
                    stop:1 #E56767
                );
            }}
        """)

        root = QVBoxLayout(dialog)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(0)

        card = QFrame()
        card.setObjectName("forgetPairCard")
        card.setStyleSheet(f"""
            QFrame#forgetPairCard {{
                background-color: {_BG_CARD};
                border: 1px solid {_BORDER_SUBTLE};
                border-radius: 16px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 150))
        card.setGraphicsEffect(shadow)
        root.addWidget(card)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 22, 22, 18)
        card_layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(14)

        icon = QLabel("!")
        icon.setFixedSize(38, 38)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            "background-color: rgba(248,113,113,0.16);"
            "color: #f87171;"
            "border: 1px solid rgba(248,113,113,0.38);"
            "border-radius: 19px;"
            "font-size: 18px;"
            "font-weight: 800;"
        )
        header.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)

        copy = QVBoxLayout()
        copy.setSpacing(6)

        title = QLabel("Eslesmeyi kaldir?")
        title.setStyleSheet(f"color: {_TEXT}; font-size: 18px; font-weight: 800;")
        copy.addWidget(title)

        body = QLabel(
            "Bu islem mevcut cihaz eslesmesini kaldirir. Devam etmek istiyor musun?"
        )
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px;")
        copy.addWidget(body)

        if device_label:
            caption = QLabel(device_label)
            caption.setWordWrap(True)
            caption.setStyleSheet(
                f"color: {_ACCENT}; font-size: 11px; font-weight: 700;"
                f"background-color: rgba(232,93,58,0.10);"
                f"border: 1px solid rgba(232,93,58,0.24);"
                f"border-radius: 8px; padding: 8px 10px;"
            )
            copy.addWidget(caption)

        header.addLayout(copy, stretch=1)
        card_layout.addLayout(header)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)

        cancel_btn = QPushButton("Iptal")
        cancel_btn.setObjectName("cancelButton")
        cancel_btn.clicked.connect(dialog.reject)
        actions.addWidget(cancel_btn)

        confirm_btn = QPushButton("Eslesmeyi Kaldir")
        confirm_btn.setObjectName("confirmButton")
        confirm_btn.clicked.connect(dialog.accept)
        confirm_btn.setDefault(True)
        actions.addWidget(confirm_btn)

        card_layout.addLayout(actions)
        return dialog.exec() == QDialog.DialogCode.Accepted
    def _submit_static_address(self, raw_value: str) -> None:
        if not raw_value:
            self._set_status("Adres girilmedi.", error=True)
            return
        if not raw_value.isdigit():
            self._set_status("Adres yalnızca rakamlardan oluşmalıdır.", error=True)
            return
        if len(raw_value) != 12:
            self._set_status("Lütfen 12 haneli sabit adresi girin.", error=True)
            return

        self._manual_disconnect = True
        self._btn_connect.setEnabled(False)
        self._set_status("Cihaz adresine baglaniliyor...")

        matching_card = next(
            (c for c in self._device_cards.values()
             if (c.connection_address() or "") == format_address(raw_value)),
            None,
        )
        self._paired_phone_id      = matching_card.device_id if matching_card else None
        self._paired_phone_address = raw_value
        save_paired_phone_address(raw_value)

        if matching_card:
            label = session_tab_label(
                matching_card.owner_name, matching_card.display_name(), matching_card.address
            )
        else:
            label = session_tab_label(None, "Bağlanıyor", raw_value)
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
        self._submit_static_address(
            "".join(ch for ch in self._inp_code.text() if ch.isdigit())
        )

    @pyqtSlot(str)
    def _on_address_text_changed(self, text: str):
        digits    = "".join(ch for ch in text if ch.isdigit())[:12]
        formatted = format_address(digits)
        if text != formatted:
            old_cursor = self._inp_code.cursorPosition()
            digit_pos  = digits_before_cursor(text, old_cursor)
            self._inp_code.blockSignals(True)
            self._inp_code.setText(formatted)
            self._inp_code.blockSignals(False)
            self._inp_code.setCursorPosition(cursor_for_digit_count(formatted, digit_pos))

    @pyqtSlot()
    def _on_disconnect(self):
        self._a11y_recovery_token += 1
        self._ws_mode                     = "presence"
        self._reconnect_session_code      = None
        self._a11y_pending_reconnect_code = None
        self._rotation_step               = 0
        self._presence_timer.stop()
        self._manual_disconnect = True
        self._mjpeg.stop()
        self._ws_client.disconnect(send_logout=True)
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
        self._a11y_recovery_token += 1
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

    def _on_presence_tick(self):
        self._ws_client.send_request_presence()

    @pyqtSlot()
    def _on_ws_connected(self):
        self._manual_disconnect = False
        self._set_status(Ui.MSG_SERVER_CONNECTED)
        self._btn_disconnect.setEnabled(True)
        if self._ws_mode == "presence":
            if not self._presence_timer.isActive():
                self._presence_timer.start()
            self._load_devices_from_db()
            self._ws_client.send_request_presence()
        else:
            self._presence_timer.stop()

    @pyqtSlot(str)
    def _on_ws_disconnected(self, reason: str):
        was_manual        = self._manual_disconnect
        was_remote        = self._ws_mode == "session" and self._connected
        restore_digits    = ""

        if was_remote and not was_manual:
            restore_digits = address_digits(self._paired_phone_address or "")
            if len(restore_digits) != 12:
                restore_digits = address_digits(load_paired_phone_address() or "")
            if len(restore_digits) != 12:
                restore_digits = address_digits(self._ws_client.join_session_code or "")

        self._reconnect_session_code = restore_digits if (was_remote and not was_manual and len(restore_digits) == 12) else None
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
        for card in self._device_cards.values():
            card.set_online(False)
        self._online_paired_devices.clear()
        self._refresh_home_summary()

        if "10060" in reason or "timed out" in reason.lower():
            self._set_status(Ui.MSG_DISCONNECT_TIMEOUT, error=True)
        elif "already closed" in reason.lower():
            self._set_status("Bağlantı kapandı.", error=True)
        else:
            self._set_status(f"Bağlantı kesildi: {reason}", error=True)
        self._schedule_reconnect()

    @pyqtSlot(str)
    def _on_paired(self, stream_url: str):
        already_streaming = self._connected and self._remote_frame_visible

        su       = (stream_url or "").strip()
        su_lower = su.lower()
        mjpeg_unreachable = (
            not su.startswith("http")
            or "0.0.0.0" in su or "10.0.2." in su
            or "127.0.0.1" in su_lower or "localhost" in su_lower
        )

        same_url = (
            su and not mjpeg_unreachable
            and hasattr(self._mjpeg, '_url')
            and self._mjpeg._url == su
            and self._mjpeg._thread is not None
            and self._mjpeg._thread.is_alive()
        )
        if already_streaming and same_url:
            logger.debug("Tekrarlayan paired/stream_info sinyali — akış zaten aktif, yoksayıldı")
            return

        if not already_streaming:
            self._remote_frame_visible = False

        paired_phone_id      = load_paired_phone_id()
        paired_phone_address = load_paired_phone_address()

        if paired_phone_id or paired_phone_address:
            pid  = str(paired_phone_id) if paired_phone_id else ""
            addr = address_digits(paired_phone_address) if paired_phone_address else ""
            missing = (pid and pid not in self._device_cards) or (
                bool(addr) and not any(c.address == addr for c in self._device_cards.values())
            )
            if missing:
                self._load_devices_from_db()
            card = self._device_cards.get(pid) if pid else None
            if card is None and addr:
                card = next((c for c in self._device_cards.values() if c.address == addr), None)
            if card is None and paired_phone_id:
                card = self._card_for_member_device(paired_phone_id)
            if card:
                self._paired_phone_id      = card.device_id
                self._paired_phone_address = card.address
                card.set_online(True)

        if not self._connected:
            self._set_connected(True)
            self._switch_page(1)
            self._set_status("Eşleşme tamamlandı. Görüntü akışı bekleniyor…")
        self._refresh_home_summary()

        if su and not mjpeg_unreachable:
            try:
                self._mjpeg.start(su)
                self._set_status("Bağlandı. Video akışı aktif.")
                return
            except Exception:
                logger.exception("MJPEG akışı başlatılamadı")

        if not self._screen_capture_prompt_sent:
            self._screen_capture_prompt_sent = True
            QTimer.singleShot(700, self._request_phone_screen_capture)
        self._refresh_paired_stream_status()

    @pyqtSlot(list, list, object)
    def _on_paired_devices_status(self, paired_devices: list, online_devices: list, phone_a11y: object):
        online_ids         = ws_device_id_set(online_devices)
        incoming_paired_ids= ws_device_id_set(paired_devices)

        if self._auth_token:
            current_ids = {str(k).strip() for k in self._device_cards if str(k).strip()}
            if incoming_paired_ids != current_ids or not self._device_cards:
                self._load_devices_from_db()
            self._online_paired_devices.clear()
            for key, card in self._device_cards.items():
                ck = str(key).strip()
                on = bool(ck) and ck in online_ids
                card.set_online(on)
                if on:
                    self._online_paired_devices.add(key)
        else:
            current_ids = {str(k).strip() for k in self._device_cards if str(k).strip()}
            if incoming_paired_ids != current_ids:
                self._load_devices_from_db()
            self._online_paired_devices.clear()
            for ck_raw, card in self._device_cards.items():
                ck = str(ck_raw).strip()
                on = bool(ck) and ck in online_ids
                card.set_online(on)
                if on:
                    self._online_paired_devices.add(ck_raw)

        self._reflow_device_cards()
        online_count = len(self._online_paired_devices)
        self._lbl_device_count.setText(
            f"{online_count} aktif / {len(self._device_cards)} cihaz"
            if self._device_cards else ""
        )

        if not self._connected:
            if online_count:
                self._set_status(f"Sunucuya baglandi - {online_count} cihaz çevrimiçi")
            else:
                self._set_status(Ui.MSG_SERVER_CONNECTED)

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
            self._load_devices_from_db()
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
        if is_accessibility_ws_error(text, code):
            banner_title = "Erişilebilirlik kapalı"
            banner_body  = text or "Telefonda Erişilebilirlik servisi açılmadan bağlantı başlatılamaz."
            self._a11y_recovery_token += 1
            recovery_token = self._a11y_recovery_token

            session_code = address_digits(self._paired_phone_address or "")
            if len(session_code) != 12:
                session_code = address_digits(load_paired_phone_address() or "")
            if len(session_code) != 12:
                session_code = address_digits(self._ws_client.join_session_code or "")
            if len(session_code) == 12:
                self._a11y_pending_reconnect_code = session_code
                logger.info("Erişilebilirlik hatası — yeniden bağlantı kodu: %s", session_code)

            def _apply_banner() -> None:
                self._mjpeg.stop()
                self._screen.clear_frame()
                self._phone_accessibility_enabled = False
                self._remote_frame_visible = False
                self._set_connected(False)
                self._switch_page(0)
                self._show_warning_banner(banner_title, banner_body)
                self._refresh_home_summary()
                if self._ws_mode == "session":
                    self._ws_mode = "presence"
                    self._manual_disconnect = True
                    self._ws_client.disconnect()
                    QTimer.singleShot(
                        300,
                        lambda: (
                            self._connect_presence_channel("Cihaz durumu izleniyor...")
                            if (
                                self._a11y_recovery_token == recovery_token
                                and self._ws_mode == "presence"
                                and not self._connected
                            )
                            else None
                        ),
                    )

            QTimer.singleShot(0, _apply_banner)
        self._set_status(f"Hata: {msg}", error=True)

    @pyqtSlot(bytes)
    def _on_audio_received(self, pcm_bytes: bytes):
        if not pcm_bytes:
            return
        chunk = self._audio_jitter.push(pcm_bytes)
        if chunk is None:
            return
        if self._audio_device is not None and self._audio_sink is not None:
            if self._audio_sink.state() == QAudio.State.StoppedState:
                self._audio_device = self._audio_sink.start()
            try:
                self._audio_device.write(chunk)
            except Exception as e:
                pass

    @pyqtSlot(bytes)
    def _on_frame_received(self, frame_bytes: bytes):
        if not frame_bytes:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(frame_bytes, "JPEG"):
            if not pixmap.loadFromData(frame_bytes):
                img = QImage()
                if not img.loadFromData(frame_bytes):
                    logger.warning("Görüntü çözümlenemedi. Boyut: %d bayt", len(frame_bytes))
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
        deg = self._rotation_step * 90
        self._screen.set_rotation(deg)
        self._sync_stream_aspect_fit()

    @staticmethod
    def _normalize_rotation_step(degrees: int | float) -> int:
        """Her türlü derece değerini 0..3 (0/90/180/270) adımına normalize et."""
        try:
            deg = int(degrees)
        except (TypeError, ValueError):
            deg = 0
        return ((deg % 360) // 90) % 4

    @pyqtSlot(int)
    def _on_rotation_received(self, degrees: int):
        """Telefon rotasyonu değiştiğinde otomatik döndür (metadata ile gelir)."""
        step = self._normalize_rotation_step(degrees)
        if step != self._rotation_step:
            self._rotation_step = step
            self._apply_rotation_step()
    @pyqtSlot(int)
    def _on_reconnecting(self, attempt: int):
        """Otomatik yeniden bağlanma denemesi başladığında durum güncelle."""
        self._set_status(f"Yeniden bağlanılıyor... (deneme {attempt})")

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
            
            from desktop_app.config.constants import AndroidKeyCodes
            if getattr(self, "_audio_sink", None) is not None:
                current_vol = self._audio_sink.volume()
                if key_code == AndroidKeyCodes.VOL_UP:
                    self._audio_sink.setVolume(min(1.0, current_vol + 0.1))
                elif key_code == AndroidKeyCodes.VOL_DOWN:
                    self._audio_sink.setVolume(max(0.0, current_vol - 0.1))
                elif key_code == AndroidKeyCodes.VOL_MUTE:
                    if current_vol > 0.0:
                        self._last_volume = current_vol
                        self._audio_sink.setVolume(0.0)
                    else:
                        prev = getattr(self, "_last_volume", 1.0)
                        self._audio_sink.setVolume(max(0.1, prev))

    def _set_remote_controls_enabled(self, enabled: bool) -> None:
        for btn in getattr(self, "_key_buttons", []):
            btn.setEnabled(enabled)
        for attr in ("_btn_sess_clip", "_btn_sess_save", "_btn_sess_paste"):
            btn = getattr(self, attr, None)
            if btn is not None:
                btn.setEnabled(enabled)
    def _request_phone_screen_capture(self) -> None:
        if self._connected:
            self._ws_client.send_screen_capture_on()

    def _refresh_paired_stream_status(self) -> None:
        if not self._connected:
            return
        if self._remote_frame_visible:
            if self._phone_accessibility_enabled is False:
                logger.debug("Kare akışı aktif — erişilebilirlik bayrağı True olarak düzeltildi")
                self._phone_accessibility_enabled = True
            self._set_status(Ui.MSG_PAIRED_WS)
            self._set_remote_controls_enabled(True)
            return
        if self._phone_accessibility_enabled is False:
            self._set_status(Ui.MSG_PAIRED_A11Y_OFF)
            self._set_remote_controls_enabled(False)
            return
        self._set_status(Ui.MSG_PAIRED_WAIT_STREAM)
        self._set_remote_controls_enabled(False)

    def _sync_stream_aspect_fit(self, ew: int | None = None, eh: int | None = None) -> None:
        if not hasattr(self, "_stream_aspect_host"):
            return
        if ew is None or eh is None:
            ew, eh = self._screen.effective_frame_size()
        if ew > 0 and eh > 0:
            self._stream_aspect_host.set_stream_dimensions(ew, eh)

    def _note_stream_frame(self, w: int, h: int) -> None:
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
            self._lbl_sess_fps.setText("FPS --")
            self._fps_frame_counter = 0
            return
        fps = self._fps_frame_counter
        self._fps_frame_counter = 0
        self._lbl_sess_fps.setText(f"FPS {fps}")

    def _reset_session_stats_labels(self) -> None:
        if hasattr(self, "_lbl_sess_res"):
            self._lbl_sess_res.setText("-- x --")
            self._lbl_sess_fps.setText("FPS --")
    def _screenshot_to_clipboard(self) -> None:
        pm = self._screen.get_export_pixmap()
        if pm is None or pm.isNull():
            self._set_status("Kopyalanacak goruntu yok.", error=True)
            return
        QApplication.clipboard().setPixmap(pm)
        self._set_status(f"Panoya kopyalandı ({pm.width()}×{pm.height()}).")

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
            self._set_status("Pano boş.", error=True)
            return
        self._ws_client.send_paste_text(text)
        self._set_status(f"Pano metni gonderildi ({len(text)} karakter).")

    def _set_connected(self, connected: bool):
        self._connected = connected
        if not connected:
            self._screen_capture_prompt_sent = False
            self._fps_histogram_timer.stop()
            self._reset_session_stats_labels()
            self._sync_stream_aspect_fit()
            self._audio_jitter.reset()
        else:
            self._fps_histogram_timer.start()
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
        self._fps_histogram_timer.stop()
        self._manual_disconnect = True
        self._ws_client.disconnect()
        super().closeEvent(event)
