
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_app.config import Colors
from desktop_app.ui.styles.app_styles import (
    PROFILE_DRAWER_CLOSE_BTN_SS,
    _ACCENT,
    _BG_INPUT,
    _BG_RAISED,
    _BORDER,
    _BORDER_SUBTLE,
    _RED,
    _TEXT,
    _TEXT_DIM,
    _TEXT_SEC,
)
from desktop_app.ui.theme import filled_button_style, line_edit_style, outline_button_style

if TYPE_CHECKING:
    from desktop_app.ui.app_window import MainWindow

_C = Colors


# ── Ana builder ──────────────────────────────────────────────────────────────

def build_profile_drawer(window: "MainWindow", parent: QWidget) -> QFrame:
    """Profil drawer widget'ını oluşturur; pencere (parent) üzerinde float eder."""
    drawer = QFrame(parent)
    drawer.setObjectName("profile_drawer")
    drawer.setStyleSheet(
        f"QFrame#profile_drawer {{"
        f"  background-color: {_BG_RAISED};"
        f"  border-left: 1px solid {_BORDER_SUBTLE};"
        f"}}"
    )
    drawer.setFixedWidth(window._profile_drawer_width)

    root = QVBoxLayout(drawer)
    root.setContentsMargins(16, 14, 16, 14)
    root.setSpacing(0)

    # Başlık satırı: "Profil" + Kapat butonu
    header = QHBoxLayout()
    title = QLabel("Profil")
    title.setStyleSheet(f"color: {_TEXT}; font-size: 16px; font-weight: 600;")
    header.addWidget(title)
    header.addStretch()

    btn_close = QPushButton("Kapat")
    btn_close.setFixedHeight(32)
    btn_close.setMinimumWidth(86)
    btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_close.setStyleSheet(PROFILE_DRAWER_CLOSE_BTN_SS)
    btn_close.setToolTip("Profil panelini kapat")
    btn_close.clicked.connect(window._close_profile_drawer)
    header.addWidget(btn_close)
    root.addLayout(header)

    hint = QLabel("Hesap özeti ve iletişim bilgileri.")
    hint.setWordWrap(True)
    hint.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px; margin-top: 6px;")
    root.addWidget(hint)

    window._profile_load_err = QLabel("")
    window._profile_load_err.setWordWrap(True)
    window._profile_load_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    window._profile_load_err.hide()
    root.addWidget(window._profile_load_err)

    # Kaydırılabilir içerik
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

    # İçerik blokları
    _build_account_card(window, lay)
    _build_action_buttons(window, lay)
    _build_edit_block(window, lay)
    _build_password_block(window, lay)

    lay.addStretch()
    return drawer


# ── Hesap özet kartı ─────────────────────────────────────────────────────────

def _build_account_card(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    card_css = (
        f"QFrame {{ background-color: {_BG_INPUT};"
        f" border: 1px solid {_BORDER_SUBTLE}; border-radius: 6px; }}"
    )

    account_card = QFrame()
    account_card.setStyleSheet(card_css)
    summary_lay = QVBoxLayout(account_card)
    summary_lay.setContentsMargins(14, 12, 14, 14)
    summary_lay.setSpacing(12)

    summary_lay.addWidget(_section_lbl("Hesap"))

    # Avatar + ad satırı
    head_row = QHBoxLayout()
    head_row.setSpacing(12)

    window._profile_avatar_lbl = QLabel("")
    window._profile_avatar_lbl.setFixedSize(40, 40)
    window._profile_avatar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window._profile_avatar_lbl.setStyleSheet(
        f"QLabel {{ background-color: {_BG_RAISED}; color: {_TEXT_SEC};"
        f" font-size: 13px; font-weight: 700;"
        f" border: 1px solid {_BORDER_SUBTLE}; border-radius: 8px; }}"
    )
    head_row.addWidget(window._profile_avatar_lbl, alignment=Qt.AlignmentFlag.AlignTop)

    title_col = QVBoxLayout()
    title_col.setSpacing(2)
    window._profile_view_name = QLabel("")
    window._profile_view_name.setWordWrap(True)
    window._profile_view_name.setStyleSheet(
        f"color: {_TEXT}; font-size: 15px; font-weight: 600;"
    )
    title_col.addWidget(window._profile_view_name)
    acc_lbl = QLabel("Kayıtlı kullanıcı")
    acc_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px;")
    title_col.addWidget(acc_lbl)
    head_row.addLayout(title_col, stretch=1)
    summary_lay.addLayout(head_row)

    sep1 = QFrame()
    sep1.setFixedHeight(1)
    sep1.setStyleSheet(f"background-color: {_BORDER_SUBTLE}; border: none;")
    summary_lay.addWidget(sep1)

    # E-posta / Telefon ızgarası
    grid = QGridLayout()
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(10)
    grid.setColumnMinimumWidth(0, 100)
    grid.setColumnStretch(1, 1)

    grid.addWidget(_grid_key("E-posta"), 0, 0)
    window._profile_view_email = _grid_val()
    grid.addWidget(window._profile_view_email, 0, 1)

    grid.addWidget(_grid_key("Telefon"), 1, 0)
    window._profile_view_phone = _grid_val()
    grid.addWidget(window._profile_view_phone, 1, 1)

    summary_lay.addLayout(grid)
    parent_lay.addWidget(account_card)


# ── İşlem butonları ──────────────────────────────────────────────────────────

def _build_action_buttons(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    parent_lay.addWidget(_section_lbl("İşlemler"))

    ops_col = QVBoxLayout()
    ops_col.setSpacing(8)

    window._profile_action_edit = QPushButton("Bilgileri düzenle…")
    window._profile_action_edit.setMinimumHeight(38)
    window._profile_action_edit.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    window._profile_action_edit.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_action_edit.setStyleSheet(filled_button_style())
    window._profile_action_edit.clicked.connect(
        lambda: window._set_profile_panel("edit")
    )
    ops_col.addWidget(window._profile_action_edit)

    window._profile_action_pwd = QPushButton("Şifre değiştir…")
    window._profile_action_pwd.setMinimumHeight(38)
    window._profile_action_pwd.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    window._profile_action_pwd.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_action_pwd.setStyleSheet(outline_button_style())
    window._profile_action_pwd.clicked.connect(
        lambda: window._set_profile_panel("password")
    )
    ops_col.addWidget(window._profile_action_pwd)
    parent_lay.addLayout(ops_col)


# ── Düzenleme bloğu (email / telefon) ────────────────────────────────────────

def _build_edit_block(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    window._profile_edit_block = QFrame()
    window._profile_edit_block.setStyleSheet(
        f"QFrame {{ background-color: {_BG_INPUT};"
        f" border: 1px solid {_BORDER_SUBTLE}; border-radius: 4px; }}"
    )
    edit_lay = QVBoxLayout(window._profile_edit_block)
    edit_lay.setContentsMargins(14, 14, 14, 14)
    edit_lay.setSpacing(8)

    edit_lay.addWidget(_section_lbl("İletişim bilgileri"))

    # Salt okunur ad/soyad
    edit_lay.addWidget(_field_lbl("Ad ve soyad"))
    window._profile_readonly_name = QLabel("")
    window._profile_readonly_name.setWordWrap(True)
    window._profile_readonly_name.setMinimumHeight(32)
    window._profile_readonly_name.setStyleSheet(
        f"color: {_TEXT_SEC}; font-size: 12px; padding: 8px 10px;"
        f" background-color: {_BG_INPUT}; border: 1px solid {_BORDER_SUBTLE};"
        f" border-radius: 6px;"
    )
    edit_lay.addWidget(window._profile_readonly_name)

    cap = QLabel("Kayıt sırasında belirlenir; buradan değiştirilemez.")
    cap.setWordWrap(True)
    cap.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px;")
    edit_lay.addWidget(cap)

    # E-posta
    edit_lay.addWidget(_field_lbl("E-posta"))
    window._profile_inp_email = QLineEdit()
    window._profile_inp_email.setFixedHeight(34)
    window._profile_inp_email.setStyleSheet(line_edit_style())
    edit_lay.addWidget(window._profile_inp_email)

    # Telefon
    edit_lay.addWidget(_field_lbl("Telefon"))
    window._profile_inp_phone = QLineEdit()
    window._profile_inp_phone.setFixedHeight(34)
    window._profile_inp_phone.setStyleSheet(line_edit_style())
    edit_lay.addWidget(window._profile_inp_phone)

    # Hata etiketi
    window._profile_err = QLabel("")
    window._profile_err.setWordWrap(True)
    window._profile_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    edit_lay.addWidget(window._profile_err)

    # Buton satırı
    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    window._profile_btn_cancel = QPushButton("Vazgeç")
    window._profile_btn_cancel.setFixedHeight(36)
    window._profile_btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_btn_cancel.setStyleSheet(outline_button_style())
    window._profile_btn_cancel.clicked.connect(window._on_profile_cancel)
    btn_row.addWidget(window._profile_btn_cancel)

    window._profile_btn_save = QPushButton("Kaydet")
    window._profile_btn_save.setFixedHeight(36)
    window._profile_btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_btn_save.setStyleSheet(filled_button_style())
    window._profile_btn_save.clicked.connect(window._save_profile_from_drawer)
    btn_row.addWidget(window._profile_btn_save)
    edit_lay.addLayout(btn_row)

    parent_lay.addWidget(window._profile_edit_block)
    window._profile_edit_block.hide()


# ── Şifre değiştirme bloğu ───────────────────────────────────────────────────

def _build_password_block(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    window._profile_pwd_block = QFrame()
    window._profile_pwd_block.setStyleSheet(
        f"QFrame {{ background-color: {_BG_INPUT};"
        f" border: 1px solid {_BORDER_SUBTLE}; border-radius: 4px; }}"
    )
    pw_lay = QVBoxLayout(window._profile_pwd_block)
    pw_lay.setContentsMargins(14, 14, 14, 14)
    pw_lay.setSpacing(8)
    pw_lay.addWidget(_section_lbl("Şifre değiştirme"))

    def _pw_field(label: str, attr: str) -> None:
        inp = QLineEdit()
        inp.setFixedHeight(34)
        inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setStyleSheet(line_edit_style())
        pw_lay.addWidget(_field_lbl(label))
        pw_lay.addWidget(inp)
        setattr(window, attr, inp)

    _pw_field("Mevcut şifre",         "_profile_inp_old")
    _pw_field("Yeni şifre",           "_profile_inp_pwd1")
    _pw_field("Yeni şifre (tekrar)",  "_profile_inp_pwd2")

    window._profile_pwd_err = QLabel("")
    window._profile_pwd_err.setWordWrap(True)
    window._profile_pwd_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    pw_lay.addWidget(window._profile_pwd_err)

    pw_btn = QHBoxLayout()
    pw_btn.setSpacing(8)

    window._profile_pwd_cancel = QPushButton("Vazgeç")
    window._profile_pwd_cancel.setFixedHeight(36)
    window._profile_pwd_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_pwd_cancel.setStyleSheet(outline_button_style())
    window._profile_pwd_cancel.clicked.connect(window._on_profile_pwd_cancel)
    pw_btn.addWidget(window._profile_pwd_cancel)

    window._profile_pwd_save = QPushButton("Kaydet")
    window._profile_pwd_save.setFixedHeight(36)
    window._profile_pwd_save.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_pwd_save.setStyleSheet(filled_button_style())
    window._profile_pwd_save.clicked.connect(window._save_password_from_drawer)
    pw_btn.addWidget(window._profile_pwd_save)
    pw_lay.addLayout(pw_btn)

    parent_lay.addWidget(window._profile_pwd_block)
    window._profile_pwd_block.hide()


# ── Widget yardımcıları ───────────────────────────────────────────────────────

def _field_lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px; font-weight: 600;")
    return l


def _section_lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color: {_TEXT}; font-size: 12px; font-weight: 600;")
    return l


def _grid_key(text: str) -> QLabel:
    w = QLabel(text)
    w.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px;")
    w.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
    return w


def _grid_val() -> QLabel:
    w = QLabel("")
    w.setWordWrap(True)
    w.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    w.setStyleSheet(f"color: {_TEXT}; font-size: 13px;")
    return w
