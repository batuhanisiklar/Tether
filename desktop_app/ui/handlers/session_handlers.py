"""
Oturum / adres yönetimi ve logout mixin'i.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer, pyqtSlot
from PyQt6.QtWidgets import QApplication, QDialog

from desktop_app.config import ServerDefaults
from desktop_app.config.prefs_store import (
    clear_logged_in,
    clear_paired_phone_id,
    save_paired_phone_address,
)
from desktop_app.ui.utils import (
    address_digits,
    cursor_for_digit_count,
    digits_before_cursor,
    format_address,
    session_tab_label,
)

logger = logging.getLogger(__name__)


class SessionHandlersMixin:
    """Bağlantı kurma, kesme, adres formatı ve logout."""

    def _connect_presence_mode(self, status_message: str | None = None):
        if self._logging_out:
            return
        if self._ws_mode == "session" and self._connected:
            logger.info("Presence bağlantısı atlandı: aktif uzak oturum korunuyor")
            return
        self._ws_mode = "presence"
        self._mjpeg.stop()
        self._presence_timer.stop()
        if status_message:
            self._set_status(status_message)
        self._manual_disconnect = True
        self._ws_client.connect_with_device_id(ServerDefaults.DEFAULT_URL)

    def _connect_session_mode(
        self,
        partner_device_id: str | None = None,
        partner_address: str | None = None,
        status_message: str | None = None,
    ):
        addr_digits = address_digits(partner_address or "")
        if not partner_device_id and not addr_digits:
            return
        self._a11y_recovery_token += 1
        self._ws_mode = "session"
        self._mjpeg.stop()
        self._rotation_step = 0
        self._apply_rotation_step()
        self._paired_phone_id      = partner_device_id
        self._paired_phone_address = addr_digits or None
        self._presence_timer.stop()
        if status_message:
            self._set_status(status_message)
        self._manual_disconnect = True
        if addr_digits:
            save_paired_phone_address(addr_digits)
        session_code = addr_digits or address_digits(partner_device_id or "")
        if not session_code:
            return
        self._ws_client.connect_to_server(ServerDefaults.DEFAULT_URL, session_code)

    def _connect_presence_channel(self, status_message: str | None = None):
        self._connect_presence_mode(status_message)

    def _submit_static_address(self, raw_value: str) -> None:
        if not raw_value:
            self._set_status("Adres girilmedi.", error=True)
            return
        if not raw_value.isdigit():
            self._set_status("Adres yalnızca rakamlardan oluşmalıdır.", error=True)
            return
        if len(raw_value) != 12:
            self._set_status("Lütfen 12 haneli sabit adresi girin.", error=True)
            return

        self._manual_disconnect = True
        self._btn_connect.setEnabled(False)
        self._set_status("Cihaz adresine bağlanılıyor...")

        matching_card = next(
            (c for c in self._device_cards.values()
             if (c.connection_address() or "") == format_address(raw_value)),
            None,
        )
        self._paired_phone_id      = matching_card.device_id if matching_card else None
        self._paired_phone_address = raw_value
        save_paired_phone_address(raw_value)

        if matching_card:
            label = session_tab_label(
                matching_card.owner_name, matching_card.display_name(), matching_card.address
            )
        else:
            label = session_tab_label(None, "Bağlanıyor", raw_value)
        self._tab_session_btn.setText(f"  {label}")
        self._tab_session.show()
        self._switch_page(1)
        self._connect_session_mode(
            partner_device_id=self._paired_phone_id,
            partner_address=raw_value,
            status_message="Cihaz adresine bağlanılıyor...",
        )
        self._refresh_home_summary()

    @pyqtSlot()
    def _on_connect(self):
        self._submit_static_address(
            "".join(ch for ch in self._inp_code.text() if ch.isdigit())
        )

    @pyqtSlot(str)
    def _on_address_text_changed(self, text: str):
        digits    = "".join(ch for ch in text if ch.isdigit())[:12]
        formatted = format_address(digits)
        if text != formatted:
            old_cursor = self._inp_code.cursorPosition()
            digit_pos  = digits_before_cursor(text, old_cursor)
            self._inp_code.blockSignals(True)
            self._inp_code.setText(formatted)
            self._inp_code.blockSignals(False)
            self._inp_code.setCursorPosition(cursor_for_digit_count(formatted, digit_pos))

    @pyqtSlot()
    def _on_disconnect(self):
        self._a11y_recovery_token += 1
        self._ws_mode                     = "presence"
        self._reconnect_session_code      = None
        self._a11y_pending_reconnect_code = None
        self._rotation_step               = 0
        self._presence_timer.stop()
        self._manual_disconnect = True
        self._mjpeg.stop()
        self._ws_client.disconnect(send_logout=True)
        self._screen.clear_frame()
        self._phone_accessibility_enabled = None
        self._remote_frame_visible = False
        self._set_connected(False)
        self._switch_page(0)
        for card in self._device_cards.values():
            card.set_online(False)
        QTimer.singleShot(150, lambda: self._connect_presence_channel("Cihaz durumu izleniyor..."))

    @pyqtSlot()
    def _on_logout(self):
        if self._logging_out:
            return
        self._a11y_recovery_token += 1
        self._logging_out = True
        self._mjpeg.stop()
        self._presence_timer.stop()
        self._manual_disconnect = True
        self._ws_client.disconnect(send_logout=True)
        self._screen.clear_frame()
        self._phone_accessibility_enabled = None
        self._remote_frame_visible = False
        clear_logged_in()
        clear_paired_phone_id()

        from desktop_app.ui.login_window import LoginWindow

        self.hide()
        login = LoginWindow()
        if login.exec() == QDialog.DialogCode.Accepted:
            from desktop_app.ui.app_window import MainWindow
            replacement = MainWindow(backend_api=login.shared_backend_api)
            app = QApplication.instance()
            if app is not None:
                setattr(app, "_rpc_main_window", replacement)
            replacement.show()
            self.close()
        else:
            app = QApplication.instance()
            self.close()
            if app is not None:
                app.quit()
            return
        self._logging_out = False
