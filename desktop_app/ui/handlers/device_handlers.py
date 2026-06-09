"""
Cihaz yönetimi mixin'i.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import pyqtSlot

from desktop_app.config.prefs_store import (
    clear_paired_phone_address,
    clear_paired_phone_id,
)
from desktop_app.ui.components.confirm_dialog import confirm_forget_pairing
from desktop_app.ui.components.device_card import DeviceCard
from desktop_app.ui.utils import address_digits, merge_phone_device_row, phone_row_key, session_tab_label

logger = logging.getLogger(__name__)


class DeviceHandlersMixin:
    """Cihaz listesi yükleme, kartlar, bağlantı ve eşleşme kaldırma."""

    def _load_paired_devices(self) -> list[dict]:
        merged: dict[str, dict] = {}
        pc_id = self._ws_client.device_id

        def _ingest(rows: list[dict] | None) -> None:
            for device in rows or []:
                if device.get("device_type") != "phone" or device.get("device_id") == pc_id:
                    continue
                key = phone_row_key(device)
                if not key:
                    continue
                merged[key] = merge_phone_device_row(merged.get(key, {}), dict(device))

        if self._auth_token:
            bundle, bundle_err = self._backend_api.get_phone_device_bundle(
                self._auth_token, pc_id
            )
            if bundle and bundle.get("ok"):
                _ingest(list(bundle.get("recent_devices") or []))
                _ingest(list(bundle.get("pairings") or []))
                return list(merged.values()) if merged else []
            if bundle_err and bundle_err != "bundle_missing":
                low = (bundle_err or "").lower()
                if ("10054" in low) or ("connection aborted" in low) or ("forcibly closed by the remote host" in low):
                    logger.info("phone-bundle geçici ağ kopması: %s", bundle_err)
                else:
                    logger.warning("phone-bundle alinamadi: %s", bundle_err)

            from desktop_app.config.prefs_store import clear_logged_in
            pairings, err = self._backend_api.get_pairings(self._auth_token, pc_id)
            if pairings is not None:
                _ingest(pairings)
            else:
                if "Bu cihaza erisim yetkiniz yok" in (err or ""):
                    logger.warning("Pairings yetkisiz (oturum sıfırlanacak): %s", err)
                    clear_logged_in()
                    self._auth_token = ""
                    return []
                logger.warning("Server pairings alinamadi: %s", err)

            return list(merged.values()) if merged else []
        return []

    def _populate_device_cards(self, devices: list[dict]):
        for card in self._device_cards.values():
            self._recent_devices_layout.removeWidget(card)
            card.deleteLater()
        self._device_cards.clear()

        db_online = {
            str(d["device_id"]) for d in devices if bool(d.get("is_online"))
        }
        self._online_paired_devices = set(db_online)

        if not devices:
            self._lbl_no_devices.show()
            self._lbl_device_count.setText("")
            return

        self._lbl_no_devices.hide()
        for device in devices:
            card = DeviceCard(
                device["device_id"],
                device.get("address"),
                device.get("device_name"),
                device.get("owner_name"),
                device.get("owner_phone"),
                device.get("owner_email"),
            )
            key = card.card_key()
            card.set_online(key in self._online_paired_devices)
            card.set_connect_callback(self._on_card_connect)
            card.set_forget_callback(self._on_card_forget)
            self._device_cards[key] = card

        online_count = sum(
            1 for d in devices if str(d["device_id"]) in self._online_paired_devices
        )
        self._lbl_device_count.setText(
            f"{online_count} aktif / {len(devices)} cihaz" if devices else ""
        )
        self._reflow_device_cards()
        self._refresh_home_summary()

    def _card_for_member_device(self, device_id: str) -> DeviceCard | None:
        for card in self._device_cards.values():
            if device_id == card.device_id:
                return card
        return None

    def _reflow_device_cards(self):
        while self._recent_devices_layout.count():
            self._recent_devices_layout.takeAt(0)
        ordered = sorted(
            self._device_cards.items(),
            key=lambda item: (not item[1].is_online(),),
        )
        cols = max(1, (self.width() - 60) // (DeviceCard.CARD_W + 18))
        for idx, (_, card) in enumerate(ordered):
            self._recent_devices_layout.addWidget(card, idx // cols, idx % cols)
        for col in range(cols):
            self._recent_devices_layout.setColumnStretch(col, 1)

    def _on_card_connect(self, card_key: str):
        card = self._device_cards.get(card_key)
        if not card:
            return
        addr = card.connection_address()
        if not card.is_online():
            self._set_status("Bu cihaz şu an çevrimiçi değil.", error=True)
            return
        if addr:
            self._inp_code.setText(addr)
            self._inp_code.setFocus()
            self._paired_phone_address = address_digits(addr)
        self._paired_phone_id = card.device_id
        label = session_tab_label(card.owner_name, card.display_name(), card.address)
        self._tab_session_btn.setText(f"  {label}")
        self._tab_session.show()
        self._switch_page(1)
        self._connect_session_mode(
            partner_device_id=None if addr else card.device_id,
            partner_address=addr,
            status_message="Seçilen cihaza bağlanılıyor...",
        )

    def _on_card_forget(self, card_key: str):
        card = self._device_cards.get(card_key)
        if not card:
            return
        if not confirm_forget_pairing(self, card.display_name()):
            return
        if not self._auth_token:
            self._set_status("Eşleşmeyi sunucudan silmek için tekrar giriş yapın.", error=True)
            return

        success, error_msg = self._backend_api.delete_pairing(
            self._auth_token, self._ws_client.device_id, card.device_id, card.address,
        )
        if not success:
            self._set_status(error_msg or "Eşleşme silinemedi.", error=True)
            return

        self._load_devices_from_db()
        self._online_paired_devices.discard(str(card.device_id))

        if self._paired_phone_address == card.address or self._paired_phone_id == card.device_id:
            self._paired_phone_id      = None
            self._paired_phone_address = None
            clear_paired_phone_address()
            clear_paired_phone_id()
            self._ws_client.forget_paired_phone()
            self._on_disconnect()
            return

        self._ws_client.send_request_presence()
        self._refresh_home_summary()
        self._set_status("Eşleşme kaldırıldı.")
