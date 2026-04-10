import asyncio
import json
import logging
import os
import secrets
import sys
from typing import Any

from aiohttp import WSMsgType, web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signaling_server.auth import issue_token, parse_token
from signaling_server.config import MessageTypes, ServerConfig
from signaling_server.db_client import ServerDbClient

logging.basicConfig(level=logging.INFO, format=ServerConfig.LOG_FORMAT)
logger = logging.getLogger(__name__)


def _normalize_device_id(raw_value: str | None) -> str:
    if not raw_value:
        return ""
    return "".join(ch for ch in str(raw_value) if ch.isdigit())[:12]


def _random_device_id() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(12))


def _device_payload(device: dict[str, Any], online_devices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    device_id = str(device.get("device_id") or "")
    is_online_db = bool(device.get("is_online", False))
    is_online = device_id in online_devices if device_id else is_online_db
    return {
        "device_id": device_id,
        "address": device_id,
        "device_type": str(device.get("device_type") or ""),
        "device_name": str(device.get("device_name") or ""),
        "is_online": is_online,
        "mac_address": str(device.get("mac_address") or ""),
        "owner_user_id": int(device.get("user_id")) if device.get("user_id") is not None else None,
    }


async def _json(request: web.Request) -> dict[str, Any]:
    try:
        return await request.json()
    except Exception:
        return {}


def _username_from_email(email: str) -> str:
    local = (email or "").strip().split("@", 1)[0].strip()
    return local or "user"


async def _require_user(request: web.Request) -> tuple[int, str] | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    payload = parse_token(auth_header[7:])
    if not payload:
        return None
    return int(payload["user_id"]), str(payload["username"])


async def _send_json(ws: web.WebSocketResponse, payload: dict[str, Any]) -> None:
    await ws.send_str(json.dumps(payload, separators=(",", ":")))


def _session_entry(app: web.Application, code: str) -> dict[str, web.WebSocketResponse]:
    if code not in app["sessions"]:
        app["sessions"][code] = {}
        app["session_devices"][code] = {}
    return app["sessions"][code]


def _websocket_is_closed(ws: web.WebSocketResponse) -> bool:
    """Kapanmis veya kapanmakta olan baglantilari oturum sayimindan cikar."""
    try:
        return bool(ws.closed)
    except Exception:
        return True


def _prune_closed_peers_from_session(app: web.Application, code: str) -> None:
    """
    Oturumda kalmis olü WebSocket referanslarini temizle.
    Aksi halde len(session)>=2 'Oturum dolu' hatasi verir; gercekte partner yoktur.
    """
    session = app["sessions"].get(code)
    if not session:
        return
    devices = app["session_devices"].get(code, {})
    dead_slots = [slot for slot, peer in list(session.items()) if _websocket_is_closed(peer)]
    for slot in dead_slots:
        session.pop(slot, None)
        devices.pop(slot, None)
        logger.warning("Oturumdan olü soket cikarildi: code=%s slot=%s", code, slot)
    if not session:
        app["sessions"].pop(code, None)
        app["session_devices"].pop(code, None)


async def _send_device_ack(app: web.Application, device_id: str) -> None:
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
        cid = _normalize_device_id(str(candidate)) or str(candidate).strip()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        paired_ids.append(cid)

    online_paired = [candidate for candidate in paired_ids if candidate in app["online_devices"]]
    await _send_json(
        ws,
        {
            "type": MessageTypes.DEVICE_ACK,
            "device_id": device_id,
            "paired_with": paired_ids[0] if paired_ids else "",
            "paired_devices": paired_ids,
            "online_paired_devices": online_paired,
            "partner_online": bool(online_paired),
        },
    )


async def _broadcast_presence_for_devices(app: web.Application, *device_ids: str) -> None:
    targets = []
    seen: set[str] = set()
    for raw in device_ids:
        did = _normalize_device_id(raw) or str(raw or "").strip()
        if did and did not in seen:
            seen.add(did)
            targets.append(did)
    for did in targets:
        try:
            await _send_device_ack(app, did)
        except Exception:
            logger.exception("device_ack gonderilemedi: %s", did)


async def _save_connection_pair(app: web.Application, controller_device_id: str, target_device_id: str) -> None:
    controller_id = _normalize_device_id(controller_device_id) or controller_device_id
    target_id = _normalize_device_id(target_device_id) or target_device_id
    if not controller_id or not target_id or controller_id == target_id:
        return
    exists = await asyncio.to_thread(app["db"].connection_exists, controller_id, target_id)
    if not exists:
        await asyncio.to_thread(app["db"].create_connection, controller_id, target_id)


def _session_peer_ws_only(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
) -> web.WebSocketResponse | None:
    """Oturum (peer_code/slot) uzerinden es; hata mesaji gondermez — binary relay icin."""
    peer_code = str(meta.get("peer_code") or "")
    peer_slot = str(meta.get("peer_slot") or "")
    if not peer_code or not peer_slot:
        return None
    _prune_closed_peers_from_session(app, peer_code)
    session = app["sessions"].get(peer_code, {})
    for slot, candidate in session.items():
        if slot != peer_slot:
            return candidate
    return None


async def _resolve_peer_ws(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
) -> web.WebSocketResponse | None:
    peer = _session_peer_ws_only(app, ws, meta)
    if peer is not None:
        return peer
    peer_code = str(meta.get("peer_code") or "")
    peer_slot = str(meta.get("peer_slot") or "")
    if not peer_code or not peer_slot:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Not paired"})
        return None
    await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Partner bagli degil"})
    return None


async def _relay_message(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
    raw_text: str | None = None,
) -> None:
    peer_ws = await _resolve_peer_ws(app, ws, meta)
    if not peer_ws:
        return
    await peer_ws.send_str(raw_text if raw_text is not None else json.dumps(message, separators=(",", ":")))


async def _relay_binary_frame(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    payload: bytes,
) -> None:
    peer_ws = _session_peer_ws_only(app, ws, meta)
    if peer_ws is None:
        device_id = _normalize_device_id(str(meta.get("device_id") or ""))
        if not device_id:
            for did, entry in list(app["online_devices"].items()):
                if entry.get("ws") is ws:
                    device_id = _normalize_device_id(str(did))
                    if device_id:
                        meta["device_id"] = device_id
                    break
        if device_id:
            db: ServerDbClient = app["db"]
            paired_ctrl = await asyncio.to_thread(db.get_connected_devices_as_controller, device_id)
            paired_tgt = await asyncio.to_thread(db.get_connected_devices_as_target, device_id)
            for partner_id_raw in list(paired_ctrl) + list(paired_tgt):
                partner_id = _normalize_device_id(str(partner_id_raw))
                if not partner_id or partner_id == device_id:
                    continue
                entry = app["online_devices"].get(partner_id)
                cand = entry.get("ws") if entry else None
                if cand is not None and cand is not ws and not _websocket_is_closed(cand):
                    peer_ws = cand
                    break
    if not peer_ws:
        logger.debug(
            "Binary frame relay yok: peer bulunamadi (device_id=%s peer_code=%s)",
            meta.get("device_id"),
            meta.get("peer_code"),
        )
        return
    try:
        await peer_ws.send_bytes(payload)
    except Exception as exc:
        logger.warning("Binary frame relay hatasi: %s", exc)


async def _register_or_reuse_device(
    app: web.Application,
    user_id: int,
    device_id: str,
    device_type: str,
    device_name: str,
    mac_address: str | None,
) -> tuple[str | None, str]:
    normalized_id = _normalize_device_id(device_id) or _random_device_id()
    existing = await asyncio.to_thread(app["db"].get_device_by_id, normalized_id)
    if existing:
        if int(existing.get("user_id")) != int(user_id):
            return None, "Bu device_id baska bir hesaba ait."
        return normalized_id, ""

    effective_mac = (mac_address or "").strip() or f"{device_type}:{normalized_id}"
    created = await asyncio.to_thread(
        app["db"].register_device,
        normalized_id,
        device_name or "",
        device_type,
        user_id,
        effective_mac,
    )
    if not created:
        return None, "Cihaz kaydi olusturulamadi."
    return normalized_id, ""


async def _handle_device_hello(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
) -> None:
    raw_device_id = str(message.get("device_id") or "").strip()
    role = str(message.get("role") or "")
    if not raw_device_id or role not in {"phone", "pc"}:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "device_id ve role gerekli"})
        return

    normalized_device_id = _normalize_device_id(raw_device_id)
    binding = await asyncio.to_thread(app["db"].get_device_by_id, normalized_device_id)
    if not binding:
        logger.warning(
            "device_hello: DB kaydi yok, meta yine dolduruluyor (register/join devam edebilsin): %s role=%s",
            normalized_device_id,
            role,
        )
        meta["device_id"] = normalized_device_id
        meta["role"] = role
        meta["user_id"] = None
        meta["accessibility_enabled"] = bool(message.get("accessibility_enabled", True))
        app["online_devices"][normalized_device_id] = {
            "ws": ws,
            "user_id": None,
            "role": role,
            "device_id": normalized_device_id,
        }
        await _send_device_ack(app, normalized_device_id)
        return
    if str(binding.get("device_type") or "") != role:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Cihaz tipi bu oturumla eslesmiyor"})
        return

    user_id = int(binding["user_id"])
    meta["user_id"] = user_id
    meta["device_id"] = normalized_device_id
    meta["role"] = role
    meta["accessibility_enabled"] = bool(message.get("accessibility_enabled", True))
    app["online_devices"][normalized_device_id] = {
        "ws": ws,
        "user_id": user_id,
        "role": role,
        "device_id": normalized_device_id,
    }
    await asyncio.to_thread(app["db"].set_device_online, normalized_device_id, True)

    await _send_device_ack(app, normalized_device_id)


async def _handle_register_or_join(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
) -> None:
    code = str(message.get("code") or "").strip()
    role = str(message.get("role") or ("phone" if message.get("type") == MessageTypes.REGISTER else "pc"))
    if not code:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "code missing"})
        return
    if role not in {"phone", "pc"}:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "role gecersiz"})
        return

    if meta.get("user_id") is None:
        raw_device_id = str(message.get("device_id") or "").strip()
        normalized_device_id = _normalize_device_id(raw_device_id)
        if not normalized_device_id:
            await _send_json(ws, {"type": MessageTypes.ERROR, "message": "device_id missing"})
            return
        binding = await asyncio.to_thread(app["db"].get_device_by_id, normalized_device_id)
        if binding:
            meta["user_id"] = int(binding["user_id"])
            meta["device_id"] = normalized_device_id
            meta["role"] = role
            meta["accessibility_enabled"] = bool(message.get("accessibility_enabled", True))
            app["online_devices"][normalized_device_id] = {
                "ws": ws,
                "user_id": int(binding["user_id"]),
                "role": role,
                "device_id": normalized_device_id,
            }
            await asyncio.to_thread(app["db"].set_device_online, normalized_device_id, True)
        elif meta.get("device_id") == normalized_device_id and meta.get("role") == role:
            logger.warning(
                "register/join: DB kaydi yok, device_hello meta ile oturum: %s role=%s",
                normalized_device_id,
                role,
            )
            meta["device_id"] = normalized_device_id
            meta["role"] = role
            meta["accessibility_enabled"] = bool(message.get("accessibility_enabled", True))
            app["online_devices"][normalized_device_id] = {
                "ws": ws,
                "user_id": None,
                "role": role,
                "device_id": normalized_device_id,
            }
        else:
            await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Cihaz bulunamadi"})
            return

    session = _session_entry(app, code)
    _prune_closed_peers_from_session(app, code)
    session = _session_entry(app, code)

    if len(session) >= 2 and ws not in session.values():
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Oturum dolu."})
        return

    slot = role
    if slot in session and session.get(slot) is not ws:
        existing = session.get(slot)
        if existing is not None and _websocket_is_closed(existing):
            session.pop(slot, None)
            app["session_devices"][code].pop(slot, None)
        else:
            slot = f"{role}_2"
    session[slot] = ws
    normalized_device_id = _normalize_device_id(str(meta.get("device_id") or message.get("device_id") or ""))
    app["session_devices"][code][slot] = normalized_device_id
    meta["peer_code"] = code
    meta["peer_slot"] = slot
    meta["peer_role"] = role
    meta["session_initiator"] = bool(message.get("type") == MessageTypes.JOIN)
    if "accessibility_enabled" in message:
        meta["accessibility_enabled"] = bool(message.get("accessibility_enabled"))

    ack_type = MessageTypes.REGISTERED if message.get("type") == MessageTypes.REGISTER else MessageTypes.JOINED
    await _send_json(ws, {"type": ack_type, "code": code, "role": role})

    if len(session) >= 2:
        await _notify_paired(app, code)
    elif message.get("type") == MessageTypes.JOIN:
        await _send_json(ws, {"type": MessageTypes.WAITING, "message": "Partner baglanmayi bekliyor..."})


async def _notify_paired(app: web.Application, code: str) -> None:
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

    # Erisilebilirlik kontrolu sunucuda eslestirmeyi BLOK ETMEZ; telefon istemcisi zaten komutlari
    # servis kapaliyken reddeder. Sunucu tarafinda bloklamak joined+error yaratarak PC/telefon
    # oturumunu kirabiliyordu.

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
    await _save_connection_pair(app, controller_device_id, target_device_id)

    for slot_name, slot_ws in session.items():
        partner_slot = right_slot if slot_name == left_slot else left_slot
        control_mode = "controller" if slot_name == controller_slot else "target"
        await _send_json(
            slot_ws,
            {
                "type": MessageTypes.PAIRED,
                "code": code,
                "your_role": str((app["ws_meta"].get(id(slot_ws)) or {}).get("role") or ""),
                "partner_device_id": str(session_devices.get(partner_slot) or ""),
                "control_mode": control_mode,
            },
        )

    await _broadcast_presence_for_devices(app, controller_device_id, target_device_id)


async def _handle_pair_confirm(app: web.Application, meta: dict[str, Any], message: dict[str, Any]) -> None:
    first_device_id = _normalize_device_id(str(message.get("my_device_id") or ""))
    second_device_id = _normalize_device_id(str(message.get("paired_with") or ""))
    if not first_device_id or not second_device_id:
        return
    await _save_connection_pair(app, first_device_id, second_device_id)
    await _broadcast_presence_for_devices(app, first_device_id, second_device_id)


async def _handle_device_logout(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict[str, Any],
    message: dict[str, Any],
) -> None:
    device_id = _normalize_device_id(str(message.get("device_id") or meta.get("device_id") or ""))
    if not device_id:
        return
    entry = app["online_devices"].get(device_id)
    if entry and entry.get("ws") is ws:
        app["online_devices"].pop(device_id, None)
    await asyncio.to_thread(app["db"].set_device_online, device_id, False)
    meta["logout_notified"] = True
    await _broadcast_presence_for_devices(app, device_id)


async def websocket_handler(request: web.Request) -> web.StreamResponse:
    ws_probe = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024, heartbeat=20)
    if not ws_probe.can_prepare(request).ok:
        return web.Response(text="OK\n")

    ws = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024, heartbeat=20)
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
                await _relay_binary_frame(app, ws, meta, raw.data)
                continue

            if raw.type != WSMsgType.TEXT:
                continue

            try:
                message = json.loads(raw.data)
            except json.JSONDecodeError:
                await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Invalid JSON payload"})
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
                await _handle_device_hello(app, ws, meta, message)
            elif message_type == MessageTypes.DEVICE_LOGOUT:
                await _handle_device_logout(app, ws, meta, message)
            elif message_type == MessageTypes.PAIR_CONFIRM:
                await _handle_pair_confirm(app, meta, message)
            elif message_type in {MessageTypes.REGISTER, MessageTypes.JOIN}:
                await _handle_register_or_join(app, ws, meta, message)
            elif message_type in {MessageTypes.REQUEST_PRESENCE, MessageTypes.HEARTBEAT}:
                if message_type == MessageTypes.REQUEST_PRESENCE and meta.get("role") == "phone":
                    if "accessibility_enabled" in message:
                        meta["accessibility_enabled"] = bool(message.get("accessibility_enabled"))
                device_id = _normalize_device_id(str(meta.get("device_id") or ""))
                if device_id:
                    await _send_device_ack(app, device_id)
                if message_type == MessageTypes.HEARTBEAT and meta.get("peer_code"):
                    peer_ws = _session_peer_ws_only(app, ws, meta)
                    if peer_ws:
                        try:
                            await peer_ws.send_str(raw.data)
                        except Exception:
                            pass
            elif message_type in MessageTypes.RELAY_TYPES:
                await _relay_message(app, ws, meta, message, raw_text=raw.data)
            else:
                await _send_json(ws, {"type": MessageTypes.ERROR, "message": f"Unknown: {message_type}"})
    finally:
        device_id = _normalize_device_id(str(meta.get("device_id") or ""))
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
                            await _send_json(candidate, {"type": MessageTypes.PEER_DISCONNECTED, "role": str(meta.get("peer_role") or "")})
                        except Exception:
                            pass
                        break
            if not session:
                app["sessions"].pop(peer_code, None)
                app["session_devices"].pop(peer_code, None)

        app["ws_meta"].pop(id(ws), None)
        if device_id and not meta.get("logout_notified"):
            await _broadcast_presence_for_devices(app, device_id)
    return ws


async def auth_register(request: web.Request) -> web.Response:
    data = await _json(request)
    email = str(data.get("email") or data.get("username") or "").strip().lower()
    password = str(data.get("password") or "")
    first_name = str(data.get("first_name") or "").strip()
    last_name = str(data.get("last_name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    if not email or not password:
        return web.json_response({"ok": False, "message": "email ve password gerekli."}, status=400)

    user_id = await asyncio.to_thread(
        request.app["db"].register_user,
        email,
        password,
        first_name,
        last_name,
        phone or None,
    )
    if user_id is None:
        return web.json_response({"ok": False, "message": "Bu e-posta zaten kayitli."}, status=400)

    device_id = str(data.get("device_id") or "")
    device_type = str(data.get("device_type") or "")
    device_name = str(data.get("device_name") or "")
    mac_address = str(data.get("mac_address") or data.get("macAddress") or "")
    resolved_device_id = ""
    if device_type in {"phone", "pc"}:
        resolved_device_id, device_err = await _register_or_reuse_device(
            request.app,
            int(user_id),
            device_id,
            device_type,
            device_name,
            mac_address,
        )
        if not resolved_device_id:
            return web.json_response({"ok": False, "message": device_err or "Cihaz kaydi yapilamadi."}, status=400)

    username = _username_from_email(email)
    token = issue_token(int(user_id), username)
    return web.json_response(
        {
            "ok": True,
            "token": token,
            "user": {
                "id": int(user_id),
                "username": username,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone or "",
                "device_id": resolved_device_id,
                "address": resolved_device_id,
            },
        }
    )


async def auth_login(request: web.Request) -> web.Response:
    data = await _json(request)
    email = str(data.get("email") or data.get("username") or "").strip().lower()
    password = str(data.get("password") or "")
    user_id = await asyncio.to_thread(request.app["db"].authenticate_user, email, password)
    if user_id is None:
        return web.json_response({"ok": False, "message": "Kullanici adi veya sifre hatali."}, status=401)

    device_id = str(data.get("device_id") or "")
    device_type = str(data.get("device_type") or "")
    device_name = str(data.get("device_name") or "")
    mac_address = str(data.get("mac_address") or data.get("macAddress") or "")
    resolved_device_id = ""
    if device_type in {"phone", "pc"}:
        resolved_device_id, device_err = await _register_or_reuse_device(
            request.app,
            int(user_id),
            device_id,
            device_type,
            device_name,
            mac_address,
        )
        if not resolved_device_id:
            return web.json_response({"ok": False, "message": device_err or "Cihaz kaydi yapilamadi."}, status=400)

    username = _username_from_email(email)
    token = issue_token(int(user_id), username)
    profile = await asyncio.to_thread(request.app["db"].get_user_by_id, int(user_id))
    return web.json_response(
        {
            "ok": True,
            "token": token,
            "user": {
                "id": int(user_id),
                "username": username,
                "email": email,
                "first_name": str((profile or {}).get("first_name") or ""),
                "last_name": str((profile or {}).get("last_name") or ""),
                "phone": str((profile or {}).get("phone") or ""),
                "device_id": resolved_device_id,
                "address": resolved_device_id,
            },
        }
    )


async def auth_me(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, username = user
    profile = await asyncio.to_thread(request.app["db"].get_user_by_id, int(user_id))
    if not profile:
        return web.json_response({"ok": False, "message": "Kullanici bulunamadi."}, status=404)

    device_id = _normalize_device_id(str(request.query.get("device_id") or ""))
    if device_id:
        device = await asyncio.to_thread(request.app["db"].get_device_by_id, device_id)
        address = device_id if device and int(device.get("user_id")) == int(user_id) else ""
    else:
        address = ""
    return web.json_response(
        {
            "ok": True,
            "user": {
                "id": int(profile["user_id"]),
                "username": username,
                "email": str(profile.get("email") or ""),
                "first_name": str(profile.get("first_name") or ""),
                "last_name": str(profile.get("last_name") or ""),
                "phone": str(profile.get("phone") or ""),
                "address": address,
            },
        }
    )


async def auth_profile_update(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _old_username = user

    data = await _json(request)
    email = data.get("email")
    phone = data.get("phone")
    old_pwd = data.get("old_password")
    pwd1 = data.get("password")
    pwd2 = data.get("password2")

    # email varsa basit doğrulama
    if email is not None:
        em = str(email).strip().lower()
        if not em or "@" not in em or len(em) < 5:
            return web.json_response({"ok": False, "message": "Gecerli bir e-posta girin."}, status=400)
        email = em

    new_password: str | None = None
    if pwd1 is not None or pwd2 is not None:
        p1 = str(pwd1 or "")
        p2 = str(pwd2 or "")
        op = str(old_pwd or "")
        if not op:
            return web.json_response({"ok": False, "message": "Mevcut sifre gerekli."}, status=400)
        if not p1 or not p2:
            return web.json_response({"ok": False, "message": "Sifre iki kere girilmelidir."}, status=400)
        if p1 != p2:
            return web.json_response({"ok": False, "message": "Sifreler eslesmiyor."}, status=400)
        if len(p1) < 6:
            return web.json_response({"ok": False, "message": "Sifre en az 6 karakter olmali."}, status=400)
        new_password = p1

    ok, err = await asyncio.to_thread(
        request.app["db"].update_user_profile,
        int(user_id),
        email=email if email is not None else None,
        phone=str(phone).strip() if phone is not None else None,
        new_password=new_password,
        old_password=str(old_pwd or "").strip() if (pwd1 is not None or pwd2 is not None) else None,
    )
    if not ok:
        return web.json_response({"ok": False, "message": err or "Profil guncellenemedi."}, status=400)

    profile = await asyncio.to_thread(request.app["db"].get_user_by_id, int(user_id))
    if not profile:
        return web.json_response({"ok": False, "message": "Kullanici bulunamadi."}, status=404)

    new_email = str(profile.get("email") or "").strip().lower()
    new_username = _username_from_email(new_email)
    token = issue_token(int(user_id), new_username)
    return web.json_response(
        {
            "ok": True,
            "token": token,
            "user": {
                "id": int(profile["user_id"]),
                "username": new_username,
                "email": new_email,
                "first_name": str(profile.get("first_name") or ""),
                "last_name": str(profile.get("last_name") or ""),
                "phone": str(profile.get("phone") or ""),
            },
        }
    )


async def upsert_device(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user

    data = await _json(request)
    device_id = str(data.get("device_id") or "")
    device_type = str(data.get("device_type") or "")
    device_name = str(data.get("device_name") or "")
    mac_address = str(data.get("mac_address") or data.get("macAddress") or "")
    if device_type not in {"phone", "pc"}:
        return web.json_response({"ok": False, "message": "device_type gecersiz."}, status=400)

    resolved_device_id, err = await _register_or_reuse_device(
        request.app,
        int(user_id),
        device_id,
        device_type,
        device_name,
        mac_address,
    )
    if not resolved_device_id:
        return web.json_response({"ok": False, "message": err or "Cihaz kaydi yapilamadi."}, status=400)
    return web.json_response({"ok": True, "device_id": resolved_device_id, "address": resolved_device_id})


async def list_devices(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user
    devices = await asyncio.to_thread(request.app["db"].get_devices_for_user, int(user_id))
    payload = [_device_payload(device, request.app["online_devices"]) for device in devices]
    return web.json_response({"ok": True, "devices": payload})


async def list_pairings(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user
    device_id = _normalize_device_id(request.query.get("device_id"))
    if not device_id:
        return web.json_response({"ok": False, "message": "device_id gerekli."}, status=400)

    device = await asyncio.to_thread(request.app["db"].get_device_by_id, device_id)
    if not device or int(device.get("user_id")) != int(user_id):
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)

    partner_ids_raw = await asyncio.to_thread(request.app["db"].get_connected_devices_as_controller, device_id)
    partner_ids_raw += await asyncio.to_thread(request.app["db"].get_connected_devices_as_target, device_id)

    seen: set[str] = set()
    pairings_payload: list[dict[str, Any]] = []
    for raw_partner_id in partner_ids_raw:
        partner_id = _normalize_device_id(str(raw_partner_id))
        if not partner_id or partner_id in seen:
            continue
        seen.add(partner_id)
        partner_device = await asyncio.to_thread(request.app["db"].get_device_by_id, partner_id)
        if not partner_device:
            continue
        pairings_payload.append(_device_payload(partner_device, request.app["online_devices"]))
    return web.json_response({"ok": True, "pairings": pairings_payload})


async def list_recent_devices(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user
    device_type = str(request.query.get("device_type") or "").strip()
    if device_type not in {"", "phone", "pc"}:
        return web.json_response({"ok": False, "message": "device_type gecersiz."}, status=400)

    user_devices = await asyncio.to_thread(request.app["db"].get_devices_for_user, int(user_id))
    partner_ids: set[str] = set()
    for dev in user_devices:
        own_id = _normalize_device_id(str(dev.get("device_id") or ""))
        if not own_id:
            continue
        as_controller = await asyncio.to_thread(request.app["db"].get_connected_devices_as_controller, own_id)
        as_target = await asyncio.to_thread(request.app["db"].get_connected_devices_as_target, own_id)
        for raw_partner_id in list(as_controller) + list(as_target):
            normalized_partner_id = _normalize_device_id(str(raw_partner_id))
            if normalized_partner_id:
                partner_ids.add(normalized_partner_id)

    devices_payload: list[dict[str, Any]] = []
    for partner_id in partner_ids:
        partner_device = await asyncio.to_thread(request.app["db"].get_device_by_id, partner_id)
        if not partner_device:
            continue
        if device_type and str(partner_device.get("device_type") or "") != device_type:
            continue
        devices_payload.append(_device_payload(partner_device, request.app["online_devices"]))
    return web.json_response({"ok": True, "devices": devices_payload})


async def desktop_phone_bundle(request: web.Request) -> web.Response:
    """
    Masaustu istemci: /devices + /recent-devices?phone + /pairings tek round-trip.
    """
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user
    pc_id = _normalize_device_id(request.query.get("device_id") or "")
    if not pc_id:
        return web.json_response({"ok": False, "message": "device_id gerekli."}, status=400)

    own = await asyncio.to_thread(request.app["db"].get_device_by_id, pc_id)
    if not own or int(own.get("user_id")) != int(user_id):
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)

    online = request.app["online_devices"]

    devices = await asyncio.to_thread(request.app["db"].get_devices_for_user, int(user_id))
    devices_payload = [_device_payload(device, online) for device in devices]

    partner_ids_raw = await asyncio.to_thread(request.app["db"].get_connected_devices_as_controller, pc_id)
    partner_ids_raw += await asyncio.to_thread(request.app["db"].get_connected_devices_as_target, pc_id)
    seen_pair: set[str] = set()
    pairings_payload: list[dict[str, Any]] = []
    for raw_partner_id in partner_ids_raw:
        partner_id = _normalize_device_id(str(raw_partner_id))
        if not partner_id or partner_id in seen_pair:
            continue
        seen_pair.add(partner_id)
        partner_device = await asyncio.to_thread(request.app["db"].get_device_by_id, partner_id)
        if not partner_device:
            continue
        pairings_payload.append(_device_payload(partner_device, online))

    partner_ids: set[str] = set()
    for dev in devices:
        own_id = _normalize_device_id(str(dev.get("device_id") or ""))
        if not own_id:
            continue
        as_controller = await asyncio.to_thread(request.app["db"].get_connected_devices_as_controller, own_id)
        as_target = await asyncio.to_thread(request.app["db"].get_connected_devices_as_target, own_id)
        for raw_partner_id in list(as_controller) + list(as_target):
            normalized_partner_id = _normalize_device_id(str(raw_partner_id))
            if normalized_partner_id:
                partner_ids.add(normalized_partner_id)

    recent_payload: list[dict[str, Any]] = []
    for partner_id in partner_ids:
        partner_device = await asyncio.to_thread(request.app["db"].get_device_by_id, partner_id)
        if not partner_device:
            continue
        if str(partner_device.get("device_type") or "") != "phone":
            continue
        recent_payload.append(_device_payload(partner_device, online))

    return web.json_response(
        {
            "ok": True,
            "devices": devices_payload,
            "recent_devices": recent_payload,
            "pairings": pairings_payload,
        }
    )


async def delete_pairing(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user

    data = await _json(request)
    device_id = _normalize_device_id(str(data.get("device_id") or ""))
    partner_device_id = _normalize_device_id(str(data.get("partner_device_id") or ""))
    if not device_id or not partner_device_id:
        return web.json_response({"ok": False, "message": "device_id ve partner_device_id gerekli."}, status=400)

    own_device = await asyncio.to_thread(request.app["db"].get_device_by_id, device_id)
    if not own_device or int(own_device.get("user_id")) != int(user_id):
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)

    deleted_ab = await asyncio.to_thread(request.app["db"].delete_connection, device_id, partner_device_id)
    deleted_ba = await asyncio.to_thread(request.app["db"].delete_connection, partner_device_id, device_id)
    if not (deleted_ab or deleted_ba):
        return web.json_response({"ok": False, "message": "Eslesme silinemedi."}, status=500)

    await _broadcast_presence_for_devices(request.app, device_id, partner_device_id)
    return web.json_response({"ok": True})


async def on_cleanup(app: web.Application) -> None:
    db = app.get("db")
    if db:
        db.close()


async def health_check(_request: web.Request) -> web.Response:
    """Yuk dengeleyici / istemci: HTTP katmaninin ayakta oldugunu dogrular (DB sart degil)."""
    return web.json_response({"ok": True, "service": "remote-phone-control-signaling"})


def create_app() -> web.Application:
    db = ServerDbClient()
    db.init_schema()

    app = web.Application()
    app["db"] = db
    app["sessions"] = {}
    app["session_devices"] = {}
    app["online_devices"] = {}
    app["ws_meta"] = {}
    app.add_routes(
        [
            web.get("/health", health_check),
            web.get("/", websocket_handler),
            web.post("/auth/register", auth_register),
            web.post("/auth/login", auth_login),
            web.get("/auth/me", auth_me),
            web.post("/auth/profile", auth_profile_update),
            web.post("/devices/upsert", upsert_device),
            web.get("/devices", list_devices),
            web.get("/devices/phone-bundle", desktop_phone_bundle),
            web.get("/recent-devices", list_recent_devices),
            web.get("/pairings", list_pairings),
            web.post("/pairings/delete", delete_pairing),
        ]
    )
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=ServerConfig.HOST, port=ServerConfig.PORT, access_log=None)