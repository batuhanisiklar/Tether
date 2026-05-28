"""
WebSocket authentication ve device binding.
"""
from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from signaling_server.auth import parse_token
from signaling_server.config import MessageTypes
from signaling_server.helpers import normalize_device_id, send_json, token_from_message


async def require_user(request: web.Request) -> tuple[int, str] | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    payload = parse_token(auth_header[7:])
    if not payload:
        return None
    return int(payload["user_id"]), str(payload["username"])


async def ensure_ws_user(
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
) -> tuple[int, str] | None:
    if meta.get("user_id") is not None:
        return int(meta["user_id"]), str(meta.get("username") or "")

    token = token_from_message(message)
    if not token:
        await send_json(ws, {"type": MessageTypes.ERROR, "code": "auth_required", "message": "Auth token gerekli."})
        return None

    payload = parse_token(token)
    if not payload:
        await send_json(ws, {"type": MessageTypes.ERROR, "code": "auth_invalid", "message": "Gecersiz auth token."})
        return None

    meta["user_id"] = int(payload["user_id"])
    meta["username"] = str(payload["username"])
    return int(payload["user_id"]), str(payload["username"])


async def bind_owned_ws_device(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
    role: str,
) -> str | None:
    user = await ensure_ws_user(ws, meta, message)
    if not user:
        return None
    user_id, _ = user

    normalized_device_id = normalize_device_id(str(message.get("device_id") or meta.get("device_id") or ""))
    if not normalized_device_id:
        await send_json(ws, {"type": MessageTypes.ERROR, "code": "device_id_required", "message": "device_id gerekli."})
        return None

    binding = await asyncio.to_thread(app["db"].get_device_by_id, normalized_device_id)
    if not binding:
        await send_json(ws, {"type": MessageTypes.ERROR, "code": "device_not_found", "message": "Cihaz bulunamadi."})
        return None
    if int(binding.get("user_id")) != int(user_id):
        await send_json(ws, {"type": MessageTypes.ERROR, "code": "device_forbidden", "message": "Bu cihaza erisim yetkiniz yok."})
        return None
    if str(binding.get("device_type") or "") != role:
        await send_json(ws, {"type": MessageTypes.ERROR, "code": "device_role_mismatch", "message": "Cihaz tipi bu oturumla eslesmiyor."})
        return None

    meta["user_id"] = int(user_id)
    meta["device_id"] = normalized_device_id
    meta["role"] = role
    meta["accessibility_enabled"] = bool(message.get("accessibility_enabled", meta.get("accessibility_enabled", True)))
    if "media_muted" in message:
        raw_muted = message.get("media_muted")
        meta["media_muted"] = None if raw_muted is None else bool(raw_muted)
    app["online_devices"][normalized_device_id] = {
        "ws": ws,
        "user_id": int(user_id),
        "role": role,
        "device_id": normalized_device_id,
    }
    await asyncio.to_thread(app["db"].set_device_online, normalized_device_id, True)
    return normalized_device_id
