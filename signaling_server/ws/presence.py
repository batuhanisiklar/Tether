"""
Cihaz presence, device_ack, device_hello/logout ve device registration.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

from aiohttp import web

from signaling_server.config import MessageTypes
from signaling_server.db_client import ServerDbClient
from signaling_server.helpers import normalize_device_id, send_json
from signaling_server.ws.auth import bind_owned_ws_device, ensure_ws_user

logger = logging.getLogger(__name__)


async def register_or_reuse_device(
    app: web.Application,
    user_id: int,
    device_id: str,
    device_type: str,
    device_name: str,
    mac_address: str | None,
) -> tuple[str | None, str]:
    """
    Bu kullanıcı için cihazı bul veya oluştur.
    """
    effective_mac = (mac_address or "").strip()

    if effective_mac:
        resolved_id = await asyncio.to_thread(
            app["db"].register_device,
            device_name or "",
            device_type,
            user_id,
            effective_mac,
        )
        if resolved_id:
            return resolved_id, ""
        return None, "Cihaz kaydi olusturulamadi."

    from signaling_server.helpers import normalize_device_id as _norm
    normalized_id = _norm(device_id) or "".join(secrets.choice("0123456789") for _ in range(12))
    existing = await asyncio.to_thread(app["db"].get_device_by_id, normalized_id)
    if existing:
        if int(existing.get("user_id")) == int(user_id):
            return normalized_id, ""
    fallback_mac = f"{device_type}:{normalized_id}"
    resolved_id = await asyncio.to_thread(
        app["db"].register_device,
        device_name or "",
        device_type,
        user_id,
        fallback_mac,
    )
    if resolved_id:
        return resolved_id, ""
    return None, "Cihaz kaydi olusturulamadi."


async def send_device_ack(app: web.Application, device_id: str) -> None:
    entry = app["online_devices"].get(device_id)
    if not entry:
        return

    db: ServerDbClient = app["db"]
    ws = entry["ws"]
    paired_as_controller = await asyncio.to_thread(db.get_connected_devices_as_controller, device_id)
    paired_as_target = await asyncio.to_thread(db.get_connected_devices_as_target, device_id)
    paired_ids: list[str] = []
    seen: set[str] = set()
    for candidate in list(paired_as_controller) + list(paired_as_target):
        cid = normalize_device_id(str(candidate)) or str(candidate).strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        paired_ids.append(cid)

    online_paired = [candidate for candidate in paired_ids if candidate in app["online_devices"]]

    phone_accessibility_enabled: bool | None = None
    if str(entry.get("role") or "") == "pc":
        states: list[Any] = []
        for pid in online_paired:
            dev = await asyncio.to_thread(db.get_device_by_id, pid)
            if not dev or str(dev.get("device_type") or "") != "phone":
                continue
            pent = app["online_devices"].get(pid)
            if not pent or not pent.get("ws"):
                continue
            pmeta = app["ws_meta"].get(id(pent["ws"]))
            states.append(pmeta.get("accessibility_enabled") if pmeta else None)
        if states:
            if any(v is False for v in states):
                phone_accessibility_enabled = False
            elif any(v is True for v in states):
                phone_accessibility_enabled = True
            else:
                phone_accessibility_enabled = None

    payload: dict[str, Any] = {
        "type": MessageTypes.DEVICE_ACK,
        "device_id": device_id,
        "paired_with": paired_ids[0] if paired_ids else "",
        "paired_devices": paired_ids,
        "online_paired_devices": online_paired,
        "partner_online": bool(online_paired),
    }
    if str(entry.get("role") or "") == "pc":
        payload["phone_accessibility_enabled"] = phone_accessibility_enabled

    await send_json(ws, payload)


async def refresh_device_ack_for_paired_pcs(app: web.Application, phone_device_id: str) -> None:
    did = normalize_device_id(phone_device_id)
    if not did:
        return
    db: ServerDbClient = app["db"]
    as_ctrl = await asyncio.to_thread(db.get_connected_devices_as_controller, did)
    as_tgt = await asyncio.to_thread(db.get_connected_devices_as_target, did)
    for raw in list(as_ctrl) + list(as_tgt):
        pid = normalize_device_id(str(raw))
        if not pid or pid not in app["online_devices"]:
            continue
        ent = app["online_devices"][pid]
        if str(ent.get("role") or "") != "pc":
            continue
        await send_device_ack(app, pid)


async def broadcast_presence_for_devices(app: web.Application, *device_ids: str) -> None:
    targets = []
    seen: set[str] = set()
    for raw in device_ids:
        did = normalize_device_id(raw) or str(raw or "").strip()
        if did and did not in seen:
            seen.add(did)
            targets.append(did)
    for did in targets:
        try:
            await send_device_ack(app, did)
        except Exception:
            logger.exception("device_ack gonderilemedi: %s", did)


async def handle_device_hello(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
) -> None:
    role = str(message.get("role") or "")
    if role not in {"phone", "pc"}:
        await send_json(ws, {"type": MessageTypes.ERROR, "message": "device_id ve role gerekli"})
        return

    normalized_device_id = await bind_owned_ws_device(app, ws, meta, message, role)
    if not normalized_device_id:
        return

    await send_device_ack(app, normalized_device_id)
    if role == "phone":
        await refresh_device_ack_for_paired_pcs(app, normalized_device_id)


async def handle_device_logout(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
) -> None:
    if not await ensure_ws_user(ws, meta, message):
        return
    device_id = normalize_device_id(str(message.get("device_id") or meta.get("device_id") or ""))
    if not device_id:
        return
    if device_id != normalize_device_id(str(meta.get("device_id") or "")):
        await send_json(ws, {"type": MessageTypes.ERROR, "code": "device_forbidden", "message": "Bu cihaza erisim yetkiniz yok."})
        return
    entry = app["online_devices"].get(device_id)
    if entry and entry.get("ws") is ws:
        app["online_devices"].pop(device_id, None)
    await asyncio.to_thread(app["db"].set_device_online, device_id, False)
    meta["logout_notified"] = True
    await broadcast_presence_for_devices(app, device_id)
