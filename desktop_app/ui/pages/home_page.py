from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from desktop_app.config import Colors
from desktop_app.ui.styles.app_styles import (
    REMOTE_BTN_ICON_PRIMARY_SS,
    WARNING_CLOSE_BTN_SS,
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
from desktop_app.ui.utils import format_address

if TYPE_CHECKING:
    from desktop_app.ui.app_window import MainWindow

_C = Colors


def build_home_page(window: "MainWindow") -> QWidget:
    """Ana sayfa widget'ını oluşturur."""
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

    layout.addWidget(_build_address_input_bar(window))
    layout.addWidget(_build_your_address_hero(window))
    layout.addWidget(_build_feature_cards())
    layout.addWidget(_build_tab_strip(window))
    layout.addWidget(_build_recent_sessions(window))
    layout.addStretch()

    scroll.setWidget(content)

    outer = QGridLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setHorizontalSpacing(0)
    outer.setVerticalSpacing(0)
    outer.addWidget(scroll, 0, 0)

    warning = _build_warning_banner(window)
    toast_host = QWidget()
    th = QVBoxLayout(toast_host)
    th.setContentsMargins(18, 0, 0, 16)
    th.setSpacing(0)
    th.addStretch(1)
    th.addWidget(warning, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
    outer.addWidget(toast_host, 0, 0, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
    return page


def _build_address_input_bar(window: "MainWindow") -> QWidget:
    bar = QFrame()
    bar.setFixedHeight(56)
    bar.setStyleSheet(f"QFrame {{ background-color: {_BG_RAISED}; }}")
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(18, 8, 18, 8)
    lay.setSpacing(10)

    dot = QFrame()
    dot.setFixedSize(8, 8)
    dot.setStyleSheet(f"background-color: {_GREEN}; border-radius: 4px;")
    lay.addWidget(dot)

    window._inp_code = QLineEdit()
    window._inp_code.setPlaceholderText("Telefon adresini girin (12 hane)")
    window._inp_code.setFixedHeight(40)
    window._inp_code.setMaxLength(14)
    window._inp_code.setFont(QFont("Segoe UI", 15))
    window._inp_code.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    window._inp_code.customContextMenuRequested.connect(window._show_code_input_menu)
    window._inp_code.setStyleSheet(f"""
        QLineEdit {{
            background-color: {_BG_INPUT};
            border: 1px solid {_BORDER};
            border-radius: 6px;
            padding: 0 12px;
            color: {_TEXT};
            selection-background-color: {_ACCENT};
        }}
        QLineEdit:focus {{ border-color: {_ACCENT}; }}
        QLineEdit::placeholder {{ color: {_TEXT_DIM}; }}
    """)
    window._inp_code.returnPressed.connect(window._on_connect)
    window._inp_code.textChanged.connect(window._on_address_text_changed)
    lay.addWidget(window._inp_code, stretch=1)

    window._btn_connect = QPushButton("→")
    window._btn_connect.setFixedSize(40, 40)
    window._btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
    window._btn_connect.setStyleSheet(REMOTE_BTN_ICON_PRIMARY_SS)
    lay.addWidget(window._btn_connect)

    window._addr_status_label = QLabel("Hazır")
    window._addr_status_label.setStyleSheet(
        f"color: {_TEXT_DIM}; font-size: 12px; font-weight: 600;"
    )
    window._addr_status_label.setFixedWidth(60)
    lay.addWidget(window._addr_status_label)

    return bar


def _build_your_address_hero(window: "MainWindow") -> QWidget:
    from desktop_app.ui.utils import desktop_device_name

    hero = QFrame()
    hero.setStyleSheet(f"background-color: {_BG};")
    outer = QHBoxLayout(hero)
    outer.setContentsMargins(28, 24, 28, 20)
    outer.setSpacing(20)

    left = QVBoxLayout()
    left.setSpacing(4)

    lbl_title = QLabel("Adresiniz")
    lbl_title.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 14px;")
    left.addWidget(lbl_title)

    formatted = format_address(window._user_address) if window._user_address else "—"
    window._hero_address = QLabel(formatted)
    hero_font = QFont("Segoe UI", 36, QFont.Weight.Bold)
    hero_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3.0)
    window._hero_address.setFont(hero_font)
    window._hero_address.setStyleSheet(f"""
        QLabel {{
            color: {_TEXT};
            background-color: rgba(42, 31, 26, 0.65);
            border: 1px solid rgba(232, 93, 58, 0.45);
            border-radius: 12px;
            padding: 10px 14px;
        }}
    """)
    left.addWidget(window._hero_address)
    left.addStretch()
    outer.addLayout(left, stretch=5)

    sep = QFrame()
    sep.setFixedWidth(1)
    sep.setStyleSheet(f"background-color: {_BORDER_SUBTLE};")
    outer.addWidget(sep)

    right = QVBoxLayout()
    right.setSpacing(10)

    info_title = QLabel("Bu bilgisayar")
    info_title.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 13px; font-weight: 600;")
    right.addWidget(info_title)

    info_pc = QLabel(f"  {desktop_device_name()}")
    info_pc.setStyleSheet(f"color: {_TEXT}; font-size: 14px; font-weight: 500;")
    right.addWidget(info_pc)

    window._hero_status_label = QLabel("  Bağlantı bekleniyor")
    window._hero_status_label.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px;")
    right.addWidget(window._hero_status_label)

    right.addStretch()
    outer.addLayout(right, stretch=3)

    return hero


def _build_warning_banner(window: "MainWindow") -> QWidget:
    banner = QFrame()
    banner.setObjectName("WarningToast")
    banner.setMaximumWidth(520)
    banner.setStyleSheet(
        "QFrame#WarningToast {"
        "  background-color: rgba(28, 16, 16, 0.92);"
        "  border: 1px solid rgba(248,113,113,0.55);"
        "  border-radius: 10px;"
        "}"
    )
    lay = QHBoxLayout(banner)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(10)

    icon = QLabel("!")
    icon.setFixedSize(18, 18)
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon.setStyleSheet(
        f"background-color: {_RED}; color: #1A1A1A; border-radius: 9px; font-weight: 800;"
    )
    lay.addWidget(icon)

    text_col = QVBoxLayout()
    text_col.setSpacing(2)

    window._warning_title = QLabel("Uyarı")
    window._warning_title.setStyleSheet(
        f"color: {_TEXT}; font-size: 12px; font-weight: 700;"
    )
    text_col.addWidget(window._warning_title)

    window._warning_text = QLabel("")
    window._warning_text.setWordWrap(True)
    window._warning_text.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px;")
    text_col.addWidget(window._warning_text)
    lay.addLayout(text_col, stretch=1)

    window._warning_close = QPushButton("Kapat")
    window._warning_close.setCursor(Qt.CursorShape.PointingHandCursor)
    window._warning_close.setFixedHeight(30)
    window._warning_close.setStyleSheet(WARNING_CLOSE_BTN_SS)
    window._warning_close.clicked.connect(window._hide_warning_banner)
    lay.addWidget(window._warning_close)
    banner.hide()
    window._warning_banner = banner
    return banner


def _build_feature_cards() -> QWidget:
    wrapper = QFrame()
    wrapper.setStyleSheet("background: transparent;")
    lay = QHBoxLayout(wrapper)
    lay.setContentsMargins(28, 0, 28, 16)
    lay.setSpacing(12)

    cards_data = [
        (
            "Hızlı bağlantı",
            "Telefonunuzun sabit adresini üst çubuğa girerek saniyeler içinde bağlantı kurabilirsiniz. "
            "Ek ayar yapmadan hızlı ve pratik şekilde cihazınıza erişim sağlayın.",
            "#C84B31",
            "#A33B24",
        ),
        (
            "Nasıl çalışır?",
            "Uygulamayı kullanmak oldukça basittir:\n"
            "1. Telefonda uygulamayı başlatın\n"
            "2. Size verilen sabit adresi bu ekrana girin\n"
            "3. Bağlan butonuna tıklayarak anında erişim sağlayın\n"
            "Tüm süreç yalnızca birkaç saniye sürer.",
            "#2D6A4F",
            "#1B4332",
        ),
        (
            "Gizlilik",
            "Tüm bağlantılar uçtan uca şifreleme ile korunur ve verileriniz üçüncü taraflarla paylaşılmaz. "
            "Cihaz sahipliği tamamen sizde kalır ve sadece onay verdiğiniz bağlantılar gerçekleştirilir.",
            "#4A3B8F",
            "#362C6B",
        ),
        (
            "Cihaz yönetimi",
            "Daha önce bağlandığınız cihazları kolayca görüntüleyebilir, düzenleyebilir ve yönetebilirsiniz. "
            "İhtiyacınız olmayan cihazları kaldırabilir, sık kullandıklarınızı hızlı erişim için saklayabilirsiniz.",
            "#8B6914",
            "#6B5010",
        ),
    ]

    for title, desc, bg_color, hover_color in cards_data:
        card = QFrame()
        card.setMinimumHeight(120)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color}; border-radius: 8px; border: none;
            }}
            QFrame:hover {{ background-color: {hover_color}; }}
        """)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(14, 12, 14, 12)
        card_lay.setSpacing(6)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(
            "color: white; font-size: 14px; font-weight: 700; background: transparent;"
        )
        card_lay.addWidget(lbl_t)

        lbl_d = QLabel(desc)
        lbl_d.setWordWrap(True)
        lbl_d.setStyleSheet(
            "color: rgba(255,255,255,0.85); font-size: 12px; background: transparent;"
        )
        card_lay.addWidget(lbl_d)
        card_lay.addStretch()
        lay.addWidget(card, stretch=1)

    return wrapper


def _build_tab_strip(window: "MainWindow") -> QWidget:
    strip = QFrame()
    strip.setFixedHeight(32)
    strip.setStyleSheet(
        f"background-color: {_BG}; border-bottom: 1px solid {_BORDER_SUBTLE};"
    )
    lay = QHBoxLayout(strip)
    lay.setContentsMargins(28, 0, 28, 0)
    lay.setSpacing(24)

    tab = QLabel("Son oturumlar")
    tab.setStyleSheet(
        f"color: {_ACCENT}; font-size: 13px; font-weight: 600;"
        f" border-bottom: 2px solid {_ACCENT}; padding-bottom: 4px;"
    )
    lay.addWidget(tab)
    lay.addStretch()

    window._lbl_device_count = QLabel("")
    window._lbl_device_count.setStyleSheet(
        f"color: {_TEXT_DIM}; font-size: 11px; padding: 0 4px;"
    )
    lay.addWidget(window._lbl_device_count)

    return strip


def _build_recent_sessions(window: "MainWindow") -> QWidget:
    section = QWidget()
    section.setStyleSheet("background: transparent;")
    inner = QVBoxLayout(section)
    inner.setContentsMargins(28, 14, 28, 20)
    inner.setSpacing(10)

    header = QHBoxLayout()
    icon_lbl = QLabel("Son oturumlar")
    icon_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 12px; font-weight: 600;")
    header.addWidget(icon_lbl)
    header.addStretch()
    inner.addLayout(header)

    window._recent_cards_container = QWidget()
    window._recent_cards_container.setStyleSheet("background: transparent;")
    window._recent_devices_layout = QGridLayout(window._recent_cards_container)
    window._recent_devices_layout.setContentsMargins(0, 0, 0, 0)
    window._recent_devices_layout.setHorizontalSpacing(12)
    window._recent_devices_layout.setVerticalSpacing(12)
    window._recent_devices_layout.setAlignment(
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
    )
    inner.addWidget(window._recent_cards_container)

    window._lbl_no_devices = QFrame()
    window._lbl_no_devices.setMinimumHeight(168)
    window._lbl_no_devices.setStyleSheet(
        f"QFrame {{ background-color: {_BG_CARD}; border-radius: 12px; border: 1px solid {_BORDER_SUBTLE}; }}"
    )
    no_dev_lay = QVBoxLayout(window._lbl_no_devices)
    no_dev_lay.setContentsMargins(32, 30, 32, 30)
    no_dev_lay.setSpacing(12)
    no_dev_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

    empty_icon = QLabel("📱")
    empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_icon.setStyleSheet(
        "font-size: 24px; background: transparent; border: none;"
    )
    no_dev_lay.addWidget(empty_icon)

    empty_title = QLabel("Henüz eşleşmiş cihaz yok")
    empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_title.setStyleSheet(
        f"color: {_TEXT_SEC}; font-size: 18px; font-weight: 700; background: transparent; border: none;"
    )
    no_dev_lay.addWidget(empty_title)

    empty_desc = QLabel(
        "Telefonunuzdaki uygulamayı açın ve 12 haneli sabit adresi yukarıdaki alana girerek ilk bağlantıyı kurun."
    )
    empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_desc.setWordWrap(True)
    empty_desc.setMaximumWidth(620)
    empty_desc.setStyleSheet(
        f"color: {_TEXT_DIM}; font-size: 14px; background: transparent; border: none;"
    )
    no_dev_lay.addWidget(empty_desc)

    inner.addWidget(window._lbl_no_devices)
    window._lbl_no_devices.hide()

    return section
