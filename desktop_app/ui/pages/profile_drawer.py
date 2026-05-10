
from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
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
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

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

# ── Modern card palette ────────────────────────────────────────────────────
_DRAWER_BG      = "#161616"
_CARD_BG        = "#1C1C1C"
_CARD_BORDER    = "rgba(255,255,255,0.06)"
_CARD_RADIUS    = 12
_AVATAR_SIZE    = 48
_AVATAR_BG      = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #E8604C, stop:1 #F07858)"
_AVATAR_TEXT    = "#FFFFFF"


def build_profile_drawer(window: "MainWindow", parent: QWidget) -> QFrame:
    """Profil drawer widget'ını oluşturur; pencere (parent) üzerinde float eder."""
    drawer = QFrame(parent)
    drawer.setObjectName("profile_drawer")
    drawer.setStyleSheet(
        f"QFrame#profile_drawer {{"
        f"  background-color: {_DRAWER_BG};"
        f"  border-left: 1px solid {_CARD_BORDER};"
        f"}}"
    )
    drawer.setFixedWidth(window._profile_drawer_width)

    # Sol kenar gölge efekti
    shadow = QGraphicsDropShadowEffect(drawer)
    shadow.setBlurRadius(32)
    shadow.setXOffset(-8)
    shadow.setYOffset(0)
    shadow.setColor(QColor(0, 0, 0, 120))
    drawer.setGraphicsEffect(shadow)

    root = QVBoxLayout(drawer)
    root.setContentsMargins(20, 18, 20, 18)
    root.setSpacing(0)

    # ── Header ────────────────────────────────────────────────────────────
    header = QHBoxLayout()
    title = QLabel("Profil")
    title.setStyleSheet(f"color: {_TEXT}; font-size: 17px; font-weight: 700;")
    header.addWidget(title)
    header.addStretch()

    btn_close = QPushButton("Kapat")
    btn_close.setFixedHeight(32)
    btn_close.setMinimumWidth(86)
    btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_close.setStyleSheet(f"""
        QPushButton {{
            color: {_TEXT_SEC};
            background-color: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 8px;
            font-size: 11px;
            font-weight: 600;
            padding: 0 14px;
        }}
        QPushButton:hover {{
            background-color: rgba(255,255,255,0.08);
            color: {_TEXT};
            border-color: rgba(255,255,255,0.12);
        }}
        QPushButton:pressed {{ background-color: rgba(255,255,255,0.04); }}
    """)
    btn_close.setToolTip("Profil panelini kapat")
    btn_close.clicked.connect(window._close_profile_drawer)
    header.addWidget(btn_close)
    root.addLayout(header)

    hint = QLabel("Hesap bilgileri ve güvenlik ayarları")
    hint.setWordWrap(True)
    hint.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px; margin-top: 4px; margin-bottom: 6px;")
    root.addWidget(hint)

    window._profile_load_err = QLabel("")
    window._profile_load_err.setWordWrap(True)
    window._profile_load_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    window._profile_load_err.hide()
    root.addWidget(window._profile_load_err)

    # ── Scrollable content ────────────────────────────────────────────────
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

    inner = QWidget()
    inner.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(0, 10, 0, 8)
    lay.setSpacing(12)
    scroll.setWidget(inner)
    root.addWidget(scroll, stretch=1)

    _build_account_card(window, lay)
    _build_action_buttons(window, lay)
    _build_edit_block(window, lay)
    _build_password_block(window, lay)

    lay.addStretch()
    return drawer


def _card_frame() -> QFrame:
    """Modern rounded card container."""
    card = QFrame()
    card.setStyleSheet(
        f"QFrame {{ background-color: {_CARD_BG};"
        f" border: none; border-radius: {_CARD_RADIUS}px; }}"
    )
    return card


def _contact_icon_label(kind: str) -> QLabel:
    label = QLabel()
    label.setFixedSize(28, 28)

    pm = QPixmap(28, 28)
    pm.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    bg = QColor(_ACCENT)
    bg.setAlpha(34)
    border = QColor(_ACCENT)
    border.setAlpha(78)
    painter.setPen(QPen(border, 1))
    painter.setBrush(bg)
    painter.drawRoundedRect(QRectF(0.5, 0.5, 27, 27), 8, 8)

    icon = QColor(_ACCENT)
    painter.setPen(QPen(icon, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if kind == "email":
        rect = QRectF(7.0, 9.0, 14.0, 10.0)
        painter.drawRoundedRect(rect, 2, 2)
        painter.drawLine(QPointF(7.4, 10.0), QPointF(14.0, 15.2))
        painter.drawLine(QPointF(20.6, 10.0), QPointF(14.0, 15.2))
    else:
        path = QPainterPath()
        path.moveTo(10.0, 7.5)
        path.cubicTo(8.6, 8.5, 8.6, 11.4, 10.1, 14.3)
        path.cubicTo(11.6, 17.1, 14.7, 19.5, 18.0, 20.2)
        path.cubicTo(19.6, 20.5, 20.8, 19.3, 20.5, 17.9)
        painter.drawPath(path)
        painter.drawLine(QPointF(10.0, 7.5), QPointF(12.1, 9.8))
        painter.drawLine(QPointF(18.0, 20.2), QPointF(19.8, 17.8))

    painter.end()
    label.setPixmap(pm)
    return label


def _build_account_card(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    account_card = _card_frame()
    summary_lay = QVBoxLayout(account_card)
    summary_lay.setContentsMargins(16, 14, 16, 16)
    summary_lay.setSpacing(14)

    # Kullanıcı avatarı ve isim
    head_row = QHBoxLayout()
    head_row.setSpacing(14)

    window._profile_avatar_lbl = QLabel("")
    window._profile_avatar_lbl.setFixedSize(_AVATAR_SIZE, _AVATAR_SIZE)
    window._profile_avatar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window._profile_avatar_lbl.setStyleSheet(
        f"QLabel {{ background: {_AVATAR_BG}; color: {_AVATAR_TEXT};"
        f" font-size: 16px; font-weight: 700;"
        f" border: none; border-radius: {_AVATAR_SIZE // 2}px; }}"
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

    # Bilgi satırları — modern ikon + değer düzeni
    info_lay = QVBoxLayout()
    info_lay.setSpacing(10)

    # E-posta satırı
    email_row = QHBoxLayout()
    email_row.setSpacing(10)
    email_icon = _contact_icon_label("email")
    email_row.addWidget(email_icon)
    email_col = QVBoxLayout()
    email_col.setSpacing(0)
    email_key = QLabel("E-posta")
    email_key.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; font-weight: 600;")
    email_col.addWidget(email_key)
    window._profile_view_email = QLabel("")
    window._profile_view_email.setWordWrap(True)
    window._profile_view_email.setStyleSheet(f"color: {_TEXT}; font-size: 13px;")
    email_col.addWidget(window._profile_view_email)
    email_row.addLayout(email_col, stretch=1)
    info_lay.addLayout(email_row)

    # Telefon satırı
    phone_row = QHBoxLayout()
    phone_row.setSpacing(10)
    phone_icon = _contact_icon_label("phone")
    phone_row.addWidget(phone_icon)
    phone_col = QVBoxLayout()
    phone_col.setSpacing(0)
    phone_key = QLabel("Telefon")
    phone_key.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; font-weight: 600;")
    phone_col.addWidget(phone_key)
    window._profile_view_phone = QLabel("")
    window._profile_view_phone.setWordWrap(True)
    window._profile_view_phone.setStyleSheet(f"color: {_TEXT}; font-size: 13px;")
    phone_col.addWidget(window._profile_view_phone)
    phone_row.addLayout(phone_col, stretch=1)
    info_lay.addLayout(phone_row)

    summary_lay.addLayout(info_lay)
    parent_lay.addWidget(account_card)


def _build_action_buttons(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    section = QLabel("İşlemler")
    section.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px;")
    parent_lay.addWidget(section)

    ops_col = QVBoxLayout()
    ops_col.setSpacing(8)

    window._profile_action_edit = QPushButton("Bilgileri düzenle")
    window._profile_action_edit.setMinimumHeight(40)
    window._profile_action_edit.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
    )
    window._profile_action_edit.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_action_edit.setStyleSheet(filled_button_style())
    window._profile_action_edit.clicked.connect(
        lambda: window._set_profile_panel("edit")
    )
    ops_col.addWidget(window._profile_action_edit)

    window._profile_action_pwd = QPushButton("Şifre değiştir")
    window._profile_action_pwd.setMinimumHeight(40)
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


def _build_edit_block(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    window._profile_edit_block = _card_frame()
    edit_lay = QVBoxLayout(window._profile_edit_block)
    edit_lay.setContentsMargins(16, 16, 16, 16)
    edit_lay.setSpacing(10)

    edit_lay.addWidget(_section_lbl("İletişim bilgileri"))

    edit_lay.addWidget(_field_lbl("Ad ve soyad"))
    window._profile_readonly_name = QLabel("")
    window._profile_readonly_name.setWordWrap(True)
    window._profile_readonly_name.setMinimumHeight(34)
    window._profile_readonly_name.setStyleSheet(
        f"color: {_TEXT_SEC}; font-size: 12px; padding: 8px 12px;"
        f" background-color: rgba(255,255,255,0.03); border: none;"
        f" border-radius: 8px;"
    )
    edit_lay.addWidget(window._profile_readonly_name)

    cap = QLabel("Kayıt sırasında belirlenir; buradan değiştirilemez.")
    cap.setWordWrap(True)
    cap.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 10px;")
    edit_lay.addWidget(cap)

    edit_lay.addWidget(_field_lbl("E-posta"))
    window._profile_inp_email = QLineEdit()
    window._profile_inp_email.setFixedHeight(36)
    window._profile_inp_email.setStyleSheet(line_edit_style())
    edit_lay.addWidget(window._profile_inp_email)

    edit_lay.addWidget(_field_lbl("Telefon"))
    window._profile_inp_phone = QLineEdit()
    window._profile_inp_phone.setFixedHeight(36)
    window._profile_inp_phone.setStyleSheet(line_edit_style())
    edit_lay.addWidget(window._profile_inp_phone)

    window._profile_err = QLabel("")
    window._profile_err.setWordWrap(True)
    window._profile_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    edit_lay.addWidget(window._profile_err)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    window._profile_btn_cancel = QPushButton("Vazgeç")
    window._profile_btn_cancel.setFixedHeight(38)
    window._profile_btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_btn_cancel.setStyleSheet(outline_button_style())
    window._profile_btn_cancel.clicked.connect(window._on_profile_cancel)
    btn_row.addWidget(window._profile_btn_cancel)

    window._profile_btn_save = QPushButton("Kaydet")
    window._profile_btn_save.setFixedHeight(38)
    window._profile_btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_btn_save.setStyleSheet(filled_button_style())
    window._profile_btn_save.clicked.connect(window._save_profile_from_drawer)
    btn_row.addWidget(window._profile_btn_save)
    edit_lay.addLayout(btn_row)

    parent_lay.addWidget(window._profile_edit_block)
    window._profile_edit_block.hide()


def _build_password_block(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    window._profile_pwd_block = _card_frame()
    pw_lay = QVBoxLayout(window._profile_pwd_block)
    pw_lay.setContentsMargins(16, 16, 16, 16)
    pw_lay.setSpacing(10)
    pw_lay.addWidget(_section_lbl("Şifre değiştirme"))

    def _pw_field(label: str, attr: str) -> None:
        inp = QLineEdit()
        inp.setFixedHeight(36)
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
    window._profile_pwd_cancel.setFixedHeight(38)
    window._profile_pwd_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_pwd_cancel.setStyleSheet(outline_button_style())
    window._profile_pwd_cancel.clicked.connect(window._on_profile_pwd_cancel)
    pw_btn.addWidget(window._profile_pwd_cancel)

    window._profile_pwd_save = QPushButton("Kaydet")
    window._profile_pwd_save.setFixedHeight(38)
    window._profile_pwd_save.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_pwd_save.setStyleSheet(filled_button_style())
    window._profile_pwd_save.clicked.connect(window._save_password_from_drawer)
    pw_btn.addWidget(window._profile_pwd_save)
    pw_lay.addLayout(pw_btn)

    parent_lay.addWidget(window._profile_pwd_block)
    window._profile_pwd_block.hide()


def _field_lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px; font-weight: 600;")
    return l


def _section_lbl(text: str) -> QLabel:
    l = QLabel(text)
    l.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: 700;")
    return l
