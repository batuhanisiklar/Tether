
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_app.config import AndroidKeyCodes, Colors
from desktop_app.ui.screen_widget import PhoneDeviceFrame, ScreenWidget, StreamAspectFitContainer
from desktop_app.ui.styles.app_styles import (
    REMOTE_BTN_DANGER_SS,
    REMOTE_BTN_GHOST_SS,
    REMOTE_BTN_PRIMARY_SS,
    REMOTE_KEY_BTN_SS,
    _ACCENT,
    _BG,
    _BG_CARD,
    _BG_RAISED,
    _BORDER_SUBTLE,
    _TEXT_DIM,
    _TEXT_SEC,
)

if TYPE_CHECKING:
    from desktop_app.ui.app_window import MainWindow

_C = Colors


# ── Ana remote sayfası ───────────────────────────────────────────────────────

def build_remote_page(window: "MainWindow") -> QWidget:
    """Remote kontrol sayfası widget'ını oluşturur."""
    page = QWidget()
    page.setStyleSheet(f"background-color: {_BG};")
    layout = QHBoxLayout(page)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(10)

    # ── Sol: görüntü alanı ──────────────────────────────────────────────
    left = QVBoxLayout()
    left.setSpacing(8)

    left.addWidget(_build_session_top_bar(window))

    screen_frame = QFrame()
    screen_frame.setStyleSheet(
        f"background-color: #0d0d0f; border: 1px solid {_BORDER_SUBTLE}; border-radius: 8px;"
    )
    sl = QVBoxLayout(screen_frame)
    sl.setContentsMargins(8, 8, 8, 8)

    window._screen = ScreenWidget()
    window._stream_aspect_host = StreamAspectFitContainer(PhoneDeviceFrame(window._screen))
    sl.addWidget(window._stream_aspect_host, stretch=1)
    left.addWidget(screen_frame, stretch=1)

    window._remote_summary_label = QLabel("")
    layout.addLayout(left, stretch=7)

    # ── Sağ: kontrol panelleri ───────────────────────────────────────────
    right = QVBoxLayout()
    right.setSpacing(10)
    right.addWidget(_build_controls_panel(window))
    right.addWidget(_build_key_controls_panel(window))
    right.addWidget(_build_session_actions_panel(window))
    right.addWidget(_build_remote_shortcuts_panel())
    right.addStretch(1)
    layout.addLayout(right, stretch=3)

    return page


# ── Oturum üst çubuğu ────────────────────────────────────────────────────────

def _build_session_top_bar(window: "MainWindow") -> QFrame:
    top_bar = QFrame()
    top_bar.setStyleSheet(
        f"background-color: {_BG_CARD}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
    )
    tbl = QHBoxLayout(top_bar)
    tbl.setContentsMargins(14, 8, 14, 8)
    tbl.setSpacing(14)
    tbl.addStretch(1)

    # İstatistik etiketleri
    stats_row = QWidget()
    stats_row.setStyleSheet("background: transparent;")
    srl = QHBoxLayout(stats_row)
    srl.setContentsMargins(0, 0, 0, 0)
    srl.setSpacing(16)
    stat_ss = f"color: {_TEXT_SEC}; font-size: 10px; font-weight: 600; background: transparent;"

    window._lbl_sess_res = QLabel("— × —")
    window._lbl_sess_fps = QLabel("FPS —")
    window._lbl_sess_rtt = QLabel("RTT —")
    for lb in (window._lbl_sess_res, window._lbl_sess_fps, window._lbl_sess_rtt):
        lb.setStyleSheet(stat_ss)
        srl.addWidget(lb)
    tbl.addWidget(stats_row, stretch=0)

    # Bağlantı kes butonu
    window._btn_disconnect = QPushButton("Bağlantıyı kes")
    window._btn_disconnect.setCursor(Qt.CursorShape.PointingHandCursor)
    window._btn_disconnect.setFixedHeight(32)
    window._btn_disconnect.setEnabled(False)
    window._btn_disconnect.setStyleSheet(REMOTE_BTN_DANGER_SS)
    tbl.addWidget(window._btn_disconnect)

    return top_bar


# ── Ekran kontrol paneli ─────────────────────────────────────────────────────

def _build_controls_panel(window: "MainWindow") -> QFrame:
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
    window._btn_rotate_left  = QPushButton("↺ Sola dön")
    window._btn_rotate_right = QPushButton("Sağa dön ↻")
    for b in (window._btn_rotate_left, window._btn_rotate_right):
        b.setFixedHeight(36)
        b.setEnabled(False)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(REMOTE_BTN_GHOST_SS)
    rot_row.addWidget(window._btn_rotate_left,  stretch=1)
    rot_row.addWidget(window._btn_rotate_right, stretch=1)
    lay.addLayout(rot_row)
    return panel


# ── Tuş kontrol paneli ───────────────────────────────────────────────────────

def _build_key_controls_panel(window: "MainWindow") -> QFrame:
    panel = QFrame()
    panel.setStyleSheet(
        f"background-color: {_BG_CARD}; border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px;"
    )
    lay = QVBoxLayout(panel)
    lay.setContentsMargins(12, 10, 12, 10)
    lay.setSpacing(8)

    title = QLabel("Tuş kontrolleri")
    title.setStyleSheet(f"color: {_ACCENT}; font-size: 11px; font-weight: 600;")
    lay.addWidget(title)

    grid = QGridLayout()
    grid.setSpacing(4)
    window._key_buttons = []
    key_codes = AndroidKeyCodes.as_mapping()

    for label, _group, row, col, key_id, colspan in AndroidKeyCodes.button_specs():
        btn = QPushButton(label)
        btn.setEnabled(False)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(REMOTE_KEY_BTN_SS)
        btn.clicked.connect(
            lambda _, code=key_codes[key_id]: window._ws_client.send_key_event(code)
        )
        if colspan > 1:
            grid.addWidget(btn, row, col, 1, colspan)
        else:
            grid.addWidget(btn, row, col)
        window._key_buttons.append(btn)

    lay.addLayout(grid)
    return panel


# ── Ekran & pano işlemleri paneli ────────────────────────────────────────────

def _build_session_actions_panel(window: "MainWindow") -> QFrame:
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

    window._btn_sess_clip = QPushButton("Görüntüyü panoya kopyala")
    window._btn_sess_clip.setCursor(Qt.CursorShape.PointingHandCursor)
    window._btn_sess_clip.setStyleSheet(REMOTE_BTN_GHOST_SS)
    window._btn_sess_clip.setFixedHeight(34)
    window._btn_sess_clip.clicked.connect(window._screenshot_to_clipboard)
    lay.addWidget(window._btn_sess_clip)

    window._btn_sess_save = QPushButton("PNG olarak kaydet…")
    window._btn_sess_save.setCursor(Qt.CursorShape.PointingHandCursor)
    window._btn_sess_save.setStyleSheet(REMOTE_BTN_GHOST_SS)
    window._btn_sess_save.setFixedHeight(34)
    window._btn_sess_save.clicked.connect(window._screenshot_save_png)
    lay.addWidget(window._btn_sess_save)

    window._btn_sess_paste = QPushButton("Panodaki metni telefona gönder")
    window._btn_sess_paste.setCursor(Qt.CursorShape.PointingHandCursor)
    window._btn_sess_paste.setStyleSheet(REMOTE_BTN_PRIMARY_SS)
    window._btn_sess_paste.setFixedHeight(36)
    window._btn_sess_paste.clicked.connect(window._send_clipboard_text_to_phone)
    window._btn_sess_paste.setEnabled(False)
    lay.addWidget(window._btn_sess_paste)

    return panel


# ── Klavye kısayolları paneli ────────────────────────────────────────────────

def _build_remote_shortcuts_panel() -> QFrame:
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
        "Kısayollar yalnızca soldaki canlı görüntü odaktayken çalışır. "
        "Kullanmadan önce görüntü alanına tıklayın."
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
        QScrollArea {{ background: transparent; border: none; }}
        QScrollBar:vertical {{
            background-color: {_BG_RAISED}; width: 11px;
            margin: 4px 6px 4px 4px; border-radius: 6px; border: none;
        }}
        QScrollBar::handle:vertical {{
            background-color: {_ACCENT}; border-radius: 5px;
            min-height: 44px; margin: 2px;
        }}
        QScrollBar::handle:vertical:hover {{ background-color: #e07a62; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            border: none; height: 0px;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """)

    shortcuts_rows: list[tuple[str, str]] = [
        (
            "Esc",
            "Geri: Aktif ekrandan bir önceki adıma döner. "
            "Bazı uygulamalarda bu işlem çıkış veya iptal etme işlevi görebilir."
        ),
        (
            "Ctrl+H",
            "Ana ekran: Telefonun ana ekranına hızlı bir şekilde dönüş yapmanızı sağlar. "
            "Açık olan uygulama arka planda çalışmaya devam eder."
        ),
        (
            "Ctrl+Tab",
            "Son uygulamalar: Arka planda çalışan uygulamaları görüntüler ve "
            "uygulamalar arasında hızlı geçiş yapmanıza olanak tanır."
        ),
        (
            "Ctrl+M",
            "Medya sesi: Telefonun medya sesini kapatır veya tekrar açar. "
            "Aynı kısayol tuşu ile sessize alma ve sesi geri açma işlemi yapılır."
        ),
        (
            "Ctrl+↑ / Ctrl+↓",
            "Ses kontrolü: Medya ses seviyesini artırır veya azaltır. "
            "Video, müzik ve diğer medya içerikleri için geçerlidir."
        ),
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
