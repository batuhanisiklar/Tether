from __future__ import annotations

import json
from typing import Any

from aiohttp import web

from signaling_server.auth import parse_token
from signaling_server.config import MessageTypes


async def send_json(ws: web.WebSocketResponse, payload: dict[str, Any]) -> None:
    await ws.send_str(json.dumps(payload, separators=(",", ":")))


def token_from_message(message: dict[str, Any]) -> str:
    return str(message.get("auth_token") or message.get("token") or "").strip()


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


__all__ = ["ensure_ws_user", "send_json", "token_from_message"]
