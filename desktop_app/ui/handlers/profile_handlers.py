"""
Profil/Ayarlar drawer iş mantığı mixin'i.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation
from PyQt6.QtWidgets import QMessageBox

from desktop_app.config.constants import Prefs
from desktop_app.config.prefs_store import (
    clear_paired_phone_address,
    clear_paired_phone_id,
    update_prefs,
)
from desktop_app.ui.styles.app_styles import (
    MAIN_FOOTER_BAR_HEIGHT,
    MAIN_NAV_BAR_HEIGHT,
    WIN_CHROME_BAR_HEIGHT,
)
from desktop_app.ui.theme import filled_button_style, outline_button_style

logger = logging.getLogger(__name__)


class ProfileHandlersMixin:
    """Ayarlar drawer açma/kapama, hesap işlemleri ve toplu cihaz kaldırma."""

    def _open_profile_drawer(self) -> None:
        if not self._auth_token:
            self._set_status("Ayarları görmek için tekrar giriş yapın.", error=True)
            return

        self._clear_profile_errors()
        profile, err = self._backend_api.get_me(self._auth_token, self._ws_client.device_id)
        self._profile_cache = dict(profile) if profile else {}
        self._profile_load_err.hide()
        self._profile_load_err.setText("")
        if err:
            self._profile_load_err.setText(err)
            self._profile_load_err.show()

        if profile:
            fn = str(profile.get("first_name") or "").strip()
            ln = str(profile.get("last_name") or "").strip()
            em = str(profile.get("email") or self._user_email or "").strip().lower()
            ph = str(profile.get("phone") or "").strip()
            self._apply_profile_summary(fn, ln, em, ph)
        else:
            fn = (self._user_first_name or "").strip()
            ln = (self._user_last_name or "").strip()
            em = (self._user_email or "").strip().lower()
            ph = ""
            self._apply_profile_summary(fn, ln, em, ph)

        self._profile_inp_email.setText(self._current_profile_email())
        self._profile_inp_phone.setText(self._current_profile_phone())
        self._profile_delete_inp_email.clear()
        self._profile_delete_inp_password.clear()
        self._profile_delete_info.setText(
            f"Bu işlem geri alınamaz. Devam etmek için hesap e-postanızı ({self._current_profile_email()}) ve şifrenizi yazın."
        )
        self._profile_inp_old.clear()
        self._profile_inp_pwd1.clear()
        self._profile_inp_pwd2.clear()
        self._set_profile_panel(None)
        self._set_profile_drawer_open(True)

    @staticmethod
    def _profile_initials(first_name: str, last_name: str, email: str) -> str:
        a = (first_name or "").strip()[:1].upper()
        b = (last_name or "").strip()[:1].upper()
        if a and b:
            return f"{a}{b}"
        if a:
            return a
        em = (email or "").strip()
        return em[:1].upper() if em else "?"

    def _apply_profile_summary(self, first_name: str, last_name: str, email: str, phone: str) -> None:
        full = f"{first_name} {last_name}".strip() or "—"
        self._profile_view_name.setText(full)
        self._profile_view_email.setText(email or "—")
        self._profile_view_phone.setText(phone or "—")
        self._profile_avatar_lbl.setText(self._profile_initials(first_name, last_name, email))

    def _current_profile_email(self) -> str:
        profile_email = str((self._profile_cache or {}).get("email") or "").strip().lower()
        return profile_email or (self._user_email or "").strip().lower()

    def _current_profile_phone(self) -> str:
        return str((self._profile_cache or {}).get("phone") or "").strip()

    @staticmethod
    def _normalize_phone_digits(raw_phone: str) -> str:
        return "".join(ch for ch in (raw_phone or "") if ch.isdigit())

    def _clear_profile_errors(self) -> None:
        self._profile_email_err.setText("")
        self._profile_phone_err.setText("")
        self._profile_pwd_err.setText("")
        self._profile_delete_err.setText("")

    def _on_profile_email_cancel(self) -> None:
        self._profile_inp_email.setText(self._current_profile_email())
        self._profile_email_err.setText("")
        self._set_profile_panel(None)

    def _on_profile_phone_cancel(self) -> None:
        self._profile_inp_phone.setText(self._current_profile_phone())
        self._profile_phone_err.setText("")
        self._set_profile_panel(None)

    def _on_profile_pwd_cancel(self) -> None:
        self._profile_pwd_err.setText("")
        self._profile_inp_old.clear()
        self._profile_inp_pwd1.clear()
        self._profile_inp_pwd2.clear()
        self._set_profile_panel(None)

    def _on_profile_delete_cancel(self) -> None:
        self._profile_delete_err.setText("")
        self._profile_delete_inp_email.clear()
        self._profile_delete_inp_password.clear()
        self._set_profile_panel(None)

    def _set_profile_panel(self, which: str | None) -> None:
        self._clear_profile_errors()

        self._profile_actions_block.setVisible(which is None)
        self._profile_email_block.setVisible(which == "email")
        self._profile_phone_block.setVisible(which == "phone")
        self._profile_pwd_block.setVisible(which == "password")
        self._profile_delete_block.setVisible(which == "delete")

        self._profile_action_email.setStyleSheet(
            filled_button_style() if which == "email" else outline_button_style()
        )
        self._profile_action_phone.setStyleSheet(
            filled_button_style() if which == "phone" else outline_button_style()
        )
        self._profile_action_pwd.setStyleSheet(
            filled_button_style() if which == "password" else outline_button_style()
        )

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
        end_x = (cw_w - self._profile_drawer_width) if open_ else cw_w

        if open_:
            self._profile_drawer.show()
            self._profile_drawer.raise_()

        start_pos = QPoint(start_x, top)
        end_pos = QPoint(end_x, top)
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

    def _apply_profile_update(self, data: dict, fallback_email: str, fallback_phone: str) -> None:
        user = (data or {}).get("user") or {}
        token = str((data or {}).get("token") or "")
        if token:
            self._auth_token = token
            self._ws_client.set_auth_token(token)
            update_prefs(**{Prefs.KEY_AUTH_TOKEN: token})

        new_email = str(user.get("email") or fallback_email).strip().lower()
        self._user_email = new_email
        update_prefs(**{Prefs.KEY_USER_EMAIL: new_email})

        fn = str(user.get("first_name") or self._user_first_name or "").strip()
        ln = str(user.get("last_name") or self._user_last_name or "").strip()
        if fn or ln:
            self._user_first_name = fn
            self._user_last_name = ln
            update_prefs(**{Prefs.KEY_USER_FIRST_NAME: fn, Prefs.KEY_USER_LAST_NAME: ln})

        ph = str(user.get("phone") or fallback_phone or "").strip()
        self._profile_cache = {
            "first_name": fn,
            "last_name": ln,
            "email": new_email,
            "phone": ph,
        }
        self._apply_profile_summary(fn, ln, new_email, ph)
        self._profile_inp_email.setText(new_email)
        self._profile_inp_phone.setText(ph)
        self._profile_delete_info.setText(
            f"Bu işlem geri alınamaz. Devam etmek için hesap e-postanızı ({new_email}) ve şifrenizi yazın."
        )
        self._refresh_home_summary()

    def _save_email_from_drawer(self) -> None:
        if not self._auth_token:
            self._profile_email_err.setText("Oturum bulunamadı. Tekrar giriş yapın.")
            return
        new_email = self._profile_inp_email.text().strip().lower()
        if not new_email or "@" not in new_email or len(new_email) < 5:
            self._profile_email_err.setText("Geçerli bir e-posta adresi girin.")
            return

        data, err = self._backend_api.update_profile(
            self._auth_token,
            email=new_email,
            phone=None,
            old_password=None,
            password=None,
            password2=None,
        )
        if err:
            self._profile_email_err.setText(err)
            return

        self._apply_profile_update(data or {}, new_email, self._current_profile_phone())
        self._set_status("E-posta güncellendi.")
        self._set_profile_panel(None)

    def _save_phone_from_drawer(self) -> None:
        if not self._auth_token:
            self._profile_phone_err.setText("Oturum bulunamadı. Tekrar giriş yapın.")
            return

        new_phone = self._normalize_phone_digits(self._profile_inp_phone.text().strip())
        self._profile_inp_phone.setText(new_phone)
        if len(new_phone) != 11:
            self._profile_phone_err.setText("Telefon numarası 11 hane olmalıdır.")
            return
        email = self._current_profile_email()
        data, err = self._backend_api.update_profile(
            self._auth_token,
            email=email,
            phone=new_phone,
            old_password=None,
            password=None,
            password2=None,
        )
        if err:
            self._profile_phone_err.setText(err)
            return

        self._apply_profile_update(data or {}, email, new_phone)
        self._set_status("Telefon numarası güncellendi.")
        self._set_profile_panel(None)

    def _save_password_from_drawer(self) -> None:
        if not self._auth_token:
            self._profile_pwd_err.setText("Oturum bulunamadı. Tekrar giriş yapın.")
            return

        oldp = self._profile_inp_old.text()
        p1 = self._profile_inp_pwd1.text()
        p2 = self._profile_inp_pwd2.text()
        if not oldp:
            self._profile_pwd_err.setText("Mevcut şifre gerekli.")
            return
        if not p1 or not p2:
            self._profile_pwd_err.setText("Yeni şifreyi iki alana da girin.")
            return
        if oldp == p1:
            self._profile_pwd_err.setText("Mevcut şifre ile yeni şifre aynı olamaz.")
            return
        if p1 != p2:
            self._profile_pwd_err.setText("Yeni şifreler eşleşmiyor.")
            return
        if len(p1) < 6:
            self._profile_pwd_err.setText("Şifre en az 6 karakter olmalıdır.")
            return

        data, err = self._backend_api.update_profile(
            self._auth_token,
            email=None,
            phone=None,
            old_password=oldp,
            password=p1,
            password2=p2,
        )
        if err:
            self._profile_pwd_err.setText(err)
            return

        self._apply_profile_update(
            data or {},
            self._current_profile_email(),
            self._current_profile_phone(),
        )
        self._set_status("Şifre güncellendi.")
        self._on_profile_pwd_cancel()

    def _delete_account_from_drawer(self) -> None:
        if not self._auth_token:
            self._profile_delete_err.setText("Oturum bulunamadı. Tekrar giriş yapın.")
            return

        account_email = self._current_profile_email()
        typed_email = self._profile_delete_inp_email.text().strip().lower()
        password = self._profile_delete_inp_password.text()

        if not account_email:
            self._profile_delete_err.setText("Hesap e-postası bulunamadı.")
            return
        if typed_email != account_email:
            self._profile_delete_err.setText("Yazdığınız e-posta hesap e-postasıyla eşleşmiyor.")
            return
        if not password:
            self._profile_delete_err.setText("Şifrenizi girin.")
            return

        self._profile_delete_confirm_btn.setEnabled(False)
        ok, err = self._backend_api.delete_account(
            self._auth_token,
            email=typed_email,
            password=password,
        )
        self._profile_delete_confirm_btn.setEnabled(True)
        if not ok:
            self._profile_delete_err.setText(err or "Hesap silinemedi.")
            return

        self._set_status("Hesabınız silindi.")
        self._on_logout()

    def _clear_all_connections_from_drawer(self) -> None:
        card_list = list(self._device_cards.values())
        total = len(card_list)
        if total == 0:
            self._set_status("Kaldırılacak eşleşmiş cihaz yok.")
            return
        if not self._auth_token:
            self._set_status("Cihazları kaldırmak için tekrar giriş yapın.", error=True)
            return

        answer = QMessageBox.question(
            self,
            "Tüm Cihazları Kaldır",
            f"{total} eşleşmiş cihaz kaydı kalıcı olarak kaldırılacak. Silmek istiyor musunuz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._profile_btn_clear_connections.setEnabled(False)
        cleared = 0
        failed = 0
        removed_active = False

        for card in card_list:
            ok, _err = self._backend_api.delete_pairing(
                self._auth_token,
                self._ws_client.device_id,
                card.device_id,
                card.address,
            )
            if ok:
                cleared += 1
                if self._paired_phone_id == card.device_id or self._paired_phone_address == card.address:
                    removed_active = True
            else:
                failed += 1

        self._profile_btn_clear_connections.setEnabled(True)

        self._load_devices_from_db()
        self._ws_client.send_request_presence()
        self._refresh_home_summary()

        if removed_active:
            self._paired_phone_id = None
            self._paired_phone_address = None
            clear_paired_phone_address()
            clear_paired_phone_id()
            self._ws_client.forget_paired_phone()
            self._on_disconnect()
            return

        if failed == 0:
            self._set_status(f"{cleared} eşleşmiş cihaz kaldırıldı.")
        elif cleared == 0:
            self._set_status("Cihazlar kaldırılamadı. Lütfen tekrar deneyin.", error=True)
        else:
            self._set_status(f"{cleared} cihaz kaldırıldı, {failed} cihaz kaldırılamadı.", error=True)
