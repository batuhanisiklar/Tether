"""
Login Penceresi — Remote Phone Control
=======================================
Sekmeli kart tasarımı: Giriş Yap / Kayıt Ol
Tüm auth işlemleri DbClient üzerinden Neon DB'ye gider.
"""

import os
import json
import logging
import threading

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QWidget, QStackedWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread
from PyQt6.QtGui import QFont

from desktop_app.config import Colors, AppMeta, Prefs
from desktop_app.database.db_client import DbClient

logger = logging.getLogger(__name__)


# ─── Worker: DB işlemlerini arka planda yapar ──────────────────────────────────
class _AuthWorker(QObject):
    finished = pyqtSignal(object, str)

    def __init__(self, fn, *args):
        super().__init__()
        self._fn = fn
        self._args = args

    def run(self):
        try:
            result = self._fn(*self._args)
            self.finished.emit(result, "")
        except Exception as e:
            self.finished.emit(None, str(e))


# ─── Yardımcı stil fonksiyonları ──────────────────────────────────────────────
def _inp_style() -> str:
    c = Colors
    return f"""
        QLineEdit {{
            background-color: {c.BG_INPUT};
            border: 1px solid {c.BORDER_INPUT};
            border-radius: 6px; padding: 0 14px;
            color: {c.TEXT}; font-size: 13px;
            font-family: 'Segoe UI', Arial, sans-serif;
            selection-background-color: {c.ACCENT};
        }}
        QLineEdit:focus {{ border-color: {c.BORDER_FOCUS}; }}
        QLineEdit[error="true"] {{
            border-color: {c.ERROR};
        }}
    """


def _btn_primary_style() -> str:
    c = Colors
    return f"""
        QPushButton {{
            background-color: {c.ACCENT};
            color: #FFFFFF; border: none; border-radius: 6px;
            font-size: 13px; font-weight: 600;
            font-family: 'Segoe UI', Arial, sans-serif;
        }}
        QPushButton:hover   {{ background-color: {c.ACCENT_HOVER}; }}
        QPushButton:pressed {{ background-color: {c.ACCENT_PRESS}; }}
        QPushButton:disabled {{
            background-color: {c.ACCENT_DIM}; color: {c.TEXT_OFF};
        }}
    """


class LoginWindow(QDialog):
    """
    Sekmeli login/register diyaloğu.
    exec() → Accepted: giriş/kayıt başarılı, prefs'e user_id yazılmış.
    """

    def __init__(self, db: DbClient, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(AppMeta.NAME)
        self.setFixedSize(420, 530)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_pos = None
        self._login_worker = None
        self._login_thread = None
        self._reg_worker = None
        self._reg_thread = None
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
                border-radius: 10px;
            }}
        """)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # ── Başlık çubuğu
        lay.addWidget(self._build_title_bar())

        # ── Logo / başlık alanı
        lay.addWidget(self._build_top_brand())

        # ── Sekme butonları
        lay.addWidget(self._build_tab_bar())

        # ── İçerik (stacked)
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        self._stack.addWidget(self._build_login_page())
        self._stack.addWidget(self._build_register_page())
        lay.addWidget(self._stack)

    def _build_title_bar(self) -> QFrame:
        c = Colors
        bar = QFrame()
        bar.setFixedHeight(36)
        bar.setStyleSheet(f"""
            QFrame {{
                background-color: {c.BG_CARD};
                border-bottom: 1px solid {c.BORDER};
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }}
        """)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 10, 0)

        lbl = QLabel(AppMeta.NAME)
        lbl.setStyleSheet(
            f"color: {c.TEXT_MUTED}; font-size: 11px; background: transparent;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        row.addWidget(lbl)
        row.addStretch()

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
        row.addWidget(close_btn)
        return bar

    def _build_top_brand(self) -> QWidget:
        c = Colors
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(32, 24, 32, 16)
        lay.setSpacing(4)

        icon_lbl = QLabel("🔌")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 32px; background: transparent;")
        lay.addWidget(icon_lbl)

        title = QLabel("Remote Phone Control")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {c.TEXT}; font-size: 17px; font-weight: 700;"
            f" background: transparent; font-family: 'Segoe UI', Arial, sans-serif;"
        )
        lay.addWidget(title)

        sub = QLabel("Hesabınıza giriş yapın veya yeni hesap oluşturun")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color: {c.TEXT_MUTED}; font-size: 11px; background: transparent;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        lay.addWidget(sub)
        return w

    def _build_tab_bar(self) -> QWidget:
        c = Colors
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        row = QHBoxLayout(w)
        row.setContentsMargins(32, 0, 32, 0)
        row.setSpacing(0)

        self._tab_login = self._make_tab_btn("Giriş Yap", active=True)
        self._tab_reg   = self._make_tab_btn("Kayıt Ol",  active=False)
        self._tab_login.clicked.connect(lambda: self._switch_tab(0))
        self._tab_reg.clicked.connect(lambda: self._switch_tab(1))

        row.addWidget(self._tab_login)
        row.addWidget(self._tab_reg)
        return w

    def _make_tab_btn(self, text: str, active: bool) -> QPushButton:
        c = Colors
        btn = QPushButton(text)
        btn.setFixedHeight(34)
        btn.setCheckable(True)
        btn.setChecked(active)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_tab_style(btn, active)
        return btn

    def _apply_tab_style(self, btn: QPushButton, active: bool):
        c = Colors
        if active:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {c.ACCENT}; border: none;
                    border-bottom: 2px solid {c.ACCENT};
                    font-size: 13px; font-weight: 600;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    padding: 0 8px;
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {c.TEXT_MUTED}; border: none;
                    border-bottom: 2px solid transparent;
                    font-size: 13px; font-weight: 500;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    padding: 0 8px;
                }}
                QPushButton:hover {{ color: {c.TEXT}; }}
            """)

    def _switch_tab(self, idx: int):
        self._stack.setCurrentIndex(idx)
        self._apply_tab_style(self._tab_login, idx == 0)
        self._apply_tab_style(self._tab_reg,   idx == 1)
        # Hata mesajlarını temizle
        self._lbl_login_err.setText("")
        self._lbl_reg_err.setText("")
        self._lbl_reg_ok.setText("")

    # ── Login sayfası ─────────────────────────────────────────────────────────

    def _build_login_page(self) -> QWidget:
        c = Colors
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(32, 20, 32, 28)
        lay.setSpacing(0)

        lay.addWidget(self._field_lbl("Kullanıcı Adı"))
        lay.addSpacing(5)
        self._inp_user = self._make_input("admin")
        lay.addWidget(self._inp_user)
        lay.addSpacing(12)

        lay.addWidget(self._field_lbl("Şifre"))
        lay.addSpacing(5)
        self._inp_pass = self._make_input("••••••••", password=True)
        self._inp_pass.returnPressed.connect(self._on_login)
        lay.addWidget(self._inp_pass)
        lay.addSpacing(6)

        self._lbl_login_err = QLabel("")
        self._lbl_login_err.setStyleSheet(
            f"color: {c.ERROR}; font-size: 11px; background: transparent;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        self._lbl_login_err.setWordWrap(True)
        lay.addWidget(self._lbl_login_err)
        lay.addSpacing(16)

        self._btn_login = QPushButton("Giriş Yap")
        self._btn_login.setFixedHeight(38)
        self._btn_login.setStyleSheet(_btn_primary_style())
        self._btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_login.clicked.connect(self._on_login)
        lay.addWidget(self._btn_login)

        lay.addStretch()

        ver = QLabel(f"v{AppMeta.VERSION}  ·  {AppMeta.NAME}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(
            f"color: {c.TEXT_SUBTLE}; font-size: 10px; background: transparent;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        lay.addWidget(ver)
        return w

    # ── Register sayfası ──────────────────────────────────────────────────────

    def _build_register_page(self) -> QWidget:
        c = Colors
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(32, 20, 32, 28)
        lay.setSpacing(0)

        lay.addWidget(self._field_lbl("Kullanıcı Adı"))
        lay.addSpacing(5)
        self._inp_reg_user = self._make_input("Kullanıcı adı seçin")
        lay.addWidget(self._inp_reg_user)
        lay.addSpacing(12)

        lay.addWidget(self._field_lbl("Şifre"))
        lay.addSpacing(5)
        self._inp_reg_pass = self._make_input("En az 6 karakter", password=True)
        lay.addWidget(self._inp_reg_pass)
        lay.addSpacing(12)

        lay.addWidget(self._field_lbl("Şifre Tekrar"))
        lay.addSpacing(5)
        self._inp_reg_pass2 = self._make_input("Şifrenizi tekrar girin", password=True)
        self._inp_reg_pass2.returnPressed.connect(self._on_register)
        lay.addWidget(self._inp_reg_pass2)
        lay.addSpacing(6)

        self._lbl_reg_err = QLabel("")
        self._lbl_reg_err.setStyleSheet(
            f"color: {c.ERROR}; font-size: 11px; background: transparent;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        self._lbl_reg_err.setWordWrap(True)
        lay.addWidget(self._lbl_reg_err)

        self._lbl_reg_ok = QLabel("")
        self._lbl_reg_ok.setStyleSheet(
            f"color: {c.SUCCESS}; font-size: 11px; background: transparent;"
            f" font-family: 'Segoe UI', Arial, sans-serif;"
        )
        self._lbl_reg_ok.setWordWrap(True)
        lay.addWidget(self._lbl_reg_ok)

        lay.addSpacing(10)

        self._btn_register = QPushButton("Kayıt Ol")
        self._btn_register.setFixedHeight(38)
        self._btn_register.setStyleSheet(_btn_primary_style())
        self._btn_register.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_register.clicked.connect(self._on_register)
        lay.addWidget(self._btn_register)

        lay.addStretch()
        return w

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
        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        inp.setFixedHeight(36)
        if password:
            inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setStyleSheet(_inp_style())
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

    # ──────── İşlem mantığı ───────────────────────────────────────────────────

    def _set_loading(self, loading: bool, btn: QPushButton):
        btn.setEnabled(not loading)
        btn.setText("Lütfen bekleyin..." if loading else btn.property("original_text"))

    def _on_login(self):
        uname = self._inp_user.text().strip()
        pwd   = self._inp_pass.text()
        if not uname or not pwd:
            self._lbl_login_err.setText("Kullanıcı adı ve şifre boş olamaz.")
            return

        self._lbl_login_err.setText("")
        self._btn_login.setEnabled(False)
        self._btn_login.setText("Giriş yapılıyor...")

        self._login_thread = QThread()
        self._login_worker = _AuthWorker(self.db.authenticate_user, uname, pwd)
        self._login_worker.moveToThread(self._login_thread)
        self._login_thread.started.connect(self._login_worker.run)
        self._login_worker.finished.connect(self._on_login_done)
        self._login_worker.finished.connect(self._login_thread.quit)
        self._login_thread.start()

    def _on_login_done(self, result, err: str):
        self._btn_login.setEnabled(True)
        self._btn_login.setText("Giriş Yap")

        if err:
            self._lbl_login_err.setText(f"Bağlantı hatası: {err}")
            return
        if result is None:
            self._lbl_login_err.setText("Kullanıcı adı veya şifre hatalı.")
            return

        user_id, username = result
        self._save_session(user_id, username)
        self.accept()

    def _on_register(self):
        uname = self._inp_reg_user.text().strip()
        pwd   = self._inp_reg_pass.text()
        pwd2  = self._inp_reg_pass2.text()

        self._lbl_reg_err.setText("")
        self._lbl_reg_ok.setText("")

        if not uname or not pwd:
            self._lbl_reg_err.setText("Tüm alanları doldurun.")
            return
        if pwd != pwd2:
            self._lbl_reg_err.setText("Şifreler eşleşmiyor.")
            return

        self._btn_register.setEnabled(False)
        self._btn_register.setText("Kaydediliyor...")

        self._reg_thread = QThread()
        self._reg_worker = _AuthWorker(self.db.register_user, uname, pwd)
        self._reg_worker.moveToThread(self._reg_thread)
        self._reg_thread.started.connect(self._reg_worker.run)
        self._reg_worker.finished.connect(self._on_register_done)
        self._reg_worker.finished.connect(self._reg_thread.quit)
        self._reg_thread.start()

    def _on_register_done(self, result, err: str):
        self._btn_register.setEnabled(True)
        self._btn_register.setText("Kayıt Ol")

        if err:
            self._lbl_reg_err.setText(f"Bağlantı hatası: {err}")
            return

        success, msg = result
        if success:
            self._lbl_reg_ok.setText(msg)
            # Otomatik giriş sayfasına geç
            QTimer.singleShot(1200, lambda: self._switch_tab(0))
        else:
            self._lbl_reg_err.setText(msg)

    def _save_session(self, user_id: int, username: str):
        prefs = {}
        try:
            if os.path.exists(Prefs.PATH):
                with open(Prefs.PATH, "r") as f:
                    prefs = json.load(f)
        except Exception:
            pass
        prefs[Prefs.KEY_LOGGED_IN] = True
        prefs[Prefs.KEY_USER_ID]   = user_id
        prefs[Prefs.KEY_USERNAME]  = username
        try:
            with open(Prefs.PATH, "w") as f:
                json.dump(prefs, f)
        except Exception:
            pass
