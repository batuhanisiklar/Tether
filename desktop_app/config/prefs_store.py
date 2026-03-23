import json
import os
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


def save_session(user_id: int, username: str) -> None:
    update_prefs(
        **{
            Prefs.KEY_LOGGED_IN: True,
            Prefs.KEY_USER_ID: user_id,
            Prefs.KEY_USERNAME: username,
            Prefs.KEY_REMEMBERED_USERNAME: username,
        }
    )


def clear_logged_in() -> None:
    update_prefs(**{Prefs.KEY_LOGGED_IN: False})


def remembered_username() -> str:
    return read_prefs().get(Prefs.KEY_REMEMBERED_USERNAME, "")


def save_remembered_username(username: str) -> None:
    update_prefs(**{Prefs.KEY_REMEMBERED_USERNAME: username.strip()})
