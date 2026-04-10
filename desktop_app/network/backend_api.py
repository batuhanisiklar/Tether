from __future__ import annotations

import logging
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectTimeout, ReadTimeout, RequestException

from desktop_app.config import ServerDefaults

logger = logging.getLogger(__name__)

_TIMEOUT_CONNECT = 25
_TIMEOUT_READ = 90
_TIMEOUT_READ_AUTH = 180


def _http_base(ws_url: str) -> str:
    u = (ws_url or "").strip()
    if u.startswith("wss://"):
        return "https://" + u[6:].split("/")[0].rstrip("/")
    if u.startswith("ws://"):
        return "http://" + u[5:].split("/")[0].rstrip("/")
    return u.rstrip("/")


class BackendApi:
    def __init__(self, base_ws_url: str | None = None) -> None:
        self._base = _http_base(base_ws_url or ServerDefaults.DEFAULT_URL)
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=10, max_retries=0)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    def close(self) -> None:
        self._session.close()

    @staticmethod
    def _timeout_tuple(*, auth: bool = False) -> tuple[float, float]:
        return (_TIMEOUT_CONNECT, _TIMEOUT_READ_AUTH if auth else _TIMEOUT_READ)

    def _post_json_with_cold_start_retry(self, url: str, body: dict[str, Any]) -> requests.Response:
        timeout = self._timeout_tuple(auth=True)
        last: Exception | None = None
        for attempt in range(2):
            try:
                return self._session.post(url, json=body, timeout=timeout)
            except (ReadTimeout, ConnectTimeout) as e:
                last = e
                if attempt == 0:
                    logger.info(
                        "Sunucu yanit vermedi (ilk deneme). Uyku modundan cikis 1-2 dk surebilir; tekrar deneniyor..."
                    )
                    time.sleep(4)
        assert last is not None
        raise last

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def login(
        self,
        *,
        email: str,
        password: str,
        device_id: str,
        device_name: str,
        mac_address: str,
    ) -> tuple[dict[str, Any] | None, str]:
        url = f"{self._base}/auth/login"
        body = {
            "email": email,
            "password": password,
            "device_id": device_id,
            "device_type": "pc",
            "device_name": device_name,
            "mac_address": mac_address,
        }
        try:
            r = self._post_json_with_cold_start_retry(url, body)
            data = r.json() if r.text else {}
            if r.status_code >= 400 or not data.get("ok"):
                return None, str(data.get("message") or r.text or f"HTTP {r.status_code}")
            return data, ""
        except (ReadTimeout, ConnectTimeout) as e:
            logger.warning("login zaman asimi: %s", e)
            return (
                None,
                "Sunucu yanit vermedi (zaman asimi). "
                "Render gibi barindirmada servis uyuyorsa ilk giris 1-2 dakika surebilir; "
                "bir sure sonra tekrar deneyin.",
            )
        except RequestException as e:
            logger.warning("login ag hatasi: %s", e)
            return None, str(e)

    def register(
        self,
        *,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        phone: str,
        device_id: str,
        device_name: str,
        mac_address: str,
    ) -> tuple[dict[str, Any] | None, str]:
        url = f"{self._base}/auth/register"
        body = {
            "email": email,
            "password": password,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone or None,
            "device_id": device_id,
            "device_type": "pc",
            "device_name": device_name,
            "mac_address": mac_address,
        }
        try:
            r = self._post_json_with_cold_start_retry(url, body)
            data = r.json() if r.text else {}
            if r.status_code >= 400 or not data.get("ok"):
                return None, str(data.get("message") or r.text or f"HTTP {r.status_code}")
            return data, ""
        except (ReadTimeout, ConnectTimeout) as e:
            logger.warning("register zaman asimi: %s", e)
            return (
                None,
                "Sunucu yanit vermedi (zaman asimi). "
                "Ilk kayit/giris denemesinde servis uyanana kadar bekleyip tekrar deneyin.",
            )
        except RequestException as e:
            logger.warning("register ag hatasi: %s", e)
            return None, str(e)

    def get_me(self, token: str, device_id: str) -> tuple[dict[str, Any] | None, str]:
        url = f"{self._base}/auth/me"
        params = {"device_id": device_id} if device_id else None
        try:
            r = self._session.get(
                url,
                headers=self._headers(token),
                params=params,
                timeout=self._timeout_tuple(),
            )
            data = r.json() if r.text else {}
            if r.status_code >= 400 or not data.get("ok"):
                return None, str(data.get("message") or r.text or f"HTTP {r.status_code}")
            return data.get("user") or {}, ""
        except (ReadTimeout, ConnectTimeout, RequestException) as e:
            logger.warning("get_me: %s", e)
            return None, str(e)

    def get_phone_device_bundle(
        self, token: str, pc_device_id: str
    ) -> tuple[dict[str, Any] | None, str]:
        """Tek HTTP: devices + recent telefonlar + pairings (masaustu)."""
        url = f"{self._base}/devices/phone-bundle"
        try:
            r = self._session.get(
                url,
                headers=self._headers(token),
                params={"device_id": pc_device_id},
                timeout=self._timeout_tuple(),
            )
            if r.status_code == 404:
                return None, "bundle_missing"
            data = r.json() if r.text else {}
            if r.status_code >= 400 or not data.get("ok"):
                return None, str(data.get("message") or r.text or f"HTTP {r.status_code}")
            return data, ""
        except (ReadTimeout, ConnectTimeout, RequestException) as e:
            logger.warning("get_phone_device_bundle: %s", e)
            return None, str(e)

    def update_profile(
        self,
        token: str,
        *,
        email: str | None = None,
        phone: str | None = None,
        old_password: str | None = None,
        password: str | None = None,
        password2: str | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        url = f"{self._base}/auth/profile"
        body: dict[str, Any] = {}
        if email is not None:
            body["email"] = (email or "").strip().lower()
        if phone is not None:
            body["phone"] = (phone or "").strip()
        if password is not None or password2 is not None:
            body["old_password"] = old_password or ""
            body["password"] = password or ""
            body["password2"] = password2 or ""
        try:
            r = self._session.post(
                url,
                headers=self._headers(token),
                json=body,
                timeout=self._timeout_tuple(),
            )
            data = r.json() if r.text else {}
            if r.status_code >= 400 or not data.get("ok"):
                return None, str(data.get("message") or r.text or f"HTTP {r.status_code}")
            return data, ""
        except (ReadTimeout, ConnectTimeout, RequestException) as e:
            logger.warning("update_profile: %s", e)
            return None, str(e)

    def get_devices(self, token: str) -> tuple[list[dict[str, Any]] | None, str]:
        url = f"{self._base}/devices"
        try:
            r = self._session.get(url, headers=self._headers(token), timeout=self._timeout_tuple())
            data = r.json() if r.text else {}
            if r.status_code >= 400 or not data.get("ok"):
                return None, str(data.get("message") or r.text or f"HTTP {r.status_code}")
            return list(data.get("devices") or []), ""
        except (ReadTimeout, ConnectTimeout, RequestException) as e:
            logger.warning("get_devices: %s", e)
            return None, str(e)

    def get_recent_devices(self, token: str, device_type: str) -> tuple[list[dict[str, Any]] | None, str]:
        url = f"{self._base}/recent-devices"
        try:
            r = self._session.get(
                url,
                headers=self._headers(token),
                params={"device_type": device_type},
                timeout=self._timeout_tuple(),
            )
            data = r.json() if r.text else {}
            if r.status_code >= 400 or not data.get("ok"):
                return None, str(data.get("message") or r.text or f"HTTP {r.status_code}")
            return list(data.get("devices") or []), ""
        except (ReadTimeout, ConnectTimeout, RequestException) as e:
            logger.warning("get_recent_devices: %s", e)
            return None, str(e)

    def get_pairings(self, token: str, device_id: str) -> tuple[list[dict[str, Any]] | None, str]:
        url = f"{self._base}/pairings"
        try:
            r = self._session.get(
                url,
                headers=self._headers(token),
                params={"device_id": device_id},
                timeout=self._timeout_tuple(),
            )
            data = r.json() if r.text else {}
            if r.status_code >= 400 or not data.get("ok"):
                return None, str(data.get("message") or r.text or f"HTTP {r.status_code}")
            return list(data.get("pairings") or []), ""
        except (ReadTimeout, ConnectTimeout, RequestException) as e:
            logger.warning("get_pairings: %s", e)
            return None, str(e)

    def delete_pairing(
        self,
        token: str,
        device_id: str,
        partner_device_id: str,
        partner_address: str | None = None,
    ) -> tuple[bool, str]:
        _ = partner_address
        url = f"{self._base}/pairings/delete"
        body = {"device_id": device_id, "partner_device_id": partner_device_id}
        try:
            r = self._session.post(
                url,
                headers=self._headers(token),
                json=body,
                timeout=self._timeout_tuple(),
            )
            data = r.json() if r.text else {}
            if r.status_code >= 400 or not data.get("ok"):
                return False, str(data.get("message") or r.text or f"HTTP {r.status_code}")
            return True, ""
        except (ReadTimeout, ConnectTimeout, RequestException) as e:
            logger.warning("delete_pairing: %s", e)
            return False, str(e)
