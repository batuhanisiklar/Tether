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
