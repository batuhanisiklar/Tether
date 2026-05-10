"""
Profil drawer iş mantığı mixin'i.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve

from desktop_app.config.constants import Prefs
from desktop_app.config.prefs_store import update_prefs
from desktop_app.ui.styles.app_styles import (
    MAIN_FOOTER_BAR_HEIGHT,
    MAIN_NAV_BAR_HEIGHT,
    WIN_CHROME_BAR_HEIGHT,
)
from desktop_app.ui.theme import filled_button_style, outline_button_style

logger = logging.getLogger(__name__)


class ProfileHandlersMixin:
    """Profil drawer açma/kapama, kaydetme, şifre değiştirme."""

    def _open_profile_drawer(self) -> None:
        if not self._auth_token:
            self._set_status("Profil bilgilerine erişmek için tekrar giriş yapın.", error=True)
            return
        self._profile_err.setText("")

        profile, err = self._backend_api.get_me(self._auth_token, self._ws_client.device_id)
        self._profile_cache = dict(profile) if profile else {}
        self._profile_load_err.hide()
        self._profile_load_err.setText("")
        if err:
            self._profile_load_err.setText(err)
            self._profile_load_err.show()

        if profile:
            fn   = str(profile.get("first_name") or "").strip()
            ln   = str(profile.get("last_name") or "").strip()
            em   = str(profile.get("email") or self._user_email or "").strip()
            ph   = str(profile.get("phone") or "").strip()
            full = f"{fn} {ln}".strip() or "—"
            self._profile_view_name.setText(full)
            self._profile_view_email.setText(em or "—")
            self._profile_view_phone.setText(ph or "—")
            self._profile_readonly_name.setText(full)
            self._profile_inp_email.setText(em)
            self._profile_inp_phone.setText(ph)
            self._profile_avatar_lbl.setText(self._profile_initials(fn, ln, em))
        else:
            fn, ln = self._user_first_name, self._user_last_name
            full   = f"{fn} {ln}".strip() or "—"
            self._profile_view_name.setText(full)
            self._profile_view_email.setText(self._user_email or "—")
            self._profile_view_phone.setText("—")
            self._profile_readonly_name.setText(full)
            self._profile_inp_email.setText(self._user_email or "")
            self._profile_inp_phone.setText("")
            self._profile_avatar_lbl.setText(
                self._profile_initials(fn, ln, self._user_email)
            )

        self._profile_inp_old.setText("")
        self._profile_inp_pwd1.setText("")
        self._profile_inp_pwd2.setText("")
        self._set_profile_drawer_open(True)
        self._set_profile_panel(None)

    @staticmethod
    def _profile_initials(first_name: str, last_name: str, email: str) -> str:
        a = (first_name or "").strip()[:1].upper()
        b = (last_name  or "").strip()[:1].upper()
        if a and b:
            return f"{a}{b}"
        if a:
            return a
        em = (email or "").strip()
        return em[:1].upper() if em else "?"

    def _on_profile_cancel(self) -> None:
        self._profile_err.setText("")
        p = self._profile_cache
        if p:
            em = str(p.get("email") or "").strip()
            ph = str(p.get("phone") or "").strip()
            fn = str(p.get("first_name") or "").strip()
            ln = str(p.get("last_name") or "").strip()
        else:
            em = (self._user_email or "").strip()
            ph = ""
            fn = (self._user_first_name or "").strip()
            ln = (self._user_last_name  or "").strip()
        self._profile_inp_email.setText(em)
        self._profile_inp_phone.setText(ph)
        self._profile_readonly_name.setText(f"{fn} {ln}".strip() or "—")
        self._profile_inp_pwd1.setText("")
        self._profile_inp_pwd2.setText("")
        self._set_profile_panel(None)

    def _on_profile_pwd_cancel(self) -> None:
        self._profile_pwd_err.setText("")
        self._profile_inp_old.setText("")
        self._profile_inp_pwd1.setText("")
        self._profile_inp_pwd2.setText("")
        self._set_profile_panel(None)

    def _set_profile_panel(self, which: str | None) -> None:
        self._profile_err.setText("")
        self._profile_pwd_err.setText("")
        self._profile_edit_block.setVisible(which == "edit")
        self._profile_pwd_block.setVisible(which == "password")
        if which == "edit":
            self._profile_action_edit.setStyleSheet(filled_button_style())
            self._profile_action_pwd.setStyleSheet(outline_button_style())
        elif which == "password":
            self._profile_action_edit.setStyleSheet(outline_button_style())
            self._profile_action_pwd.setStyleSheet(filled_button_style())
        else:
            self._profile_action_edit.setStyleSheet(filled_button_style())
            self._profile_action_pwd.setStyleSheet(outline_button_style())

    def _close_profile_drawer(self) -> None:
        self._set_profile_drawer_open(False)

    def _profile_drawer_geometry(self) -> tuple[int, int, int]:
        cw = getattr(self, "_main_card", self.centralWidget())
        if cw is None:
            return 0, 160, self.width()
        top = WIN_CHROME_BAR_HEIGHT + MAIN_NAV_BAR_HEIGHT
        bottom_gap = MAIN_FOOTER_BAR_HEIGHT
        inner_h = cw.height() - top - bottom_gap
        return top, max(160, inner_h), cw.width()

    def _set_profile_drawer_open(self, open_: bool) -> None:
        if self._profile_drawer_open == open_:
            return
        self._profile_drawer_open = open_

        top, drawer_h, cw_w = self._profile_drawer_geometry()
        self._profile_drawer.setFixedHeight(drawer_h)

        start_x = cw_w if open_ else (cw_w - self._profile_drawer_width)
        end_x   = (cw_w - self._profile_drawer_width) if open_ else cw_w

        if open_:
            self._profile_drawer.show()
            self._profile_drawer.raise_()

        start_pos = QPoint(start_x, top)
        end_pos   = QPoint(end_x, top)
        self._profile_drawer.move(start_pos)

        if self._profile_anim is not None:
            try:
                self._profile_anim.stop()
            except Exception:
                pass

        anim = QPropertyAnimation(self._profile_drawer, b"pos", self)
        anim.setDuration(220)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.setStartValue(start_pos)
        anim.setEndValue(end_pos)
        anim.finished.connect(
            lambda: self._profile_drawer.hide() if not self._profile_drawer_open else None
        )
        self._profile_anim = anim
        anim.start()

    def _save_profile_from_drawer(self) -> None:
        if not self._auth_token:
            self._profile_err.setText("Oturum bulunamadi. Tekrar giris yapin.")
            return
        em = self._profile_inp_email.text().strip().lower()
        if not em or "@" not in em or len(em) < 5:
            self._profile_err.setText("Gecerli bir e-posta girin.")
            return
        phone = self._profile_inp_phone.text().strip()

        data, err = self._backend_api.update_profile(
            self._auth_token, email=em, phone=phone,
            old_password=None, password=None, password2=None,
        )
        if err:
            self._profile_err.setText(err)
            return

        user  = (data or {}).get("user") or {}
        token = str((data or {}).get("token") or "")
        if token:
            self._auth_token = token
            self._ws_client.set_auth_token(token)
            update_prefs(**{Prefs.KEY_AUTH_TOKEN: token})

        new_email = str(user.get("email") or em).strip().lower()
        self._user_email = new_email
        update_prefs(**{Prefs.KEY_USER_EMAIL: new_email})

        fn = str(user.get("first_name") or "").strip()
        ln = str(user.get("last_name") or "").strip()
        if fn or ln:
            self._user_first_name = fn
            self._user_last_name  = ln
            update_prefs(**{Prefs.KEY_USER_FIRST_NAME: fn, Prefs.KEY_USER_LAST_NAME: ln})

        self._profile_cache = dict(user)
        full    = f"{fn} {ln}".strip() or "—"
        ph_disp = str(user.get("phone") or phone or "").strip()
        self._profile_view_name.setText(full)
        self._profile_view_email.setText(new_email or "—")
        self._profile_view_phone.setText(ph_disp or "—")
        self._profile_readonly_name.setText(full)
        self._profile_avatar_lbl.setText(self._profile_initials(fn, ln, new_email))
        self._set_status("Profil güncellendi.")
        self._refresh_home_summary()
        self._close_profile_drawer()

    def _save_password_from_drawer(self) -> None:
        if not self._auth_token:
            self._profile_pwd_err.setText("Oturum bulunamadi. Tekrar giris yapin.")
            return
        oldp = self._profile_inp_old.text()
        p1   = self._profile_inp_pwd1.text()
        p2   = self._profile_inp_pwd2.text()
        if not oldp:
            self._profile_pwd_err.setText("Mevcut şifre gerekli.")
            return
        if not p1 or not p2:
            self._profile_pwd_err.setText("Yeni şifre iki kere girilmelidir.")
            return
        if p1 != p2:
            self._profile_pwd_err.setText("Yeni şifreler eşleşmiyor.")
            return
        if len(p1) < 6:
            self._profile_pwd_err.setText("Şifre en az 6 karakter olmalıdır.")
            return

        email = (self._profile_inp_email.text() or "").strip().lower() or self._user_email
        phone = (self._profile_inp_phone.text() or "").strip()
        data, err = self._backend_api.update_profile(
            self._auth_token, email=email, phone=phone,
            old_password=oldp, password=p1, password2=p2,
        )
        if err:
            self._profile_pwd_err.setText(err)
            return
        token = str((data or {}).get("token") or "")
        if token:
            self._auth_token = token
            self._ws_client.set_auth_token(token)
            update_prefs(**{Prefs.KEY_AUTH_TOKEN: token})
        self._set_status("Şifre güncellendi.")
        self._on_profile_pwd_cancel()
