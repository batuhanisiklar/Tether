from __future__ import annotations

import secrets
from typing import Any


def normalize_device_id(raw_value: str | None) -> str:
    if not raw_value:
        return ""
    return "".join(ch for ch in str(raw_value) if ch.isdigit())[:12]


def random_device_id() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(12))


def owner_fields(
    db: Any | None,
    user_id: int | None,
    cache: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    if db is None or user_id is None:
        return {"owner_name": "", "owner_phone": "", "owner_email": ""}
    uid = int(user_id)
    profile = cache.get(uid)
    if profile is None:
        profile = db.get_user_by_id(uid)
        cache[uid] = profile or {}
    fn = str((profile or {}).get("first_name") or "").strip()
    ln = str((profile or {}).get("last_name") or "").strip()
    full = f"{fn} {ln}".strip()
    return {
        "owner_name": full,
        "owner_phone": str((profile or {}).get("phone") or "").strip(),
        "owner_email": str((profile or {}).get("email") or "").strip(),
    }


def device_payload(
    device: dict[str, Any],
    online_devices: dict[str, dict[str, Any]],
    *,
    db: Any | None = None,
    owner_cache: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    device_id = str(device.get("device_id") or "")
    is_online_db = bool(device.get("is_online", False))
    is_online = device_id in online_devices if device_id else is_online_db
    user_id = int(device.get("user_id")) if device.get("user_id") is not None else None
    cache = owner_cache if owner_cache is not None else {}
    owner = owner_fields(db, user_id, cache)
    return {
        "device_id": device_id,
        "address": device_id,
        "device_type": str(device.get("device_type") or ""),
        "device_name": str(device.get("device_name") or ""),
        "is_online": is_online,
        "mac_address": str(device.get("mac_address") or ""),
        "owner_user_id": user_id,
        **owner,
    }


__all__ = [
    "device_payload",
    "normalize_device_id",
    "owner_fields",
    "random_device_id",
]
