"""
Eşleşme kaldırma onay diyaloğu.
app_window.py'den ayrılmış bağımsız bileşen.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_app.ui.styles.app_styles import (
    _ACCENT,
    _BG_CARD,
    _BG_RAISED,
    _BORDER,
    _BORDER_SUBTLE,
    _RED,
    _TEXT,
    _TEXT_SEC,
)


def confirm_forget_pairing(parent: QWidget, device_label: str) -> bool:
    """Modal onay diyaloğu gösterir; True = kullanıcı onayladı."""
    dialog = QDialog(parent)
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
            color: #FFFFFF;
            border: 1px solid rgba(255,107,110,0.72);
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 #FF5A5F,
                stop:1 #D9272E
            );
        }}
        QPushButton#confirmButton:hover {{
            border: 1px solid rgba(255,180,181,0.92);
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 #FF7074,
                stop:1 #FF3F46
            );
        }}
        QPushButton#confirmButton:pressed {{
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 #D9272E,
                stop:1 #B91C1C
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

    title = QLabel("Eşleşmeyi kaldır?")
    title.setStyleSheet(f"color: {_TEXT}; font-size: 18px; font-weight: 800;")
    copy.addWidget(title)

    body = QLabel(
        "Bu işlem mevcut cihaz eşleşmesini kaldırır. Devam etmek istiyor musun?"
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

    cancel_btn = QPushButton("İptal")
    cancel_btn.setObjectName("cancelButton")
    cancel_btn.clicked.connect(dialog.reject)
    actions.addWidget(cancel_btn)

    confirm_btn = QPushButton("Eşleşmeyi Kaldır")
    confirm_btn.setObjectName("confirmButton")
    confirm_btn.clicked.connect(dialog.accept)
    confirm_btn.setDefault(True)
    actions.addWidget(confirm_btn)

    card_layout.addLayout(actions)
    return dialog.exec() == QDialog.DialogCode.Accepted


def confirm_clear_all_pairings(parent: QWidget, total: int) -> bool:
    """Mobile ayarlar ekranındaki temalı onay penceresine denk toplu kaldırma diyaloğu."""
    dialog = QDialog(parent)
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
            min-height: 44px;
            border-radius: 12px;
            padding: 0 14px;
            font-size: 13px;
            font-weight: 800;
        }}
        QPushButton#cancelButton {{
            background-color: #333333;
            color: {_TEXT};
            border: 1px solid {_BORDER};
        }}
        QPushButton#cancelButton:hover {{
            background-color: #3A3A3A;
            border-color: {_ACCENT};
        }}
        QPushButton#confirmButton {{
            color: #FFFFFF;
            background-color: #E03137;
            border: 1px solid rgba(255,107,110,0.72);
        }}
        QPushButton#confirmButton:hover {{
            background-color: #FF4D4F;
            border-color: rgba(255,180,181,0.92);
        }}
        QPushButton#confirmButton:pressed {{
            background-color: #B91C1C;
        }}
    """)

    root = QVBoxLayout(dialog)
    root.setContentsMargins(18, 18, 18, 18)
    root.setSpacing(0)

    card = QFrame()
    card.setObjectName("clearAllPairingsCard")
    card.setStyleSheet(f"""
        QFrame#clearAllPairingsCard {{
            background-color: {_BG_CARD};
            border: 1px solid {_BORDER_SUBTLE};
            border-radius: 12px;
        }}
    """)
    shadow = QGraphicsDropShadowEffect(card)
    shadow.setBlurRadius(36)
    shadow.setOffset(0, 10)
    shadow.setColor(QColor(0, 0, 0, 145))
    card.setGraphicsEffect(shadow)
    root.addWidget(card)

    card_layout = QVBoxLayout(card)
    card_layout.setContentsMargins(22, 22, 22, 22)
    card_layout.setSpacing(18)

    header = QHBoxLayout()
    header.setSpacing(14)

    icon = QLabel("!")
    icon.setFixedSize(42, 42)
    icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon.setStyleSheet(
        f"background-color: {_BG_RAISED};"
        f"color: {_RED};"
        f"border: 1px solid rgba(248,113,113,0.36);"
        f"border-radius: 12px;"
        f"font-size: 20px;"
        f"font-weight: 900;"
    )
    header.addWidget(icon, alignment=Qt.AlignmentFlag.AlignTop)

    title = QLabel("Tüm Cihazları Kaldır")
    title.setWordWrap(True)
    title.setStyleSheet(f"color: {_TEXT}; font-size: 18px; font-weight: 800;")
    header.addWidget(title, stretch=1)
    card_layout.addLayout(header)

    body = QLabel(
        f"{total} eşleşmiş cihaz kaydı kalıcı olarak kaldırılacak. Silmek istiyor musunuz?"
    )
    body.setWordWrap(True)
    body.setStyleSheet(f"color: {_TEXT_SEC}; font-size: 14px;")
    card_layout.addWidget(body)

    actions = QHBoxLayout()
    actions.setSpacing(10)

    cancel_btn = QPushButton("İptal")
    cancel_btn.setObjectName("cancelButton")
    cancel_btn.clicked.connect(dialog.reject)
    actions.addWidget(cancel_btn, stretch=1)

    confirm_btn = QPushButton("Kaldır")
    confirm_btn.setObjectName("confirmButton")
    confirm_btn.clicked.connect(dialog.accept)
    confirm_btn.setDefault(True)
    actions.addWidget(confirm_btn, stretch=1)

    card_layout.addLayout(actions)
    return dialog.exec() == QDialog.DialogCode.Accepted
