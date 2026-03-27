import json
import os
import uuid
from typing import Any

from desktop_app.config.constants import Prefs


def read_prefs() -> dict[str, Any]:
    """Tercih dosyasini guvenli sekilde oku."""
    try:
        if os.path.exists(Prefs.PATH):
            with open(Prefs.PATH, "r", encoding="utf-8") as file:
                return json.load(file)
    except Exception:
        pass
    return {}


def write_prefs(data: dict[str, Any]) -> None:
    """Tercih dosyasini guvenli sekilde yaz."""
    try:
        with open(Prefs.PATH, "w", encoding="utf-8") as file:
            json.dump(data, file)
    except Exception:
        pass


def update_prefs(**values: Any) -> dict[str, Any]:
    """Mevcut tercihleri koruyarak verilen alanlari guncelle."""
    prefs = read_prefs()
    prefs.update(values)
    write_prefs(prefs)
    return prefs


def load_paired_phone_id() -> str | None:
    return read_prefs().get(Prefs.KEY_PAIRED_PHONE)


def save_paired_phone_id(phone_device_id: str) -> None:
    update_prefs(**{Prefs.KEY_PAIRED_PHONE: phone_device_id})


def clear_paired_phone_id() -> None:
    prefs = read_prefs()
    if Prefs.KEY_PAIRED_PHONE in prefs:
        prefs.pop(Prefs.KEY_PAIRED_PHONE, None)
        write_prefs(prefs)


def load_paired_phone_address() -> str | None:
    return read_prefs().get(Prefs.KEY_PAIRED_PHONE_ADDRESS)


def save_paired_phone_address(phone_address: str) -> None:
    digits = "".join(ch for ch in phone_address if ch.isdigit())[:12]
    update_prefs(**{Prefs.KEY_PAIRED_PHONE_ADDRESS: digits})


def clear_paired_phone_address() -> None:
    prefs = read_prefs()
    if Prefs.KEY_PAIRED_PHONE_ADDRESS in prefs:
        prefs.pop(Prefs.KEY_PAIRED_PHONE_ADDRESS, None)
        write_prefs(prefs)


def load_or_create_device_id() -> str:
    prefs = read_prefs()
    device_id = prefs.get(Prefs.KEY_DEVICE_ID, "").strip()
    if device_id:
        return device_id
    device_id = f"pc-{uuid.uuid4().hex[:12]}"
    prefs[Prefs.KEY_DEVICE_ID] = device_id
    write_prefs(prefs)
    return device_id


def load_user_address() -> str:
    return read_prefs().get(Prefs.KEY_USER_ADDRESS, "")


def save_user_address(user_address: str) -> None:
    digits = "".join(ch for ch in user_address if ch.isdigit())[:12]
    update_prefs(**{Prefs.KEY_USER_ADDRESS: digits})


def save_session(user_id: int, username: str, user_address: str = "") -> None:
    digits = "".join(ch for ch in user_address if ch.isdigit())[:12]
    update_prefs(
        **{
            Prefs.KEY_LOGGED_IN: True,
            Prefs.KEY_USER_ID: user_id,
            Prefs.KEY_USERNAME: username,
            Prefs.KEY_USER_ADDRESS: digits,
            Prefs.KEY_REMEMBERED_USERNAME: username,
        }
    )


def save_auth_token(token: str) -> None:
    update_prefs(**{Prefs.KEY_AUTH_TOKEN: token})


def load_auth_token() -> str:
    return read_prefs().get(Prefs.KEY_AUTH_TOKEN, "")


def clear_logged_in() -> None:
    prefs = read_prefs()
    prefs[Prefs.KEY_LOGGED_IN] = False
    prefs.pop(Prefs.KEY_AUTH_TOKEN, None)
    prefs.pop(Prefs.KEY_USER_ADDRESS, None)
    prefs.pop(Prefs.KEY_PAIRED_PHONE_ADDRESS, None)
    write_prefs(prefs)


def remembered_username() -> str:
    return read_prefs().get(Prefs.KEY_REMEMBERED_USERNAME, "")


def save_remembered_username(username: str) -> None:
    update_prefs(**{Prefs.KEY_REMEMBERED_USERNAME: username.strip()})
