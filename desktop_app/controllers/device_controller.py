from __future__ import annotations

import logging
from typing import Any

from desktop_app.ui.utils import merge_phone_device_row, phone_row_key

logger = logging.getLogger(__name__)


class DeviceController:
    def __init__(self, backend_api: Any) -> None:
        self._backend_api = backend_api

    def load_paired_phone_devices(self, auth_token: str, pc_id: str) -> tuple[list[dict], bool]:
        merged: dict[str, dict] = {}

        def ingest(rows: list[dict] | None) -> None:
            for device in rows or []:
                if device.get("device_type") != "phone" or device.get("device_id") == pc_id:
                    continue
                key = phone_row_key(device)
                if not key:
                    continue
                merged[key] = merge_phone_device_row(merged.get(key, {}), dict(device))

        if not auth_token:
            return [], False

        bundle, bundle_err = self._backend_api.get_phone_device_bundle(auth_token, pc_id)
        if bundle and bundle.get("ok"):
            ingest(list(bundle.get("devices") or []))
            ingest(list(bundle.get("recent_devices") or []))
            ingest(list(bundle.get("pairings") or []))
            return list(merged.values()) if merged else [], False
        if bundle_err and bundle_err != "bundle_missing":
            low = (bundle_err or "").lower()
            if ("10054" in low) or ("connection aborted" in low) or ("forcibly closed by the remote host" in low):
                logger.info("phone-bundle gecici ag kopmasi: %s", bundle_err)
            else:
                logger.warning("phone-bundle alinamadi: %s", bundle_err)

        devices, err = self._backend_api.get_devices(auth_token)
        if devices is not None:
            ingest(devices)
        else:
            logger.warning("Server devices alinamadi: %s", err)

        recent, err = self._backend_api.get_recent_devices(auth_token, "phone")
        if recent is not None:
            ingest(recent)
        else:
            logger.warning("Server recent devices alinamadi: %s", err)

        pairings, err = self._backend_api.get_pairings(auth_token, pc_id)
        if pairings is not None:
            ingest(pairings)
        else:
            if "Bu cihaza erisim yetkiniz yok" in (err or ""):
                logger.warning("Pairings yetkisiz (oturum sifirlanacak): %s", err)
                return [], True
            logger.warning("Server pairings alinamadi: %s", err)

        return list(merged.values()) if merged else [], False
