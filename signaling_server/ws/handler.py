"""
Ana WebSocket handler — message dispatch ve cleanup.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import WSMsgType, web

from signaling_server.config import MessageTypes
from signaling_server.helpers import normalize_device_id, send_json, websocket_is_closed
from signaling_server.ws.auth import ensure_ws_user
from signaling_server.ws.presence import (
    broadcast_presence_for_devices,
    handle_device_hello,
    handle_device_logout,
    refresh_device_ack_for_paired_pcs,
    send_device_ack,
)
from signaling_server.ws.relay import relay_binary_frame, relay_message
from signaling_server.ws.session import (
    handle_pair_confirm,
    handle_register_or_join,
    session_peer_ws_only,
)

logger = logging.getLogger(__name__)


async def websocket_handler(request: web.Request) -> web.StreamResponse:
    ws_probe = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024, heartbeat=60)
    if not ws_probe.can_prepare(request).ok:
        return web.Response(text="OK\n")

    ws = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024, heartbeat=60)
    await ws.prepare(request)

    app = request.app
    meta: dict[str, Any] = {
        "user_id": None,
        "device_id": None,
        "role": None,
        "peer_code": None,
        "peer_slot": None,
        "peer_role": None,
        "session_initiator": False,
    }
    app["ws_meta"][id(ws)] = meta

    try:
        async for raw in ws:
            if raw.type == WSMsgType.BINARY:
                if meta.get("user_id") is None:
                    continue
                await relay_binary_frame(app, ws, meta, raw.data)
                continue

            if raw.type != WSMsgType.TEXT:
                continue

            try:
                message = json.loads(raw.data)
            except json.JSONDecodeError:
                await send_json(ws, {"type": MessageTypes.ERROR, "message": "Invalid JSON payload"})
                continue

            message_type = str(message.get("type") or "")
            if message_type not in {MessageTypes.FRAME, MessageTypes.HEARTBEAT}:
                logger.info(
                    "[%s] device_id=%s code=%s role=%s",
                    message_type,
                    message.get("device_id"),
                    message.get("code"),
                    message.get("role"),
                )

            if message_type == MessageTypes.DEVICE_HELLO:
                await handle_device_hello(app, ws, meta, message)
            elif message_type == MessageTypes.DEVICE_LOGOUT:
                await handle_device_logout(app, ws, meta, message)
            elif message_type == MessageTypes.PAIR_CONFIRM:
                await handle_pair_confirm(app, meta, message)
            elif message_type in {MessageTypes.REGISTER, MessageTypes.JOIN}:
                await handle_register_or_join(app, ws, meta, message)
            elif message_type in {MessageTypes.REQUEST_PRESENCE, MessageTypes.HEARTBEAT}:
                if not await ensure_ws_user(ws, meta, message):
                    continue
                if message_type == MessageTypes.REQUEST_PRESENCE and meta.get("role") == "phone":
                    if "accessibility_enabled" in message:
                        meta["accessibility_enabled"] = bool(message.get("accessibility_enabled"))
                    if "media_muted" in message:
                        raw_muted = message.get("media_muted")
                        meta["media_muted"] = None if raw_muted is None else bool(raw_muted)
                device_id = normalize_device_id(str(meta.get("device_id") or ""))
                if device_id:
                    await send_device_ack(app, device_id)
                    if message_type == MessageTypes.REQUEST_PRESENCE and meta.get("role") == "phone":
                        await refresh_device_ack_for_paired_pcs(app, device_id)
                if message_type == MessageTypes.HEARTBEAT and meta.get("peer_code"):
                    peer_ws = session_peer_ws_only(app, ws, meta)
                    if peer_ws and not websocket_is_closed(peer_ws):
                        try:
                            await peer_ws.send_str(raw.data)
                        except ConnectionResetError:
                            logger.debug("Heartbeat relay: peer baglantisi kapanmis")
                        except Exception:
                            pass
            elif message_type in MessageTypes.RELAY_TYPES:
                if meta.get("user_id") is None:
                    await send_json(ws, {"type": MessageTypes.ERROR, "code": "auth_required", "message": "Auth token gerekli."})
                    continue
                await relay_message(app, ws, meta, message, raw_text=raw.data)
            else:
                await send_json(ws, {"type": MessageTypes.ERROR, "message": f"Unknown: {message_type}"})
    finally:
        device_id = normalize_device_id(str(meta.get("device_id") or ""))
        if not meta.get("logout_notified") and device_id:
            online_entry = app["online_devices"].get(device_id)
            if online_entry and online_entry.get("ws") is ws:
                app["online_devices"].pop(device_id, None)
                await asyncio.to_thread(app["db"].set_device_online, device_id, False)

        peer_code = str(meta.get("peer_code") or "")
        peer_slot = str(meta.get("peer_slot") or "")
        if peer_code and peer_slot:
            session = app["sessions"].get(peer_code, {})
            if session.get(peer_slot) is ws:
                session.pop(peer_slot, None)
                app["session_devices"].get(peer_code, {}).pop(peer_slot, None)
                for slot, candidate in session.items():
                    if slot != peer_slot:
                        try:
                            await send_json(candidate, {"type": MessageTypes.PEER_DISCONNECTED, "role": str(meta.get("peer_role") or "")})
                        except Exception:
                            pass
                        break
            if not session:
                app["sessions"].pop(peer_code, None)
                app["session_devices"].pop(peer_code, None)

        app["ws_meta"].pop(id(ws), None)
        if device_id and not meta.get("logout_notified"):
            await broadcast_presence_for_devices(app, device_id)
    return ws
