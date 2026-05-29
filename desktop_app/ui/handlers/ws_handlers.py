"""
WebSocket olay isleyici mixin'i.
MainWindow tarafindan coklu kalitim ile kullanilir.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, QTimer, pyqtSlot

from desktop_app.config import ServerDefaults, Ui
from desktop_app.config.prefs_store import (
    clear_logged_in,
    load_paired_phone_address,
    load_paired_phone_id,
)
from desktop_app.network.ws_client import WsClient
from desktop_app.ui.utils import address_digits, is_accessibility_ws_error

logger = logging.getLogger(__name__)


class WsHandlersMixin:
    """WebSocket baglanti / eslesme / hata olaylari."""

    @pyqtSlot()
    def _on_ws_connected(self):
        self._manual_disconnect = False
        self._set_status(Ui.MSG_SERVER_CONNECTED)
        self._btn_disconnect.setEnabled(True)
        if self._ws_mode == "presence":
            if not self._presence_timer.isActive():
                self._presence_timer.start()
            self._load_devices_from_db()
            self._ws_client.send_request_presence()
        else:
            self._presence_timer.stop()

    @pyqtSlot(str)
    def _on_ws_disconnected(self, reason: str):
        was_manual = self._manual_disconnect
        was_remote = self._ws_mode == "session" and self._connected
        restore_digits = ""

        if was_remote and not was_manual:
            restore_digits = address_digits(self._paired_phone_address or "")
            if len(restore_digits) != 12:
                restore_digits = address_digits(load_paired_phone_address() or "")
            if len(restore_digits) != 12:
                restore_digits = address_digits(self._ws_client.join_session_code or "")

        self._reconnect_session_code = (
            restore_digits
            if (was_remote and not was_manual and len(restore_digits) == 12)
            else None
        )
        self._manual_disconnect = False
        self._btn_connect.setEnabled(True)
        if was_manual:
            return

        self._set_connected(False)
        self._switch_page(0)
        self._screen.clear_frame()
        self._phone_accessibility_enabled = None
        self._phone_media_muted = None
        self._remote_frame_visible = False
        self._presence_timer.stop()
        for card in self._device_cards.values():
            card.set_online(False)
        self._online_paired_devices.clear()
        self._refresh_home_summary()

        if "10060" in reason or "timed out" in reason.lower():
            self._set_status(Ui.MSG_DISCONNECT_TIMEOUT, error=True)
        elif "already closed" in reason.lower():
            self._set_status("Baglanti kapandi.", error=True)
        else:
            self._set_status(f"Baglanti kesildi: {reason}", error=True)

    @pyqtSlot(str)
    def _on_paired(self, stream_url: str):
        # Disconnect/presence moduna gecildiyse kuyrukta kalmis paired/stream_info olaylarini yok say.
        if self._ws_mode != "session":
            logger.debug("paired/stream_info yoksayildi: ws_mode=%s", self._ws_mode)
            return

        already_streaming = self._connected and self._remote_frame_visible
        if already_streaming:
            logger.debug("Tekrarlayan paired/stream_info sinyali - akis zaten aktif, yoksayildi")
            return

        self._remote_frame_visible = False

        paired_phone_id = load_paired_phone_id()
        paired_phone_address = load_paired_phone_address()

        if paired_phone_id or paired_phone_address:
            pid = str(paired_phone_id) if paired_phone_id else ""
            addr = address_digits(paired_phone_address) if paired_phone_address else ""
            missing = (pid and pid not in self._device_cards) or (
                bool(addr) and not any(c.address == addr for c in self._device_cards.values())
            )
            if missing:
                self._load_devices_from_db()
            card = self._device_cards.get(pid) if pid else None
            if card is None and addr:
                card = next((c for c in self._device_cards.values() if c.address == addr), None)
            if card is None and paired_phone_id:
                card = self._card_for_member_device(paired_phone_id)
            if card:
                self._paired_phone_id = card.device_id
                self._paired_phone_address = card.address
                card.set_online(True)

        if not self._connected:
            self._set_connected(True)
            self._switch_page(1)
            self._set_status("Eslesme tamamlandi. Goruntu akisi bekleniyor...")
        self._refresh_home_summary()

        # Akis tamamen WebSocket uzerinden yurur.
        _ = stream_url

        if not self._screen_capture_prompt_sent:
            self._screen_capture_prompt_sent = True
            QTimer.singleShot(700, self._request_phone_screen_capture)
        self._refresh_paired_stream_status()

    @pyqtSlot(list, list, object, object)
    def _on_paired_devices_status(
        self,
        paired_devices: list,
        online_devices: list,
        phone_a11y: object,
        phone_media_muted: object,
    ):
        from desktop_app.ui.utils import ws_device_id_set

        online_ids = ws_device_id_set(online_devices)
        incoming_paired_ids = ws_device_id_set(paired_devices)

        current_ids = {str(k).strip() for k in self._device_cards if str(k).strip()}
        if incoming_paired_ids != current_ids or not self._device_cards:
            self._load_devices_from_db()
        self._online_paired_devices.clear()
        for key, card in self._device_cards.items():
            ck = str(key).strip()
            on = bool(ck) and ck in online_ids
            card.set_online(on)
            if on:
                self._online_paired_devices.add(key)

        self._reflow_device_cards()
        online_count = len(self._online_paired_devices)
        self._lbl_device_count.setText(
            f"{online_count} aktif / {len(self._device_cards)} cihaz"
            if self._device_cards else ""
        )

        if not self._connected:
            if online_count:
                self._set_status(f"Sunucuya baglandi - {online_count} cihaz cevrimici")
            else:
                self._set_status(Ui.MSG_SERVER_CONNECTED)

        if phone_a11y is not WsClient.PHONE_A11Y_UNCHANGED:
            self._phone_accessibility_enabled = None if phone_a11y is None else bool(phone_a11y)
        if phone_media_muted is not WsClient.PHONE_MEDIA_MUTED_UNCHANGED:
            self._phone_media_muted = None if phone_media_muted is None else bool(phone_media_muted)
        self._update_volume_mute_button_label()

        self._refresh_home_summary()
        if self._connected:
            self._refresh_paired_stream_status()

    @pyqtSlot()
    def _on_peer_disconnected(self):
        self._ws_mode = "presence"
        self._screen.clear_frame()
        self._phone_accessibility_enabled = None
        self._phone_media_muted = None
        self._remote_frame_visible = False
        self._set_connected(False)
        self._switch_page(0)
        if self._auth_token:
            self._load_devices_from_db()
        else:
            pid = str(self._paired_phone_id) if self._paired_phone_id else ""
            if pid and pid in self._device_cards:
                self._device_cards[pid].set_online(False)
            self._online_paired_devices.discard(pid)
        self._refresh_home_summary()
        self._ws_client.send_request_presence()
        self._set_status(Ui.MSG_PEER_DISCONNECTED, error=True)

    @pyqtSlot(str, str)
    def _on_error(self, msg: str, code: str = ""):
        text = (msg or "").strip()
        if is_accessibility_ws_error(text, code):
            banner_title = "Erisilebilirlik kapali"
            banner_body = text or "Telefonda Erisilebilirlik servisi acilmadan baglanti baslatilamaz."
            self._a11y_recovery_token += 1
            recovery_token = self._a11y_recovery_token

            session_code = address_digits(self._paired_phone_address or "")
            if len(session_code) != 12:
                session_code = address_digits(load_paired_phone_address() or "")
            if len(session_code) != 12:
                session_code = address_digits(self._ws_client.join_session_code or "")
            if len(session_code) == 12:
                self._a11y_pending_reconnect_code = session_code
                logger.info("Erisilebilirlik hatasi - yeniden baglanti kodu: %s", session_code)

            def _apply_banner() -> None:
                self._screen.clear_frame()
                self._phone_accessibility_enabled = False
                self._remote_frame_visible = False
                self._set_connected(False)
                self._switch_page(0)
                self._show_warning_banner(banner_title, banner_body)
                self._refresh_home_summary()
                if self._ws_mode == "session":
                    self._ws_mode = "presence"
                    self._manual_disconnect = True
                    self._ws_client.disconnect()
                    QTimer.singleShot(
                        300,
                        lambda: (
                            self._connect_presence_channel("Cihaz durumu izleniyor...")
                            if (
                                self._a11y_recovery_token == recovery_token
                                and self._ws_mode == "presence"
                                and not self._connected
                            )
                            else None
                        ),
                    )

            QTimer.singleShot(0, _apply_banner)
        self._set_status(f"Hata: {msg}", error=True)

    @pyqtSlot(int)
    def _on_reconnecting(self, attempt: int):
        """Otomatik yeniden baglanma denemesi basladiginda durum guncelle."""
        self._set_status(f"Yeniden baglaniliyor... (deneme {attempt})")
