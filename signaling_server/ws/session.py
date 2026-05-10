"""
Oturum (session) yönetimi — register/join, pairing, session state.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import web

from signaling_server.config import MessageTypes
from signaling_server.db_client import ServerDbClient
from signaling_server.helpers import normalize_device_id, send_json, websocket_is_closed
from signaling_server.ws.auth import bind_owned_ws_device
from signaling_server.ws.presence import broadcast_presence_for_devices

logger = logging.getLogger(__name__)


async def user_can_access_session_code(
    app: web.Application,
    user_id: int,
    own_device_id: str,
    code: str,
    role: str,
    message_type: str,
) -> bool:
    normalized_code = normalize_device_id(code)
    if len(normalized_code) != 12:
        return False

    if message_type == MessageTypes.REGISTER:
        return role == "phone" and normalized_code == own_device_id

    target = await asyncio.to_thread(app["db"].get_device_by_id, normalized_code)
    if target and int(target.get("user_id")) == int(user_id):
        return True

    if message_type == MessageTypes.JOIN and role == "pc" and target:
        online_entry = app["online_devices"].get(normalized_code)
        target_is_online_phone = (
            str(target.get("device_type") or "") == "phone"
            and online_entry is not None
            and str(online_entry.get("role") or "") == "phone"
        )
        if target_is_online_phone:
            return True

    paired_as_controller = await asyncio.to_thread(app["db"].get_connected_devices_as_controller, own_device_id)
    paired_as_target = await asyncio.to_thread(app["db"].get_connected_devices_as_target, own_device_id)
    return normalized_code in {
        normalize_device_id(str(candidate))
        for candidate in list(paired_as_controller) + list(paired_as_target)
    }


def session_entry(app: web.Application, code: str) -> dict[str, web.WebSocketResponse]:
    if code not in app["sessions"]:
        app["sessions"][code] = {}
        app["session_devices"][code] = {}
    return app["sessions"][code]


def prune_closed_peers_from_session(app: web.Application, code: str) -> None:
    """
    Oturumda kalmis olü WebSocket referanslarini temizle.
    Aksi halde len(session)>=2 'Oturum dolu' hatasi verir; gercekte partner yoktur.
    """
    session = app["sessions"].get(code)
    if not session:
        return
    devices = app["session_devices"].get(code, {})
    dead_slots = [slot for slot, peer in list(session.items()) if websocket_is_closed(peer)]
    for slot in dead_slots:
        session.pop(slot, None)
        devices.pop(slot, None)
        logger.warning("Oturumdan olü soket cikarildi: code=%s slot=%s", code, slot)
    if not session:
        app["sessions"].pop(code, None)
        app["session_devices"].pop(code, None)


async def evict_stale_session_slots_for_device(
    app: web.Application,
    code: str,
    device_id: str,
    current_ws: web.WebSocketResponse,
) -> None:
    """
    Ayni device_id ile yeni WebSocket geldiginde oturumdaki eski soketi cikar.
    """
    norm = normalize_device_id(device_id)
    if not norm:
        return
    session = app["sessions"].get(code)
    if not session:
        return
    devices = app["session_devices"].get(code, {})
    for slot in list(session.keys()):
        slot_did = normalize_device_id(str(devices.get(slot) or ""))
        if slot_did != norm:
            continue
        old_ws = session.get(slot)
        if old_ws is None or old_ws is current_ws:
            continue
        session.pop(slot, None)
        devices.pop(slot, None)
        logger.info(
            "Oturum kodu=%s: ayni cihaz icin eski slot temizlendi (device_id=%s)",
            code,
            norm,
        )
        try:
            await old_ws.close(code=4000)
        except Exception:
            pass
    if not session:
        app["sessions"].pop(code, None)
        app["session_devices"].pop(code, None)


def session_peer_ws_only(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
) -> web.WebSocketResponse | None:
    """Oturum (peer_code/slot) uzerinden es; hata mesaji gondermez — binary relay icin."""
    peer_code = str(meta.get("peer_code") or "")
    peer_slot = str(meta.get("peer_slot") or "")
    if not peer_code or not peer_slot:
        return None
    prune_closed_peers_from_session(app, peer_code)
    session = app["sessions"].get(peer_code, {})
    for slot, candidate in session.items():
        if slot != peer_slot:
            return candidate
    return None


async def resolve_peer_ws(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
) -> web.WebSocketResponse | None:
    peer = session_peer_ws_only(app, ws, meta)
    if peer is not None:
        return peer
    peer_code = str(meta.get("peer_code") or "")
    peer_slot = str(meta.get("peer_slot") or "")
    if not peer_code or not peer_slot:
        await send_json(ws, {"type": MessageTypes.ERROR, "message": "Not paired"})
        return None
    await send_json(ws, {"type": MessageTypes.ERROR, "message": "Partner bagli degil"})
    return None


async def save_connection_pair(app: web.Application, controller_device_id: str, target_device_id: str) -> None:
    """
    PC (controller) → Telefon (target) bağlantısını kaydet.
    DB'de ON CONFLICT DO NOTHING ile duplicate otomatik engellenir.
    """
    controller_id = normalize_device_id(controller_device_id) or controller_device_id
    target_id = normalize_device_id(target_device_id) or target_device_id
    if not controller_id or not target_id or controller_id == target_id:
        return
    await asyncio.to_thread(app["db"].create_connection, controller_id, target_id)


async def notify_paired(app: web.Application, code: str) -> None:
    session = app["sessions"].get(code, {})
    session_devices = app["session_devices"].get(code, {})
    if len(session) < 2:
        return

    slots = list(session.keys())[:2]
    left_slot, right_slot = slots[0], slots[1]
    left_ws = session[left_slot]
    right_ws = session[right_slot]
    left_meta = app["ws_meta"].get(id(left_ws)) or {}
    right_meta = app["ws_meta"].get(id(right_ws)) or {}

    _phone_a11y = next(
        (m.get("accessibility_enabled") for m in (left_meta, right_meta) if str(m.get("role") or "") == "phone"),
        None,
    )
    logger.info("paired code=%s slots=%s phone_accessibility_enabled=%s", code, list(session.keys()), _phone_a11y)

    controller_slot = left_slot
    for slot_name, slot_ws in session.items():
        if (app["ws_meta"].get(id(slot_ws)) or {}).get("session_initiator"):
            controller_slot = slot_name
            break
    target_slot = right_slot if controller_slot == left_slot else left_slot
    controller_device_id = str(session_devices.get(controller_slot) or "")
    target_device_id = str(session_devices.get(target_slot) or "")
    await save_connection_pair(app, controller_device_id, target_device_id)

    for slot_name, slot_ws in session.items():
        partner_slot = right_slot if slot_name == left_slot else left_slot
        control_mode = "controller" if slot_name == controller_slot else "target"
        await send_json(
            slot_ws,
            {
                "type": MessageTypes.PAIRED,
                "code": code,
                "your_role": str((app["ws_meta"].get(id(slot_ws)) or {}).get("role") or ""),
                "partner_device_id": str(session_devices.get(partner_slot) or ""),
                "control_mode": control_mode,
            },
        )

    await broadcast_presence_for_devices(app, controller_device_id, target_device_id)


async def handle_register_or_join(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
) -> None:
    code = str(message.get("code") or "").strip()
    role = str(message.get("role") or ("phone" if message.get("type") == MessageTypes.REGISTER else "pc"))
    if not code:
        await send_json(ws, {"type": MessageTypes.ERROR, "message": "code missing"})
        return
    if role not in {"phone", "pc"}:
        await send_json(ws, {"type": MessageTypes.ERROR, "message": "role gecersiz"})
        return

    normalized_device_id = await bind_owned_ws_device(app, ws, meta, message, role)
    if not normalized_device_id:
        return

    user_id = int(meta["user_id"])
    if not await user_can_access_session_code(app, user_id, normalized_device_id, code, role, str(message.get("type") or "")):
        await send_json(ws, {"type": MessageTypes.ERROR, "code": "session_forbidden", "message": "Bu oturuma erisim yetkiniz yok."})
        return

    prune_closed_peers_from_session(app, code)
    await evict_stale_session_slots_for_device(app, code, normalized_device_id, ws)
    session = session_entry(app, code)

    if len(session) >= 2 and ws not in session.values():
        await send_json(ws, {"type": MessageTypes.ERROR, "message": "Oturum dolu."})
        return

    slot = role
    if slot in session and session.get(slot) is not ws:
        existing = session.get(slot)
        if existing is not None and websocket_is_closed(existing):
            session.pop(slot, None)
            app["session_devices"][code].pop(slot, None)
        else:
            slot = f"{role}_2"
    session[slot] = ws
    app["session_devices"][code][slot] = normalized_device_id
    meta["peer_code"] = code
    meta["peer_slot"] = slot
    meta["peer_role"] = role
    meta["session_initiator"] = bool(message.get("type") == MessageTypes.JOIN)
    if "accessibility_enabled" in message:
        meta["accessibility_enabled"] = bool(message.get("accessibility_enabled"))

    ack_type = MessageTypes.REGISTERED if message.get("type") == MessageTypes.REGISTER else MessageTypes.JOINED
    await send_json(ws, {"type": ack_type, "code": code, "role": role})

    if len(session) >= 2:
        await notify_paired(app, code)
    elif message.get("type") == MessageTypes.JOIN:
        await send_json(ws, {"type": MessageTypes.WAITING, "message": "Partner baglanmayi bekliyor..."})

    if role == "phone":
        pid = normalize_device_id(str(meta.get("device_id") or ""))
        if pid:
            from signaling_server.ws.presence import refresh_device_ack_for_paired_pcs
            await refresh_device_ack_for_paired_pcs(app, pid)


async def handle_pair_confirm(app: web.Application, meta: dict[str, Any], message: dict[str, Any]) -> None:
    """
    Telefon, pair_confirm gonderdiginde cagirilir.
    """
    if meta.get("user_id") is None:
        return
    first_device_id = normalize_device_id(str(message.get("my_device_id") or ""))
    second_device_id = normalize_device_id(str(message.get("paired_with") or ""))
    if not first_device_id or not second_device_id:
        return
    if first_device_id != normalize_device_id(str(meta.get("device_id") or "")):
        return
    await broadcast_presence_for_devices(app, first_device_id, second_device_id)
