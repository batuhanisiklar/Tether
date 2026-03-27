import requests

from desktop_app.config import ServerDefaults


def _base_http_url() -> str:
    return (
        ServerDefaults.DEFAULT_URL
        .replace("wss://", "https://", 1)
        .replace("ws://", "http://", 1)
        .rstrip("/")
    )


class BackendApi:
    def __init__(self, timeout_sec: float = 10.0):
        self._base_url = _base_http_url()
        self._timeout_sec = timeout_sec

    def login(self, username: str, password: str, device_id: str, device_name: str) -> tuple[dict | None, str]:
        payload = {
            "username": username,
            "password": password,
            "device_id": device_id,
            "device_type": "pc",
            "device_name": device_name,
        }
        try:
            response = requests.post(
                f"{self._base_url}/auth/login",
                json=payload,
                timeout=self._timeout_sec,
            )
            data = response.json() if response.content else {}
        except requests.RequestException:
            return None, "Sunucuya ulasilamadi."
        except ValueError:
            return None, "Sunucudan gecersiz yanit alindi."

        if not response.ok:
            return None, data.get("message") or "Giris basarisiz."
        return data, ""

    def get_devices(self, token: str) -> tuple[list[dict] | None, str]:
        try:
            response = requests.get(
                f"{self._base_url}/devices",
                headers={"Authorization": f"Bearer {token}"},
                timeout=self._timeout_sec,
            )
            data = response.json() if response.content else {}
        except requests.RequestException:
            return None, "Sunucuya ulasilamadi."
        except ValueError:
            return None, "Sunucudan gecersiz yanit alindi."

        if not response.ok:
            return None, data.get("message") or "Cihazlar alinamadi."
        return data.get("devices", []), ""

    def get_pairings(self, token: str, device_id: str) -> tuple[list[dict] | None, str]:
        try:
            response = requests.get(
                f"{self._base_url}/pairings",
                headers={"Authorization": f"Bearer {token}"},
                params={"device_id": device_id},
                timeout=self._timeout_sec,
            )
            data = response.json() if response.content else {}
        except requests.RequestException:
            return None, "Sunucuya ulasilamadi."
        except ValueError:
            return None, "Sunucudan gecersiz yanit alindi."

        if not response.ok:
            return None, data.get("message") or "Cihaz listesi alinamadi."
        return data.get("pairings", []), ""

    def get_recent_devices(self, token: str, device_type: str) -> tuple[list[dict] | None, str]:
        try:
            response = requests.get(
                f"{self._base_url}/recent-devices",
                headers={"Authorization": f"Bearer {token}"},
                params={"device_type": device_type},
                timeout=self._timeout_sec,
            )
            data = response.json() if response.content else {}
        except requests.RequestException:
            return None, "Sunucuya ulasilamadi."
        except ValueError:
            return None, "Sunucudan gecersiz yanit alindi."

        if not response.ok:
            return None, data.get("message") or "Recent cihaz listesi alinamadi."
        return data.get("devices", []), ""

    def get_me(self, token: str, device_id: str | None = None) -> tuple[dict | None, str]:
        try:
            response = requests.get(
                f"{self._base_url}/auth/me",
                headers={"Authorization": f"Bearer {token}"},
                params={"device_id": device_id} if device_id else None,
                timeout=self._timeout_sec,
            )
            data = response.json() if response.content else {}
        except requests.RequestException:
            return None, "Sunucuya ulasilamadi."
        except ValueError:
            return None, "Sunucudan gecersiz yanit alindi."

        if not response.ok:
            return None, data.get("message") or "Kullanici bilgisi alinamadi."
        return data.get("user", {}), ""

    def delete_pairing(
        self,
        token: str,
        device_id: str,
        partner_device_id: str,
        partner_address: str | None = None,
    ) -> tuple[bool, str]:
        try:
            response = requests.post(
                f"{self._base_url}/pairings/delete",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "device_id": device_id,
                    "partner_device_id": partner_device_id,
                    "partner_address": partner_address or "",
                },
                timeout=self._timeout_sec,
            )
            data = response.json() if response.content else {}
        except requests.RequestException:
            return False, "Sunucuya ulasilamadi."
        except ValueError:
            return False, "Sunucudan gecersiz yanit alindi."

        if not response.ok:
            return False, data.get("message") or "Eslesme silinemedi."
        return True, ""
