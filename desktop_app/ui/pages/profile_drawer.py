from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_app.config import AppMeta, Colors
from desktop_app.ui.styles.app_styles import (
    PROFILE_DRAWER_CLOSE_BTN_SS,
    _ACCENT,
    _RED,
    _TEXT,
    _TEXT_DIM,
    _TEXT_SEC,
)
from desktop_app.ui.theme import filled_button_style, line_edit_style, outline_button_style

if TYPE_CHECKING:
    from desktop_app.ui.app_window import MainWindow

_C = Colors

_DRAWER_BG = "#161616"
_CARD_BG = "#1C1C1C"
_CARD_BORDER = "rgba(255,255,255,0.06)"
_CARD_RADIUS = 12
_AVATAR_SIZE = 48
_AVATAR_BG = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #E8604C, stop:1 #F07858)"
_AVATAR_TEXT = "#FFFFFF"


def build_profile_drawer(window: "MainWindow", parent: QWidget) -> QFrame:
    drawer = QFrame(parent)
    drawer.setObjectName("profile_drawer")
    drawer.setStyleSheet(
        f"QFrame#profile_drawer {{"
        f"background-color: {_DRAWER_BG};"
        f"border-left: 1px solid {_CARD_BORDER};"
        f"}}"
    )
    drawer.setFixedWidth(window._profile_drawer_width)

    shadow = QGraphicsDropShadowEffect(drawer)
    shadow.setBlurRadius(32)
    shadow.setXOffset(-8)
    shadow.setYOffset(0)
    shadow.setColor(QColor(0, 0, 0, 120))
    drawer.setGraphicsEffect(shadow)

    root = QVBoxLayout(drawer)
    root.setContentsMargins(20, 18, 20, 18)
    root.setSpacing(0)

    header = QHBoxLayout()
    title = QLabel("Ayarlar")
    title.setStyleSheet(f"color: {_TEXT}; font-size: 17px; font-weight: 700;")
    header.addWidget(title)
    header.addStretch()

    btn_close = QPushButton("Kapat")
    btn_close.setFixedHeight(32)
    btn_close.setMinimumWidth(86)
    btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_close.setStyleSheet(PROFILE_DRAWER_CLOSE_BTN_SS)
    btn_close.setToolTip("Ayarlar panelini kapat")
    btn_close.clicked.connect(window._close_profile_drawer)
    header.addWidget(btn_close)
    root.addLayout(header)

    hint = QLabel("Hesap ve güvenlik ayarları")
    hint.setWordWrap(True)
    hint.setStyleSheet(
        f"color: {_TEXT_DIM}; font-size: 11px; margin-top: 4px; margin-bottom: 6px;"
    )
    root.addWidget(hint)

    window._profile_load_err = QLabel("")
    window._profile_load_err.setWordWrap(True)
    window._profile_load_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    window._profile_load_err.hide()
    root.addWidget(window._profile_load_err)

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
    _build_account_settings(window, lay)
    _build_email_block(window, lay)
    _build_phone_block(window, lay)
    _build_password_block(window, lay)
    _build_delete_account_block(window, lay)
    _build_app_info_card(lay)
    _build_logout_button(window, lay)

    lay.addStretch()
    return drawer


def _card_frame() -> QFrame:
    card = QFrame()
    card.setStyleSheet(
        f"QFrame {{ background-color: {_CARD_BG}; border: none; border-radius: {_CARD_RADIUS}px; }}"
    )
    return card


def _danger_button_style() -> str:
    return filled_button_style(
        background="#E03137",
        foreground="#FFFFFF",
        hover="#FF4D4F",
        pressed="#B91C1C",
        disabled_background="#3A2526",
        disabled_foreground="#8F7375",
    )


def _danger_outline_button_style() -> str:
    return outline_button_style(
        background="rgba(255,77,79,0.10)",
        foreground="#FF6B6E",
        border_color="rgba(255,77,79,0.52)",
        hover_background="rgba(255,77,79,0.22)",
        hover_foreground="#FFFFFF",
        hover_border="#FF6B6E",
        font_weight=700,
    )


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
    painter.setPen(
        QPen(
            icon,
            1.7,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
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

    head_row = QHBoxLayout()
    head_row.setSpacing(14)

    window._profile_avatar_lbl = QLabel("")
    window._profile_avatar_lbl.setFixedSize(_AVATAR_SIZE, _AVATAR_SIZE)
    window._profile_avatar_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    window._profile_avatar_lbl.setStyleSheet(
        f"QLabel {{ background: {_AVATAR_BG}; color: {_AVATAR_TEXT}; "
        f"font-size: 16px; font-weight: 700; border: none; border-radius: {_AVATAR_SIZE // 2}px; }}"
    )
    head_row.addWidget(window._profile_avatar_lbl, alignment=Qt.AlignmentFlag.AlignTop)

    title_col = QVBoxLayout()
    title_col.setSpacing(2)
    window._profile_view_name = QLabel("")
    window._profile_view_name.setWordWrap(True)
    window._profile_view_name.setStyleSheet(f"color: {_TEXT}; font-size: 15px; font-weight: 600;")
    title_col.addWidget(window._profile_view_name)
    acc_lbl = QLabel("Kayıtlı kullanıcı")
    acc_lbl.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px;")
    title_col.addWidget(acc_lbl)
    head_row.addLayout(title_col, stretch=1)
    summary_lay.addLayout(head_row)

    info_lay = QVBoxLayout()
    info_lay.setSpacing(10)

    email_row = QHBoxLayout()
    email_row.setSpacing(10)
    email_row.addWidget(_contact_icon_label("email"))
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

    phone_row = QHBoxLayout()
    phone_row.setSpacing(10)
    phone_row.addWidget(_contact_icon_label("phone"))
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

    window._profile_btn_clear_connections = QPushButton("Tüm Cihazları Kaldır")
    window._profile_btn_clear_connections.setMinimumHeight(40)
    window._profile_btn_clear_connections.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_btn_clear_connections.setStyleSheet(_danger_outline_button_style())
    window._profile_btn_clear_connections.clicked.connect(window._clear_all_connections_from_drawer)
    summary_lay.addWidget(window._profile_btn_clear_connections)

    parent_lay.addWidget(account_card)


def _build_account_settings(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    section = QLabel("Hesap Ayarları")
    section.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: 700;")
    parent_lay.addWidget(section)

    sub = QLabel("E-posta, telefon, şifre değiştirme ve hesap silme işlemleri.")
    sub.setWordWrap(True)
    sub.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 11px; margin-top: 2px;")
    parent_lay.addWidget(sub)

    window._profile_actions_block = QWidget()
    ops_col = QVBoxLayout(window._profile_actions_block)
    ops_col.setContentsMargins(0, 0, 0, 0)
    ops_col.setSpacing(8)

    def _action_button(text: str, panel: str, attr_name: str) -> None:
        btn = QPushButton(text)
        btn.setMinimumHeight(40)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(outline_button_style())
        btn.clicked.connect(lambda: window._set_profile_panel(panel))
        setattr(window, attr_name, btn)
        ops_col.addWidget(btn)

    _action_button("E-posta Değiştir", "email", "_profile_action_email")
    _action_button("Telefon Numarası Değiştir", "phone", "_profile_action_phone")
    _action_button("Şifre Değiştir", "password", "_profile_action_pwd")

    window._profile_action_delete = QPushButton("Hesabı Sil")
    window._profile_action_delete.setMinimumHeight(40)
    window._profile_action_delete.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_action_delete.setStyleSheet(_danger_button_style())
    window._profile_action_delete.clicked.connect(lambda: window._set_profile_panel("delete"))
    ops_col.addWidget(window._profile_action_delete)

    parent_lay.addWidget(window._profile_actions_block)


def _build_email_block(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    window._profile_email_block = _card_frame()
    lay = QVBoxLayout(window._profile_email_block)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(10)

    lay.addWidget(_section_lbl("E-posta Değiştir"))
    lay.addWidget(_field_lbl("Yeni e-posta adresi"))
    window._profile_inp_email = QLineEdit()
    window._profile_inp_email.setFixedHeight(38)
    window._profile_inp_email.setStyleSheet(line_edit_style())
    lay.addWidget(window._profile_inp_email)

    window._profile_email_err = QLabel("")
    window._profile_email_err.setWordWrap(True)
    window._profile_email_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    lay.addWidget(window._profile_email_err)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    cancel = QPushButton("Vazgeç")
    cancel.setFixedHeight(38)
    cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel.setStyleSheet(outline_button_style())
    cancel.clicked.connect(window._on_profile_email_cancel)
    btn_row.addWidget(cancel)

    save = QPushButton("Kaydet")
    save.setFixedHeight(38)
    save.setCursor(Qt.CursorShape.PointingHandCursor)
    save.setStyleSheet(filled_button_style())
    save.clicked.connect(window._save_email_from_drawer)
    btn_row.addWidget(save)
    lay.addLayout(btn_row)

    parent_lay.addWidget(window._profile_email_block)
    window._profile_email_block.hide()


def _build_phone_block(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    window._profile_phone_block = _card_frame()
    lay = QVBoxLayout(window._profile_phone_block)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(10)

    lay.addWidget(_section_lbl("Telefon Numarası Değiştir"))
    lay.addWidget(_field_lbl("Yeni telefon numarası"))
    window._profile_inp_phone = QLineEdit()
    window._profile_inp_phone.setFixedHeight(38)
    window._profile_inp_phone.setMaxLength(11)
    window._profile_inp_phone.setPlaceholderText("05XXXXXXXXX")
    window._profile_inp_phone.setStyleSheet(line_edit_style())
    window._profile_inp_phone.textChanged.connect(
        lambda text: window._profile_inp_phone.setText(
            "".join(ch for ch in text if ch.isdigit())[:11]
        )
        if any(not ch.isdigit() for ch in text)
        else None
    )
    lay.addWidget(window._profile_inp_phone)

    window._profile_phone_err = QLabel("")
    window._profile_phone_err.setWordWrap(True)
    window._profile_phone_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    lay.addWidget(window._profile_phone_err)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    cancel = QPushButton("Vazgeç")
    cancel.setFixedHeight(38)
    cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel.setStyleSheet(outline_button_style())
    cancel.clicked.connect(window._on_profile_phone_cancel)
    btn_row.addWidget(cancel)

    save = QPushButton("Kaydet")
    save.setFixedHeight(38)
    save.setCursor(Qt.CursorShape.PointingHandCursor)
    save.setStyleSheet(filled_button_style())
    save.clicked.connect(window._save_phone_from_drawer)
    btn_row.addWidget(save)
    lay.addLayout(btn_row)

    parent_lay.addWidget(window._profile_phone_block)
    window._profile_phone_block.hide()


def _build_password_block(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    window._profile_pwd_block = _card_frame()
    lay = QVBoxLayout(window._profile_pwd_block)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(10)

    lay.addWidget(_section_lbl("Şifre Değiştir"))

    def _pw_field(label: str, attr: str) -> None:
        inp = QLineEdit()
        inp.setFixedHeight(38)
        inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setStyleSheet(line_edit_style())
        lay.addWidget(_field_lbl(label))
        lay.addWidget(inp)
        setattr(window, attr, inp)

    _pw_field("Mevcut şifre", "_profile_inp_old")
    _pw_field("Yeni şifre", "_profile_inp_pwd1")
    _pw_field("Yeni şifre (tekrar)", "_profile_inp_pwd2")

    window._profile_pwd_err = QLabel("")
    window._profile_pwd_err.setWordWrap(True)
    window._profile_pwd_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    lay.addWidget(window._profile_pwd_err)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    cancel = QPushButton("Vazgeç")
    cancel.setFixedHeight(38)
    cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel.setStyleSheet(outline_button_style())
    cancel.clicked.connect(window._on_profile_pwd_cancel)
    btn_row.addWidget(cancel)

    save = QPushButton("Kaydet")
    save.setFixedHeight(38)
    save.setCursor(Qt.CursorShape.PointingHandCursor)
    save.setStyleSheet(filled_button_style())
    save.clicked.connect(window._save_password_from_drawer)
    btn_row.addWidget(save)
    lay.addLayout(btn_row)

    parent_lay.addWidget(window._profile_pwd_block)
    window._profile_pwd_block.hide()


def _build_delete_account_block(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    window._profile_delete_block = _card_frame()
    lay = QVBoxLayout(window._profile_delete_block)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(10)

    lay.addWidget(_section_lbl("Hesabı Sil"))

    window._profile_delete_info = QLabel("")
    window._profile_delete_info.setWordWrap(True)
    window._profile_delete_info.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px;")
    lay.addWidget(window._profile_delete_info)

    warning = QLabel("Dikkat: Bu işlem kalıcıdır ve hesabınızla birlikte tüm eşleşmeler silinir.")
    warning.setWordWrap(True)
    warning.setStyleSheet(
        f"color: {_RED}; font-size: 11px; border: 1px solid rgba(248,113,113,0.35); "
        f"background-color: rgba(248,113,113,0.10); border-radius: 8px; padding: 8px;"
    )
    lay.addWidget(warning)

    lay.addWidget(_field_lbl("Hesap e-postası"))
    window._profile_delete_inp_email = QLineEdit()
    window._profile_delete_inp_email.setFixedHeight(38)
    window._profile_delete_inp_email.setStyleSheet(line_edit_style())
    lay.addWidget(window._profile_delete_inp_email)

    lay.addWidget(_field_lbl("Hesap şifresi"))
    window._profile_delete_inp_password = QLineEdit()
    window._profile_delete_inp_password.setFixedHeight(38)
    window._profile_delete_inp_password.setEchoMode(QLineEdit.EchoMode.Password)
    window._profile_delete_inp_password.setStyleSheet(line_edit_style())
    lay.addWidget(window._profile_delete_inp_password)

    window._profile_delete_err = QLabel("")
    window._profile_delete_err.setWordWrap(True)
    window._profile_delete_err.setStyleSheet(f"color: {_RED}; font-size: 11px;")
    lay.addWidget(window._profile_delete_err)

    btn_row = QHBoxLayout()
    btn_row.setSpacing(8)
    cancel = QPushButton("Vazgeç")
    cancel.setFixedHeight(38)
    cancel.setCursor(Qt.CursorShape.PointingHandCursor)
    cancel.setStyleSheet(outline_button_style())
    cancel.clicked.connect(window._on_profile_delete_cancel)
    btn_row.addWidget(cancel)

    window._profile_delete_confirm_btn = QPushButton("Hesabı Kalıcı Sil")
    window._profile_delete_confirm_btn.setFixedHeight(38)
    window._profile_delete_confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_delete_confirm_btn.setStyleSheet(_danger_button_style())
    window._profile_delete_confirm_btn.clicked.connect(window._delete_account_from_drawer)
    btn_row.addWidget(window._profile_delete_confirm_btn)
    lay.addLayout(btn_row)

    parent_lay.addWidget(window._profile_delete_block)
    window._profile_delete_block.hide()


def _build_app_info_card(parent_lay: QVBoxLayout) -> None:
    card = _card_frame()
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(6)

    title = QLabel("Uygulama Bilgisi")
    title.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: 700;")
    lay.addWidget(title)

    version = QLabel(f"Sürüm: {AppMeta.VERSION}")
    version.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 12px;")
    lay.addWidget(version)

    parent_lay.addWidget(card)


def _build_logout_button(window: "MainWindow", parent_lay: QVBoxLayout) -> None:
    window._profile_logout_btn = QPushButton("Çıkış Yap")
    window._profile_logout_btn.setMinimumHeight(42)
    window._profile_logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    window._profile_logout_btn.setStyleSheet(_danger_button_style())
    window._profile_logout_btn.clicked.connect(window._on_logout)
    parent_lay.addWidget(window._profile_logout_btn)


def _field_lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 11px; font-weight: 600;")
    return lbl


def _section_lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {_TEXT}; font-size: 13px; font-weight: 700;")
    return lbl
