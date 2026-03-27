"""
Login Penceresi — Remote Phone Control
=======================================
Sekmeli kart tasarımı: Giriş Yap / Kayıt Ol
Tüm auth işlemleri DbClient üzerinden Neon DB'ye gider.
"""

import logging
import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QWidget, QStackedWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread

from desktop_app.config import Colors, AppMeta
from desktop_app.config.prefs_store import (
    load_or_create_device_id,
    remembered_login_email,
    save_auth_token,
    save_remembered_login_email,
    save_session,
)
from desktop_app.database.db_client import DbClient
from desktop_app.network.backend_api import BackendApi
from desktop_app.network.hardware_id import get_mac_fingerprint
from desktop_app.ui.theme import (
    card_style,
    filled_button_style,
    line_edit_style,
    outline_button_style,
    tab_button_style,
    text_style,
)

logger = logging.getLogger(__name__)


class _AuthThread(QThread):
    finished_with_result = pyqtSignal(object, str)

    def __init__(self, fn, *args):
        super().__init__()
        self._fn = fn
        self._args = args

    def run(self):
        try:
            result = self._fn(*self._args)
            self.finished_with_result.emit(result, "")
        except Exception as e:
            self.finished_with_result.emit(None, str(e))


class LoginWindow(QDialog):
    """
    Sekmeli login/register diyaloğu.
    exec() → Accepted: giriş/kayıt başarılı, prefs'e user_id yazılmış.
    """

    def __init__(self, db: DbClient, parent=None):
        super().__init__(parent)
        self.db = db
        self._backend_api = BackendApi()
        self.setWindowTitle(AppMeta.NAME)
        self.setFixedSize(420, 720)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_pos = None
        self._login_thread = None
        self._reg_thread = None
        self._remembered_email = remembered_login_email()
        self._pending_close = False
        self._build_ui()

    # ──────── UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        c = Colors
        self.setStyleSheet(f"background-color: {c.BG_APP};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame(objectName="card")
        card.setStyleSheet(f"QFrame#card {{ {card_style(background=c.BG_SURFACE)} }}")
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
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
            }}
        """)
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 0, 10, 0)

        lbl = QLabel(AppMeta.NAME)
        lbl.setStyleSheet(text_style(c.TEXT_MUTED, size=11))
        row.addWidget(lbl)
        row.addStretch()

        close_btn = QPushButton("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            outline_button_style(
                background="transparent",
                foreground=c.TEXT_MUTED,
                border_color="transparent",
                hover_background=c.BTN_DANGER_BG,
                hover_foreground=c.BTN_DANGER_FG,
                hover_border=c.BTN_DANGER_BDR,
                radius=6,
                font_size=16,
            )
        )
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

        icon_lbl = QLabel("◈")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 32px; background: transparent;")
        lay.addWidget(icon_lbl)

        title = QLabel("Remote Phone Control")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(text_style(c.TEXT, size=18, weight=700))
        lay.addWidget(title)

        sub = QLabel("Hesabınıza giriş yapın veya yeni hesap oluşturun")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(text_style(c.TEXT_MUTED, size=11))
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
        btn.setStyleSheet(tab_button_style(active))

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

        lay.addWidget(self._field_lbl("E-posta"))
        lay.addSpacing(5)
        self._inp_user = self._make_input("ornek@eposta.com")
        if self._remembered_email:
            self._inp_user.setText(self._remembered_email)
        lay.addWidget(self._inp_user)
        lay.addSpacing(12)

        lay.addWidget(self._field_lbl("Şifre"))
        lay.addSpacing(5)
        self._inp_pass = self._make_input("••••••••", password=True)
        self._inp_pass.returnPressed.connect(self._on_login)
        lay.addWidget(self._inp_pass)
        lay.addSpacing(6)

        self._lbl_login_err = QLabel("")
        self._lbl_login_err.setStyleSheet(text_style(c.ERROR, size=11))
        self._lbl_login_err.setWordWrap(True)
        lay.addWidget(self._lbl_login_err)
        lay.addSpacing(16)

        self._btn_login = QPushButton("Giriş Yap")
        self._btn_login.setFixedHeight(38)
        self._btn_login.setProperty("original_text", "Giriş Yap")
        self._btn_login.setStyleSheet(filled_button_style())
        self._btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_login.clicked.connect(self._on_login)
        lay.addWidget(self._btn_login)

        lay.addStretch()

        helper = QLabel("Son giris yapilan e-posta otomatik hatirlanir")
        helper.setAlignment(Qt.AlignmentFlag.AlignCenter)
        helper.setStyleSheet(text_style(c.TEXT_MUTED, size=10))
        lay.addWidget(helper)
        lay.addSpacing(10)

        ver = QLabel(f"v{AppMeta.VERSION}  ·  {AppMeta.NAME}")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(text_style(c.TEXT_SUBTLE, size=10))
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

        lay.addWidget(self._field_lbl("Ad"))
        lay.addSpacing(5)
        self._inp_reg_first = self._make_input("Adiniz")
        lay.addWidget(self._inp_reg_first)
        lay.addSpacing(10)

        lay.addWidget(self._field_lbl("Soyad"))
        lay.addSpacing(5)
        self._inp_reg_last = self._make_input("Soyadiniz")
        lay.addWidget(self._inp_reg_last)
        lay.addSpacing(10)

        lay.addWidget(self._field_lbl("E-posta"))
        lay.addSpacing(5)
        self._inp_reg_email = self._make_input("ornek@eposta.com")
        lay.addWidget(self._inp_reg_email)
        lay.addSpacing(10)

        lay.addWidget(self._field_lbl("Telefon (istege bagli)"))
        lay.addSpacing(5)
        self._inp_reg_phone = self._make_input("05xx xxx xx xx")
        lay.addWidget(self._inp_reg_phone)
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
        self._lbl_reg_err.setStyleSheet(text_style(c.ERROR, size=11))
        self._lbl_reg_err.setWordWrap(True)
        lay.addWidget(self._lbl_reg_err)

        self._lbl_reg_ok = QLabel("")
        self._lbl_reg_ok.setStyleSheet(text_style(c.SUCCESS, size=11))
        self._lbl_reg_ok.setWordWrap(True)
        lay.addWidget(self._lbl_reg_ok)

        lay.addSpacing(10)

        self._btn_register = QPushButton("Kayıt Ol")
        self._btn_register.setFixedHeight(38)
        self._btn_register.setProperty("original_text", "Kayıt Ol")
        self._btn_register.setStyleSheet(filled_button_style())
        self._btn_register.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_register.clicked.connect(self._on_register)
        lay.addWidget(self._btn_register)

        lay.addStretch()
        return w

    # ──────── Yardımcılar ─────────────────────────────────────────────────────

    def _field_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(text_style(Colors.TEXT_MUTED, size=11, weight=600, letter_spacing=0.4))
        return lbl

    def _make_input(self, placeholder: str, password: bool = False) -> QLineEdit:
        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        inp.setFixedHeight(36)
        if password:
            inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setStyleSheet(line_edit_style())
        return inp

    # ──────── Sürükleme ve Kapanış ────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def closeEvent(self, event):
        """Pencere kapanırken çalışan asenkron DB thread'lerini güvenlice sonlandırır."""
        if not self._wait_for_auth_threads():
            self._pending_close = True
            self._show_busy_message("Kimlik doğrulama işlemi tamamlanana kadar pencere kapatılamaz.")
            event.ignore()
            return
        super().closeEvent(event)

    # ──────── İşlem mantığı ───────────────────────────────────────────────────

    def _set_loading(self, loading: bool, btn: QPushButton):
        btn.setEnabled(not loading)
        default_text = btn.property("original_text") or btn.text()
        btn.setText("Lütfen bekleyin..." if loading else default_text)

    def _show_busy_message(self, message: str):
        if self._stack.currentIndex() == 0:
            self._lbl_login_err.setText(message)
        else:
            self._lbl_reg_err.setText(message)

    def _wait_for_auth_threads(self) -> bool:
        for thread in (self._login_thread, self._reg_thread):
            if thread and thread.isRunning():
                thread.wait(5000)
                if thread.isRunning():
                    return False
        return True

    def _cleanup_auth_task(self, thread_attr: str):
        thread = getattr(self, thread_attr)
        if thread is not None:
            thread.deleteLater()
        setattr(self, thread_attr, None)
        if self._pending_close and self._wait_for_auth_threads():
            self.reject()

    def _desktop_device_name(self) -> str:
        return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "Bu Bilgisayar"

    def _authenticate_login_session(self, email: str, password: str):
        device_id = load_or_create_device_id()
        mac_fp = get_mac_fingerprint()
        api_result, api_error = self._backend_api.login(
            email=email.strip().lower(),
            password=password,
            device_id=device_id,
            device_name=self._desktop_device_name(),
            mac_address=mac_fp,
        )
        if api_error:
            return {
                "auth_result": None,
                "auth_error": api_error,
                "token": "",
                "address": "",
            }
        if not api_result or not api_result.get("ok"):
            msg = (api_result or {}).get("message", "Giris basarisiz.")
            return {
                "auth_result": None,
                "auth_error": msg,
                "token": "",
                "address": "",
            }
        token = str(api_result.get("token") or "")
        user = api_result.get("user") or {}
        uid = user.get("id")
        if uid is None:
            return {
                "auth_result": None,
                "auth_error": "Sunucu yaniti gecersiz.",
                "token": "",
                "address": "",
            }
        username = str(user.get("username") or email)
        address = str(user.get("address") or "")
        return {
            "auth_result": (int(uid), username),
            "auth_error": "",
            "token": token,
            "address": address,
        }

    def _register_via_api(
        self,
        first_name: str,
        last_name: str,
        email: str,
        phone: str,
        password: str,
        password2: str,
    ) -> tuple[bool, str]:
        if password != password2:
            return False, "Sifreler eslesmiyor."
        if len(password) < 6:
            return False, "Sifre en az 6 karakter olmali."
        em = email.strip().lower()
        if "@" not in em or len(em) < 5:
            return False, "Gecerli bir e-posta girin."
        if not first_name.strip() or not last_name.strip():
            return False, "Ad ve soyad zorunludur."
        device_id = load_or_create_device_id()
        mac_fp = get_mac_fingerprint()
        data, err = self._backend_api.register(
            email=em,
            password=password,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=phone.strip(),
            device_id=device_id,
            device_name=self._desktop_device_name(),
            mac_address=mac_fp,
        )
        if err:
            return False, err
        if not data or not data.get("ok"):
            return False, (data or {}).get("message", "Kayit basarisiz.")
        return True, "Kayit basarili! Giris yapabilirsiniz."

    def _start_auth_task(self, thread_attr: str, fn, done_handler, *args):
        thread = _AuthThread(fn, *args)
        thread.finished_with_result.connect(done_handler)
        thread.finished.connect(lambda: self._cleanup_auth_task(thread_attr))
        setattr(self, thread_attr, thread)
        thread.start()

    def _on_login(self):
        uname = self._inp_user.text().strip()
        pwd   = self._inp_pass.text()
        if not uname or not pwd:
            self._lbl_login_err.setText("E-posta ve sifre bos olamaz.")
            return

        self._lbl_login_err.setText("")
        self._set_loading(True, self._btn_login)
        self._btn_login.setText("Giriş yapılıyor...")
        self._start_auth_task("_login_thread", self._authenticate_login_session, self._on_login_done, uname, pwd)

    def _on_login_done(self, result, err: str):
        self._set_loading(False, self._btn_login)

        if err:
            self._lbl_login_err.setText(f"Bağlantı hatası: {err}")
            return

        auth_result = result.get("auth_result")
        auth_error = result.get("auth_error", "")
        if auth_error:
            self._lbl_login_err.setText(auth_error)
            return
        if auth_result is None:
            self._lbl_login_err.setText(result.get("auth_error") or "E-posta veya sifre hatali.")
            return

        user_id, username = auth_result
        em = self._inp_user.text().strip().lower()
        save_remembered_login_email(em)
        token = result.get("token", "")
        address = result.get("address", "")
        if token:
            save_auth_token(token)
        self._save_session(user_id, username, address, em)
        self.accept()

    def _on_register(self):
        first = self._inp_reg_first.text()
        last = self._inp_reg_last.text()
        em = self._inp_reg_email.text().strip()
        phone = self._inp_reg_phone.text().strip()
        pwd = self._inp_reg_pass.text()
        pwd2 = self._inp_reg_pass2.text()

        self._lbl_reg_err.setText("")
        self._lbl_reg_ok.setText("")

        if not em or not pwd:
            self._lbl_reg_err.setText("E-posta ve sifre zorunludur.")
            return

        self._set_loading(True, self._btn_register)
        self._btn_register.setText("Kaydediliyor...")
        self._start_auth_task(
            "_reg_thread",
            self._register_via_api,
            self._on_register_done,
            first,
            last,
            em,
            phone,
            pwd,
            pwd2,
        )

    def _on_register_done(self, result, err: str):
        self._set_loading(False, self._btn_register)

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

    def _save_session(self, user_id: int, username: str, address: str = "", login_email: str = ""):
        save_session(user_id, username, address, login_email)
