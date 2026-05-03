"""
Giriş penceresi — Remote Phone Control
=======================================
Sekmeli kart tasarımı: Giriş yap / Kayıt ol.
Kimlik doğrulama işlemleri `BackendApi` üzerinden yürütülür.
"""

import logging
import os
import sys

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QWidget, QStackedWidget, QCheckBox, QToolButton,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize
from PyQt6.QtGui import QIcon, QPainter, QPen, QColor, QPixmap

from desktop_app.config import Colors, AppMeta
from desktop_app.config.prefs_store import (
    load_or_create_device_id,
    remembered_login_email,
    save_auth_token,
    clear_remembered_login_email,
    save_remembered_login_email,
    save_session,
    update_prefs,
)
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._backend_api = BackendApi()
        self.setWindowTitle(AppMeta.NAME)
        _win_slack = 24 if sys.platform == "win32" else 0
        self.setMinimumSize(920, 560)
        self.resize(920, 560 + (0 if sys.platform != "win32" else _win_slack))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._drag_pos = None
        self._login_thread = None
        self._reg_thread = None
        self._remembered_email = remembered_login_email()
        self._pending_close = False
        self._phone_fmt_guard = False
        self._build_ui()

    @property
    def shared_backend_api(self) -> BackendApi:
        """Giriş sonrası `MainWindow` ile aynı `requests.Session` kullanılır (TCP bağlantısı yeniden kullanılır)."""
        return self._backend_api


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

        lay.addWidget(self._build_title_bar())

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        row = QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        row.addWidget(self._build_promo_panel())

        right = QWidget()
        right.setStyleSheet("background: transparent;")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(40, 28, 40, 20)
        right_lay.setSpacing(0)

        right_lay.addWidget(self._build_top_brand())
        right_lay.addWidget(self._build_tab_bar())

        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        self._stack.addWidget(self._build_login_page())
        self._stack.addWidget(self._build_register_page())
        right_lay.addWidget(self._stack, 1)

        row.addWidget(right, 1)
        lay.addWidget(body, 1)

        self._update_default_button_for_tab(0)

    def _build_promo_panel(self) -> QFrame:
        c = Colors
        panel = QFrame()
        panel.setFixedWidth(400)
        panel.setStyleSheet(f"""
            QFrame {{
                border-top-left-radius: 6px;
                border-bottom-left-radius: 6px;
                border-right: 1px solid rgba(255, 255, 255, 6);
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0.7, y2: 1,
                    stop: 0 #1E120C,
                    stop: 0.3 #241610,
                    stop: 0.6 #1A1014,
                    stop: 1 {c.BG_APP}
                );
            }}
        """)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(36, 36, 36, 24)
        lay.setSpacing(0)

        logo_container = QLabel()
        logo_container.setFixedSize(88, 88)
        logo_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_container.setStyleSheet(f"""
            QLabel {{
                background: qradialgradient(
                    cx:0.5, cy:0.5, radius:0.7,
                    fx:0.5, fy:0.5,
                    stop:0 rgba(224, 128, 64, 35),
                    stop:0.6 rgba(224, 96, 64, 12),
                    stop:1 transparent
                );
                border-radius: 22px;
            }}
        """)
        pm = self._load_logo_pixmap(88)
        if pm is not None:
            logo_container.setPixmap(pm)
        else:
            logo_container.setText("RPC")
        logo_wrap = QHBoxLayout()
        logo_wrap.setContentsMargins(0, 0, 0, 0)
        logo_wrap.addStretch()
        logo_wrap.addWidget(logo_container)
        logo_wrap.addStretch()
        lay.addLayout(logo_wrap)
        lay.addSpacing(18)

        app_name = QLabel("Remote Phone Control")
        app_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_name.setStyleSheet(text_style(c.TEXT, size=20, weight=800))
        lay.addWidget(app_name)
        lay.addSpacing(6)

        tagline = QLabel("Telefonunuzu bilgisayarınızdan\nkolay ve güvenli şekilde yönetin")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setWordWrap(True)
        tagline.setStyleSheet(text_style(c.TEXT_MUTED, size=11))
        lay.addWidget(tagline)

        lay.addSpacing(32)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255, 255, 255, 8);")
        lay.addWidget(sep)
        lay.addSpacing(24)

        features = [
            ("⚡", "Hızlı eşleştirme", "Sabit adres ile hızlı bağlantı"),
            ("📺", "Canlı görüntü", "Ekran aktarımı ve dokunmatik kontrol"),
            ("🔒", "Güvenli bağlantı", "Uçtan uca şifreli iletişim"),
            ("📱", "Erişilebilirlik", "Telefon kontrolü için yardımcı servis"),
        ]
        for i, (emoji, title, desc) in enumerate(features):
            feat_row = QHBoxLayout()
            feat_row.setContentsMargins(4, 0, 4, 0)
            feat_row.setSpacing(16)

            ico = QLabel(emoji)
            ico.setFixedSize(44, 44)
            ico.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ico.setStyleSheet(f"""
                font-size: 22px;
                background: rgba(224, 96, 64, 15);
                border: 1px solid rgba(224, 96, 64, 20);
                border-radius: 12px;
            """)
            feat_row.addWidget(ico, 0, Qt.AlignmentFlag.AlignVCenter)

            txt_col = QVBoxLayout()
            txt_col.setContentsMargins(0, 0, 0, 0)
            txt_col.setSpacing(2)
            t = QLabel(title)
            t.setStyleSheet(text_style(c.TEXT, size=14, weight=700) + " background: transparent; border: none;")
            txt_col.addWidget(t)
            d = QLabel(desc)
            d.setStyleSheet(text_style(c.TEXT_SUBTLE, size=11) + " background: transparent; border: none;")
            txt_col.addWidget(d)
            feat_row.addLayout(txt_col, 1)

            lay.addLayout(feat_row)
            if i < len(features) - 1:
                lay.addSpacing(18)

        lay.addStretch(1)
        return panel

    def _project_root(self) -> str:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

    def _load_logo_pixmap(self, size: int) -> QPixmap | None:
        """
        `logo.png`'yi güvenli şekilde yükler.
        Null pixmap ise `None` döner (scaled uyarısını engeller).
        """
        logo_path = os.path.join(self._project_root(), "logo.png")
        pm = QPixmap(logo_path)
        if pm.isNull():
            return None
        return pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

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

        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)

        mini = QLabel()
        mini.setFixedSize(18, 18)
        pm = self._load_logo_pixmap(18)
        if pm is not None:
            mini.setPixmap(pm)
        left.addWidget(mini)

        lbl = QLabel(AppMeta.NAME)
        lbl.setStyleSheet(text_style(c.TEXT_MUTED, size=11))
        left.addWidget(lbl)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setStyleSheet("background: transparent;")
        row.addWidget(left_w)
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
        lay.setContentsMargins(0, 0, 0, 12)
        lay.setSpacing(0)

        title = QLabel("Hoş geldiniz")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        title.setStyleSheet(text_style(c.TEXT, size=24, weight=800))
        lay.addWidget(title)
        lay.addSpacing(6)

        sub = QLabel("Devam etmek için giriş yapın veya\nyeni bir hesap oluşturun")
        sub.setAlignment(Qt.AlignmentFlag.AlignLeft)
        sub.setWordWrap(True)
        sub.setStyleSheet(text_style(c.TEXT_MUTED, size=12))
        lay.addWidget(sub)
        return w

    def _build_tab_bar(self) -> QWidget:
        c = Colors
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 16)
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
        btn.setFixedHeight(36)
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
        self._update_default_button_for_tab(idx)
        self._lbl_login_err.setText("")
        self._lbl_reg_err.setText("")
        self._lbl_reg_ok.setText("")

    def _update_default_button_for_tab(self, idx: int):
        """Enter/Return hangi sekmedeyse ilgili ana aksiyonu tetiklesin diye default butonu ayarlar."""
        login_btn = getattr(self, "_btn_login", None)
        reg_btn = getattr(self, "_btn_register", None)
        if login_btn is not None:
            login_btn.setDefault(idx == 0)
            login_btn.setAutoDefault(idx == 0)
        if reg_btn is not None:
            reg_btn.setDefault(idx == 1)
            reg_btn.setAutoDefault(idx == 1)


    def _build_login_page(self) -> QWidget:
        c = Colors
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        lay.addWidget(self._field_lbl("E-posta"))
        lay.addSpacing(8)
        self._inp_user = self._make_input("ornek@eposta.com")
        if self._remembered_email:
            self._inp_user.setText(self._remembered_email)
        lay.addWidget(self._inp_user)
        lay.addSpacing(22)

        lay.addWidget(self._field_lbl("Şifre"))
        lay.addSpacing(8)
        pass_row = QHBoxLayout()
        pass_row.setContentsMargins(0, 0, 0, 0)
        pass_row.setSpacing(8)

        self._inp_pass = self._make_input("••••••••", password=True)
        pass_row.addWidget(self._inp_pass, 1)

        self._btn_pass_eye = self._make_eye_button()
        self._btn_pass_eye.clicked.connect(lambda: self._toggle_password_visible(self._inp_pass, self._btn_pass_eye))
        pass_row.addWidget(self._btn_pass_eye)

        lay.addLayout(pass_row)
        lay.addSpacing(18)

        chk_img = self._check_indicator_images()
        self._chk_remember = QCheckBox("  Beni hatırla")
        self._chk_remember.setCursor(Qt.CursorShape.PointingHandCursor)
        self._chk_remember.setChecked(bool(self._remembered_email))
        self._chk_remember.setStyleSheet(f"""
            QCheckBox {{
                color: {c.TEXT_MUTED};
                font-size: 12px;
                spacing: 6px;
            }}
            QCheckBox:hover {{
                color: {c.TEXT};
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1.5px solid {c.BORDER_INPUT};
                background: {c.BG_INPUT};
            }}
            QCheckBox::indicator:hover {{
                border-color: {c.ACCENT};
            }}
            QCheckBox::indicator:checked {{
                background: {c.ACCENT};
                border: 1.5px solid {c.ACCENT};
                image: url({chk_img});
            }}
        """)
        lay.addWidget(self._chk_remember)
        lay.addSpacing(14)

        self._lbl_login_err = QLabel("")
        self._lbl_login_err.setStyleSheet(text_style(c.ERROR, size=12))
        self._lbl_login_err.setWordWrap(True)
        lay.addWidget(self._lbl_login_err)
        lay.addSpacing(22)

        self._btn_login = QPushButton("Giriş Yap")
        self._btn_login.setFixedHeight(46)
        self._btn_login.setProperty("original_text", "Giriş Yap")
        self._btn_login.setStyleSheet(filled_button_style(font_size=15, font_weight=700))
        self._btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_login.setDefault(True)
        self._btn_login.setAutoDefault(True)
        self._btn_login.clicked.connect(self._on_login)
        lay.addWidget(self._btn_login)

        lay.addStretch(1)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: rgba(255, 255, 255, 6);")
        lay.addWidget(sep)
        lay.addSpacing(14)

        sec_note = QLabel("🔒  Verileriniz güvenli bağlantı ile korunmaktadır")
        sec_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sec_note.setStyleSheet(text_style(c.TEXT_SUBTLE, size=10))
        lay.addWidget(sec_note)
        lay.addSpacing(6)

        ver = QLabel(f"v{AppMeta.VERSION}  ·  {AppMeta.NAME}  ·  © 2026  ·  Batuhan Isiklar")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver.setStyleSheet(text_style(c.TEXT_SUBTLE, size=9))
        lay.addWidget(ver)
        return w


    def _check_indicator_images(self) -> str:
        """
        Checkbox tik işareti için geçici bir PNG oluşturur; CSS image: url(...) ile kullanılır.
        Boş bir ✓ ikonu çizer, kaydeder ve yolunu döner.
        """
        import tempfile
        img_path = os.path.join(tempfile.gettempdir(), "_rpc_check_tick.png")
        if not os.path.exists(img_path):
            sz = 16
            pm = QPixmap(sz, sz)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            pen = QPen(QColor("#FFFFFF"))
            pen.setWidthF(2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            from PyQt6.QtCore import QPointF
            p.drawLine(QPointF(3.0, 8.5), QPointF(6.5, 12.0))
            p.drawLine(QPointF(6.5, 12.0), QPointF(13.0, 4.0))
            p.end()
            pm.save(img_path, "PNG")
        return img_path.replace("\\", "/")

    def _eye_icon(self, *, visible: bool) -> QIcon:
        """
        Basit, profesyonel "eye" ikonu (asset gerektirmez).
        visible=False → göz (şifre gizli, gösterilebilir)
        visible=True  → üstü çizgili göz (şifre görünür, gizlenebilir)
        """
        c = Colors
        px = 22
        pm = QIcon().pixmap(px, px)  # placeholder; overwritten below
        from PyQt6.QtGui import QPixmap  # lokal import, startup maliyeti düşük
        pm = QPixmap(px, px)
        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(c.TEXT_MUTED))
        pen.setWidthF(1.6)
        p.setPen(pen)

        p.drawArc(3, 7, px - 6, px - 12, 0 * 16, 180 * 16)
        p.drawArc(3, 7, px - 6, px - 12, 180 * 16, 180 * 16)
        p.setBrush(QColor(c.TEXT_MUTED))
        p.drawEllipse(px // 2 - 2, px // 2 - 2, 4, 4)
        p.setBrush(Qt.BrushStyle.NoBrush)

        if visible:
            slash = QPen(QColor(c.TEXT_SUBTLE))
            slash.setWidthF(2.0)
            p.setPen(slash)
            p.drawLine(5, px - 6, px - 5, 6)

        p.end()
        return QIcon(pm)

    def _toggle_password_visible(self, inp: QLineEdit, btn: QToolButton):
        is_hidden = inp.echoMode() == QLineEdit.EchoMode.Password
        inp.setEchoMode(QLineEdit.EchoMode.Normal if is_hidden else QLineEdit.EchoMode.Password)
        btn.setIcon(self._eye_icon(visible=is_hidden))


    def _build_register_page(self) -> QWidget:
        c = Colors
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        row1_lbl = QHBoxLayout()
        row1_lbl.setContentsMargins(0, 0, 0, 0)
        row1_lbl.setSpacing(12)
        row1_lbl.addWidget(self._field_lbl("Ad"))
        row1_lbl.addWidget(self._field_lbl("Soyad"))
        lay.addLayout(row1_lbl)
        lay.addSpacing(5)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(12)
        self._inp_reg_first = self._make_input("Adınız")
        self._inp_reg_last = self._make_input("Soyadınız")
        row1.addWidget(self._inp_reg_first, 1)
        row1.addWidget(self._inp_reg_last, 1)
        lay.addLayout(row1)
        lay.addSpacing(12)

        row2_lbl = QHBoxLayout()
        row2_lbl.setContentsMargins(0, 0, 0, 0)
        row2_lbl.setSpacing(12)
        row2_lbl.addWidget(self._field_lbl("E-posta"))
        row2_lbl.addWidget(self._field_lbl("Telefon (isteğe bağlı)"))
        lay.addLayout(row2_lbl)
        lay.addSpacing(5)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(12)
        self._inp_reg_email = self._make_input("ornek@eposta.com")
        self._inp_reg_phone = self._make_input("0(312) 456 78 90")
        self._inp_reg_phone.textChanged.connect(self._on_reg_phone_text_changed)
        row2.addWidget(self._inp_reg_email, 1)
        row2.addWidget(self._inp_reg_phone, 1)
        lay.addLayout(row2)
        lay.addSpacing(12)

        lay.addWidget(self._field_lbl("Şifre"))
        lay.addSpacing(5)
        reg_pass_row = QHBoxLayout()
        reg_pass_row.setContentsMargins(0, 0, 0, 0)
        reg_pass_row.setSpacing(8)
        self._inp_reg_pass = self._make_input("En az 6 karakter", password=True)
        reg_pass_row.addWidget(self._inp_reg_pass, 1)
        self._btn_reg_pass_eye = self._make_eye_button()
        self._btn_reg_pass_eye.clicked.connect(lambda: self._toggle_password_visible(self._inp_reg_pass, self._btn_reg_pass_eye))
        reg_pass_row.addWidget(self._btn_reg_pass_eye)
        lay.addLayout(reg_pass_row)
        lay.addSpacing(12)

        lay.addWidget(self._field_lbl("Şifre Tekrar"))
        lay.addSpacing(5)
        reg_pass2_row = QHBoxLayout()
        reg_pass2_row.setContentsMargins(0, 0, 0, 0)
        reg_pass2_row.setSpacing(8)
        self._inp_reg_pass2 = self._make_input("Şifrenizi tekrar girin", password=True)
        reg_pass2_row.addWidget(self._inp_reg_pass2, 1)
        self._btn_reg_pass2_eye = self._make_eye_button()
        self._btn_reg_pass2_eye.clicked.connect(lambda: self._toggle_password_visible(self._inp_reg_pass2, self._btn_reg_pass2_eye))
        reg_pass2_row.addWidget(self._btn_reg_pass2_eye)
        lay.addLayout(reg_pass2_row)
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
        self._btn_register.setDefault(False)
        self._btn_register.setAutoDefault(False)
        self._btn_register.clicked.connect(self._on_register)
        lay.addWidget(self._btn_register)

        lay.addStretch()
        return w


    def _field_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(text_style(Colors.TEXT_MUTED, size=12, weight=600, letter_spacing=0.4))
        return lbl

    @staticmethod
    def _format_phone_tr_display(raw: str) -> str:
        """0(312) 456 78 90 — en fazla 11 rakam."""
        d = "".join(c for c in raw if c.isdigit())[:11]
        if not d:
            return ""
        sb: list[str] = [d[0]]
        if len(d) >= 2:
            sb.append("(")
            sb.append(d[1:min(4, len(d))])
            if len(d) >= 4:
                sb.append(") ")
                sb.append(d[4:min(7, len(d))])
        if len(d) >= 7:
            sb.append(" ")
            sb.append(d[7:min(9, len(d))])
        if len(d) >= 9:
            sb.append(" ")
            sb.append(d[9:min(11, len(d))])
        return "".join(sb)

    def _on_reg_phone_text_changed(self, _text: str):
        if self._phone_fmt_guard:
            return
        inp = self._inp_reg_phone
        formatted = self._format_phone_tr_display(inp.text())
        if formatted != inp.text():
            self._phone_fmt_guard = True
            inp.setText(formatted)
            inp.setCursorPosition(len(formatted))
            self._phone_fmt_guard = False

    def _make_input(self, placeholder: str, password: bool = False) -> QLineEdit:
        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        inp.setFixedHeight(40)
        if password:
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            inp.setProperty("is_password_field", True)
            inp.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            inp.setDragEnabled(False)
            inp.installEventFilter(self)
        inp.setStyleSheet(line_edit_style(font_size=14))
        return inp

    def _make_eye_button(self) -> QToolButton:
        """Şifre göster/gizle butonu oluşturur (ortak yardımcı)."""
        c = Colors
        btn = QToolButton()
        btn.setIcon(self._eye_icon(visible=False))
        btn.setIconSize(QSize(18, 18))
        btn.setFixedSize(36, 36)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QToolButton {{
                background-color: {c.BG_INPUT};
                border: 1px solid {c.BORDER_INPUT};
                border-radius: 6px;
            }}
            QToolButton:hover {{
                background-color: {c.BG_CARD};
                border-color: {c.BORDER_FOCUS};
            }}
        """)
        return btn

    def eventFilter(self, obj, event):
        """Şifre alanlarında (görünürken) kopyala/kes/yapıştır engeller."""
        from PyQt6.QtCore import QEvent
        if isinstance(obj, QLineEdit) and bool(obj.property("is_password_field")):
            if obj.echoMode() == QLineEdit.EchoMode.Normal and event.type() == QEvent.Type.KeyPress:
                from PyQt6.QtGui import QKeyEvent, QKeySequence
                key_event: QKeyEvent = event
                if (
                    key_event.matches(QKeySequence.StandardKey.Copy)
                    or key_event.matches(QKeySequence.StandardKey.Cut)
                    or key_event.matches(QKeySequence.StandardKey.Paste)
                    or key_event.matches(QKeySequence.StandardKey.SelectAll)
                ):
                    return True
                if (key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier) and key_event.key() == Qt.Key.Key_Insert:
                    return True
                if (key_event.modifiers() & Qt.KeyboardModifier.ControlModifier) and key_event.key() == Qt.Key.Key_Insert:
                    return True
        return super().eventFilter(obj, event)


    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._stack.currentIndex() == 0:
                if getattr(self, "_btn_login", None) is not None and self._btn_login.isEnabled():
                    self._on_login()
                    return
            else:
                if getattr(self, "_btn_register", None) is not None and self._btn_register.isEnabled():
                    self._on_register()
                    return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        """Pencere kapanırken çalışan asenkron DB thread'lerini güvenlice sonlandırır."""
        if not self._wait_for_auth_threads():
            self._pending_close = True
            self._show_busy_message("Kimlik doğrulama işlemi tamamlanana kadar pencere kapatılamaz.")
            event.ignore()
            return
        super().closeEvent(event)


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
            msg = (api_result or {}).get("message", "Giriş başarısız.")
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
                    "auth_error": "Sunucu yanıtı geçersiz.",
                "token": "",
                "address": "",
            }
        username = str(user.get("username") or email)
        resolved_device_id = str(user.get("device_id") or user.get("address") or "").strip()
        address = resolved_device_id
        if resolved_device_id and resolved_device_id.isdigit() and len(resolved_device_id) == 12 and resolved_device_id != device_id:
            try:
                update_prefs(**{"device_id": resolved_device_id})
            except Exception:
                pass
        first_name = str(user.get("first_name") or "").strip()
        last_name = str(user.get("last_name") or "").strip()
        return {
            "auth_result": (int(uid), username),
            "auth_error": "",
            "token": token,
            "address": address,
            "first_name": first_name,
            "last_name": last_name,
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
            return False, "Şifreler eşleşmiyor."
        if len(password) < 6:
            return False, "Şifre en az 6 karakter olmalıdır."
        em = email.strip().lower()
        if "@" not in em or len(em) < 5:
            return False, "Lütfen geçerli bir e-posta adresi girin."
        if not first_name.strip() or not last_name.strip():
            return False, "Ad ve soyad alanları zorunludur."
        device_id = load_or_create_device_id()
        mac_fp = get_mac_fingerprint()
        phone_digits = "".join(c for c in phone if c.isdigit())
        data, err = self._backend_api.register(
            email=em,
            password=password,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=phone_digits,
            device_id=device_id,
            device_name=self._desktop_device_name(),
            mac_address=mac_fp,
        )
        if err:
            return False, err
        if not data or not data.get("ok"):
            return False, (data or {}).get("message", "Kayıt işlemi başarısız.")
        return True, "Kayıt başarılı. Şimdi giriş yapabilirsiniz."

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
            self._lbl_login_err.setText("E-posta ve şifre alanları boş bırakılamaz.")
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
            self._lbl_login_err.setText(result.get("auth_error") or "E-posta veya şifre hatalı.")
            return

        user_id, username = auth_result
        em = self._inp_user.text().strip().lower()
        if getattr(self, "_chk_remember", None) is not None and self._chk_remember.isChecked():
            save_remembered_login_email(em)
        else:
            clear_remembered_login_email()
        token = result.get("token", "")
        address = result.get("address", "")
        first_name = str(result.get("first_name") or "").strip()
        last_name = str(result.get("last_name") or "").strip()
        if token:
            save_auth_token(token)
        self._save_session(user_id, username, address, em, first_name, last_name)
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
            self._lbl_reg_err.setText("E-posta ve şifre alanları zorunludur.")
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
            QTimer.singleShot(1200, lambda: self._switch_tab(0))
        else:
            self._lbl_reg_err.setText(msg)

    def _save_session(
        self,
        user_id: int,
        username: str,
        address: str = "",
        login_email: str = "",
        first_name: str = "",
        last_name: str = "",
    ):
        save_session(user_id, username, address, login_email, first_name, last_name)
