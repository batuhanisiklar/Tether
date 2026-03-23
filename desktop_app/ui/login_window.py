"""
Login Penceresi — Remote Phone Control
=======================================
Profesyonel koyu login diyaloğu. Tüm renkler constants.Colors'dan alınır.
"""

import os
import json
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QWidget,
)
from PyQt6.QtCore import Qt

from desktop_app.config import Colors, AppMeta, Prefs

# ─── Kimlik bilgileri (hardcoded — DB entegrasyonuna kadar) ────────────────────
_VALID_USERNAME = "admin"
_VALID_PASSWORD = "1234"


class LoginWindow(QDialog):
    """
    Profesyonel koyu login diyaloğu.
    exec() → Accepted: giriş başarılı.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(AppMeta.NAME)
        self.setFixedSize(400, 488)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_pos = None
        self._build_ui()

    # ──────── UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        c = Colors
        self.setStyleSheet(f"background-color: {c.BG_APP};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame(objectName="card")
        card.setStyleSheet(f"""
            QFrame#card {{
                background-color: {c.BG_SURFACE};
                border: 1px solid {c.BORDER};
                border-radius: 8px;
            }}
        """)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Başlık çubuğu ──────────────────────────────────────────
        title_bar = QFrame()
        title_bar.setFixedHeight(42)
        title_bar.setStyleSheet(f"""
            QFrame {{
                background-color: {c.BG_CARD};
                border-bottom: 1px solid {c.BORDER};
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)
        tb = QHBoxLayout(title_bar)
        tb.setContentsMargins(14, 0, 14, 0)

        app_lbl = QLabel(AppMeta.NAME)
        app_lbl.setStyleSheet(
            f"color: {c.TEXT}; font-size: 13px; font-weight: 600;"
            f" background: transparent; font-family: 'Segoe UI', Arial, sans-serif;"
        )
        tb.addWidget(app_lbl)
        tb.addStretch()

        close_btn = QPushButton("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {c.TEXT_MUTED};
                border: none; font-size: 16px; border-radius: 3px;
            }}
            QPushButton:hover {{ background-color: {c.BTN_DANGER_BG}; color: {c.BTN_DANGER_FG}; }}
        """)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.reject)
        tb.addWidget(close_btn)
        lay.addWidget(title_bar)

        # ── Form içeriği ────────────────────────────────────────────
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(28, 24, 28, 28)
        cl.setSpacing(0)

        headline = QLabel("Oturum Açın")
        headline.setStyleSheet(
            f"color: {c.TEXT}; font-size: 19px; font-weight: 600;"
            f" letter-spacing: -0.3px; background: transparent;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        cl.addWidget(headline)

        sub = QLabel("Yönetim paneline erişmek için kimlik bilgilerinizi girin.")
        sub.setStyleSheet(
            f"color: {c.TEXT_MUTED}; font-size: 12px; background: transparent;"
            f" margin-top: 4px; font-family: 'Segoe UI', Arial, sans-serif;"
        )
        sub.setWordWrap(True)
        cl.addWidget(sub)
        cl.addSpacing(20)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {c.BORDER}; border: none;")
        cl.addWidget(div)
        cl.addSpacing(20)

        # Kullanıcı adı
        cl.addWidget(self._field_lbl("Kullanıcı Adı"))
        cl.addSpacing(5)
        self._inp_user = self._make_input("Kullanıcı adınızı girin")
        cl.addWidget(self._inp_user)
        cl.addSpacing(12)

        # Şifre
        cl.addWidget(self._field_lbl("Şifre"))
        cl.addSpacing(5)
        self._inp_pass = self._make_input("Şifrenizi girin", password=True)
        self._inp_pass.returnPressed.connect(self._on_login)
        cl.addWidget(self._inp_pass)

        # Hata
        self._lbl_error = QLabel("")
        self._lbl_error.setStyleSheet(
            f"color: {c.ERROR}; font-size: 11px; background: transparent;"
            f" padding: 6px 0 0 0; font-family: 'Segoe UI', Arial, sans-serif;"
        )
        self._lbl_error.setVisible(False)
        cl.addWidget(self._lbl_error)

        cl.addSpacing(18)

        # Buton
        self._btn_login = QPushButton("Oturum Aç")
        self._btn_login.setFixedHeight(36)
        self._btn_login.setStyleSheet(f"""
            QPushButton {{
                background-color: {c.ACCENT}; color: #FFFFFF;
                border: none; border-radius: 4px;
                font-size: 13px; font-weight: 600;
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QPushButton:hover   {{ background-color: {c.ACCENT_HOVER}; }}
            QPushButton:pressed {{ background-color: {c.ACCENT_PRESS}; }}
        """)
        self._btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_login.clicked.connect(self._on_login)
        cl.addWidget(self._btn_login)

        cl.addStretch()

        footer = QLabel(f"{AppMeta.NAME}  ·  v{AppMeta.VERSION}")
        footer.setStyleSheet(
            f"color: {c.TEXT_SUBTLE}; font-size: 10px;"
            f" background: transparent; margin-top: 14px;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(footer)

        lay.addWidget(content)

    # ──────── Yardımcılar ─────────────────────────────────────────────────────

    def _field_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {Colors.TEXT_MUTED}; font-size: 11px; font-weight: 600;"
            f" letter-spacing: 0.4px; background: transparent;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        return lbl

    def _make_input(self, placeholder: str, password: bool = False) -> QLineEdit:
        c = Colors
        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        inp.setFixedHeight(34)
        if password:
            inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setStyleSheet(f"""
            QLineEdit {{
                background-color: {c.BG_INPUT};
                border: 1px solid {c.BORDER_INPUT};
                border-radius: 4px; padding: 0 12px;
                color: {c.TEXT}; font-size: 13px;
                selection-background-color: {c.ACCENT};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QLineEdit:focus {{ border-color: {c.BORDER_FOCUS}; }}
            QLineEdit[error="true"] {{
                border-color: {c.ERROR};
                background-color: {c.BTN_DANGER_BG};
            }}
        """)
        return inp

    # ──────── Sürükleme ───────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    # ──────── Giriş mantığı ───────────────────────────────────────────────────

    def _on_login(self):
        uname = self._inp_user.text().strip()
        pwd   = self._inp_pass.text()

        if uname == _VALID_USERNAME and pwd == _VALID_PASSWORD:
            self._lbl_error.setVisible(False)
            self._set_err(self._inp_user, False)
            self._set_err(self._inp_pass, False)
            try:
                prefs = {}
                if os.path.exists(Prefs.PATH):
                    with open(Prefs.PATH, "r") as f:
                        prefs = json.load(f)
                prefs[Prefs.KEY_LOGGED_IN] = True
                with open(Prefs.PATH, "w") as f:
                    json.dump(prefs, f)
            except Exception:
                pass
            self.accept()
        else:
            self._lbl_error.setText("Kullanıcı adı veya şifre hatalı.")
            self._lbl_error.setVisible(True)
            self._set_err(self._inp_user, True)
            self._set_err(self._inp_pass, True)
            self._inp_pass.clear()
            self._inp_pass.setFocus()

    @staticmethod
    def _set_err(field: QLineEdit, error: bool):
        field.setProperty("error", "true" if error else "false")
        field.style().unpolish(field)
        field.style().polish(field)
