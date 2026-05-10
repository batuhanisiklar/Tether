"""
Mesaj ve binary frame relay.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from aiohttp import web

from signaling_server.config import MessageTypes
from signaling_server.db_client import ServerDbClient
from signaling_server.helpers import normalize_device_id, send_json, websocket_is_closed
from signaling_server.ws.session import resolve_peer_ws, session_peer_ws_only

logger = logging.getLogger(__name__)

# Throttle: binary relay sirasinda peer bulunamadiginda DB sorgusunu sinirla
_binary_relay_db_cache: dict[str, tuple[float, list[str]]] = {}
_BINARY_RELAY_DB_TTL = 10.0  # saniye (oturum sirasinda cifter degismez)


async def relay_message(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
    raw_text: str | None = None,
) -> None:
    peer_ws = await resolve_peer_ws(app, ws, meta)
    if not peer_ws:
        return
    await peer_ws.send_str(raw_text if raw_text is not None else json.dumps(message, separators=(",", ":")))


async def relay_binary_frame(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    payload: bytes,
) -> None:
    peer_ws = session_peer_ws_only(app, ws, meta)
    if peer_ws is None:
        device_id = normalize_device_id(str(meta.get("device_id") or ""))
        if not device_id:
            for did, entry in list(app["online_devices"].items()):
                if entry.get("ws") is ws:
                    device_id = normalize_device_id(str(did))
                    if device_id:
                        meta["device_id"] = device_id
                    break
        if device_id:
            db: ServerDbClient = app["db"]
            now = time.monotonic()
            cached = _binary_relay_db_cache.get(device_id)
            if cached and (now - cached[0]) < _BINARY_RELAY_DB_TTL:
                partner_ids = cached[1]
            else:
                paired_ctrl = await asyncio.to_thread(db.get_connected_devices_as_controller, device_id)
                paired_tgt = await asyncio.to_thread(db.get_connected_devices_as_target, device_id)
                partner_ids = []
                for raw in list(paired_ctrl) + list(paired_tgt):
                    pid = normalize_device_id(str(raw))
                    if pid and pid != device_id:
                        partner_ids.append(pid)
                _binary_relay_db_cache[device_id] = (now, partner_ids)
            for partner_id in partner_ids:
                entry = app["online_devices"].get(partner_id)
                cand = entry.get("ws") if entry else None
                if cand is not None and cand is not ws and not websocket_is_closed(cand):
                    peer_ws = cand
                    break
    if not peer_ws:
        return
    try:
        await peer_ws.send_bytes(payload)
    except Exception as exc:
        logger.warning("Binary frame relay hatasi: %s", exc)
