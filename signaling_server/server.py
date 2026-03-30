import asyncio
import json
import logging
import os
import sys

from aiohttp import WSMsgType, web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signaling_server.auth import issue_token, parse_token
from signaling_server.config import MessageTypes, ServerConfig
from signaling_server.db_client import ServerDbClient

logging.basicConfig(level=logging.INFO, format=ServerConfig.LOG_FORMAT)
logger = logging.getLogger(__name__)


def _online_key(user_id: int, device_id: str) -> str:
    return f"{user_id}:{device_id}"


def _device_payload(device: dict, online_devices: dict[str, dict]) -> dict:
    did = str(device.get("device_id") or "")
    ouid = device.get("owner_user_id")
    db_flag = bool(device.get("is_online"))
    # Gercek zamanli WS baglantisi; DB bayragi hesap degisiminde gecikmeli kalabiliyor.
    if ouid is not None and did:
        try:
            is_online = _online_key(int(ouid), did) in online_devices
        except (TypeError, ValueError):
            is_online = db_flag
    else:
        is_online = db_flag
    payload = {
        "device_id": device["device_id"],
        "device_type": device["device_type"],
        "device_name": device.get("device_name"),
        "address": device.get("address"),
        "is_online": is_online,
        "mac_address": device.get("mac_address"),
    }
    owner_name = (device.get("owner_name") or "").strip()
    owner_phone = (device.get("owner_phone") or "").strip()
    owner_email = (device.get("owner_email") or "").strip()
    if owner_name:
        payload["owner_name"] = owner_name
    if owner_phone:
        payload["owner_phone"] = owner_phone
    if owner_email:
        payload["owner_email"] = owner_email
    if ouid is not None:
        try:
            payload["owner_user_id"] = int(ouid)
        except (TypeError, ValueError):
            pass
    return payload


async def _json(request: web.Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


async def _require_user(request: web.Request) -> tuple[int, str] | None:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    payload = parse_token(auth_header[7:])
    if not payload:
        return None
    return payload["user_id"], payload["username"]


async def _send_json(ws: web.WebSocketResponse, payload: dict) -> None:
    await ws.send_str(json.dumps(payload, separators=(",", ":")))


def _session_entry(app: web.Application, code: str) -> dict:
    if code not in app["sessions"]:
        app["sessions"][code] = {}
        app["session_devices"][code] = {}
    return app["sessions"][code]


async def _evict_superseded_sessions(app: web.Application, evicted: list[tuple[int, str]]) -> None:
    """Ayni MAC ile baska oturum supersede edilince WS kapat ve presence yayinla."""
    for uid, did in evicted:
        key = _online_key(uid, did)
        entry = app["online_devices"].pop(key, None)
        if entry and entry.get("ws"):
            try:
                await entry["ws"].close()
            except Exception:
                logger.exception("Superseded oturum kapatilamadi: %s", key)
        try:
            await _broadcast_presence_change(app, uid, did)
        except Exception:
            logger.exception("Superseded presence yayini basarisiz: %s", key)


async def _upsert_device_and_evict(
    app: web.Application,
    user_id: int,
    device_id: str,
    device_type: str,
    device_name: str,
    mac_address: str | None = None,
) -> str | None:
    result = await asyncio.to_thread(
        app["db"].upsert_device,
        user_id,
        device_id,
        device_type,
        device_name,
        mac_address,
    )
    if not result or result[0] is None:
        return None
    resolved, evicted = result
    await _evict_superseded_sessions(app, evicted)
    return resolved


async def _get_paired_partner_refs(app: web.Application, user_id: int, device_id: str) -> list[tuple[int, str]]:
    return await asyncio.to_thread(app["db"].get_paired_partner_refs, user_id, device_id)


async def _get_paired_partner_refs_map(
    app: web.Application,
    user_id: int,
    device_ids: list[str],
) -> dict[str, list[tuple[int, str]]]:
    return await asyncio.to_thread(app["db"].get_paired_partner_refs_map, user_id, device_ids)


async def _send_device_ack(
    app: web.Application,
    user_id: int,
    device_id: str,
    paired_partner_refs_map: dict[str, list[tuple[int, str]]] | None = None,
) -> None:
    device_entry = app["online_devices"].get(_online_key(user_id, device_id))
    if not device_entry:
        return

    role = device_entry["role"]
    partner_refs = (
        paired_partner_refs_map.get(device_id, [])
        if paired_partner_refs_map is not None
        else await _get_paired_partner_refs(app, user_id, device_id)
    )
    paired_devices = [partner_id for _, partner_id in partner_refs]
    online_paired_devices = [
        partner_id
        for partner_user_id, partner_id in partner_refs
        if (
            _online_key(partner_user_id, partner_id) in app["online_devices"]
            and app["online_devices"][_online_key(partner_user_id, partner_id)]["role"] != role
        )
    ]
    await _send_json(
        device_entry["ws"],
        {
            "type": MessageTypes.DEVICE_ACK,
            "device_id": device_id,
            "paired_with": paired_devices[0] if paired_devices else "",
            "paired_devices": paired_devices,
            "online_paired_devices": online_paired_devices,
            "partner_online": bool(online_paired_devices),
        },
    )


async def _broadcast_presence_update(app: web.Application, user_id: int, *device_ids: str) -> None:
    root_device_ids = list(dict.fromkeys(device_id for device_id in device_ids if device_id))
    if not root_device_ids:
        return

    direct_partner_refs_map = await _get_paired_partner_refs_map(app, user_id, root_device_ids)
    impacted_device_ids: set[str] = set(root_device_ids)
    for partner_refs in direct_partner_refs_map.values():
        impacted_device_ids.update(partner_id for partner_user_id, partner_id in partner_refs if partner_user_id == user_id)

    paired_partner_refs_map = dict(direct_partner_refs_map)
    missing_ids = [device_id for device_id in impacted_device_ids if device_id not in paired_partner_refs_map]
    if missing_ids:
        paired_partner_refs_map.update(await _get_paired_partner_refs_map(app, user_id, missing_ids))

    for impacted_device_id in impacted_device_ids:
        try:
            await _send_device_ack(app, user_id, impacted_device_id, paired_partner_refs_map)
        except Exception:
            logger.exception("Presence update gonderilemedi: %s", impacted_device_id)


async def _broadcast_presence_change(app: web.Application, user_id: int, device_id: str) -> None:
    await _broadcast_presence_update(app, user_id, device_id)
    partner_refs = await _get_paired_partner_refs(app, user_id, device_id)
    cross_account_targets = {
        (partner_user_id, partner_id)
        for partner_user_id, partner_id in partner_refs
        if partner_user_id != user_id
    }
    for partner_user_id, partner_id in cross_account_targets:
        await _broadcast_presence_update(app, partner_user_id, partner_id)


def _mac_from_body(data: dict) -> str | None:
    m = (data.get("mac_address") or data.get("macAddress") or "").strip()
    return m or None


async def _handle_device_logout(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
    message: dict,
) -> None:
    """Cikis: DB cevrimdisi, eslestirilmis tum taraflara presence yayini."""
    device_id = str(message.get("device_id") or meta.get("device_id") or "").strip()
    if not device_id:
        return
    binding = await asyncio.to_thread(app["db"].get_device_binding_by_address, device_id)
    if not binding:
        return
    user_id = int(binding["user_id"])
    key = _online_key(user_id, device_id)
    entry = app["online_devices"].get(key)
    meta_uid = meta.get("user_id")
    authorized = (entry and entry.get("ws") is ws) or (
        meta_uid is not None and int(meta_uid) == user_id
    )
    if not authorized:
        return
    if entry and entry.get("ws") is ws:
        app["online_devices"].pop(key, None)
    await asyncio.to_thread(app["db"].set_device_online, user_id, device_id, False)
    meta["logout_notified"] = True
    await _broadcast_presence_change(app, user_id, device_id)


async def _persist_session_pairings(
    app: web.Application,
    _phone_user_id: int,
    phone_device_id: str,
    _pc_user_id: int,
    pc_device_id: str,
) -> None:
    """Tek pairing satiri; kullanici id'leri DB'de cihazlardan okunur."""
    await asyncio.to_thread(app["db"].save_pairing_by_device_ids, phone_device_id, pc_device_id)


async def _broadcast_session_presence(
    app: web.Application,
    first_user_id: int,
    first_device_id: str,
    second_user_id: int,
    second_device_id: str,
) -> None:
    await _broadcast_presence_update(app, first_user_id, first_device_id, second_device_id)
    if second_user_id != first_user_id:
        await _broadcast_presence_update(app, second_user_id, first_device_id, second_device_id)


async def _notify_paired(app: web.Application, code: str) -> None:
    session = app["sessions"].get(code, {})
    session_devices = app["session_devices"].get(code, {})
    if "phone" not in session or "pc" not in session:
        return

    phone_meta = app["ws_meta"].get(id(session["phone"])) or {}
    pc_meta = app["ws_meta"].get(id(session["pc"])) or {}
    if phone_meta.get("accessibility_enabled") is False:
        await _send_json(
            session["pc"],
            {
                "type": MessageTypes.ERROR,
                "code": "accessibility_required",
                "message": "Telefonda Erisilebilirlik servisi kapali. Telefonda uygulamayi acip Erisilebilirlik'i etkinlestirin.",
            },
        )
        await _send_json(
            session["phone"],
            {
                "type": MessageTypes.ERROR,
                "code": "accessibility_required",
                "message": "Erisilebilirlik kapali. Bilgisayardan kontrol icin Erisilebilirlik servisini acin ve yeniden baglanin.",
            },
        )
        return
    phone_user_id = phone_meta.get("user_id")
    pc_user_id = pc_meta.get("user_id")
    if not phone_user_id or not pc_user_id:
        await _send_json(session["phone"], {"type": MessageTypes.ERROR, "message": "Baglanti kullanici bilgisi eksik."})
        await _send_json(session["pc"], {"type": MessageTypes.ERROR, "message": "Baglanti kullanici bilgisi eksik."})
        return

    phone_device_id = session_devices.get("phone", "")
    pc_device_id = session_devices.get("pc", "")
    await _persist_session_pairings(app, phone_user_id, phone_device_id, pc_user_id, pc_device_id)

    logger.info("Paired session created: %s", code)
    for role, ws in session.items():
        partner_role = "pc" if role == "phone" else "phone"
        await _send_json(
            ws,
            {
                "type": MessageTypes.PAIRED,
                "code": code,
                "your_role": role,
                "partner_device_id": session_devices.get(partner_role, ""),
            },
        )
    await _broadcast_session_presence(app, phone_user_id, phone_device_id, pc_user_id, pc_device_id)


async def _pick_online_partner(app: web.Application, user_id: int, device_id: str, role: str) -> tuple[int, str] | None:
    partners = await _get_paired_partner_refs(app, user_id, device_id)
    for partner_user_id, partner_id in partners:
        partner_entry = app["online_devices"].get(_online_key(partner_user_id, partner_id))
        if partner_entry and partner_entry["role"] != role:
            return partner_user_id, partner_id
    return None


async def _pick_preferred_online_partner(
    app: web.Application,
    user_id: int,
    device_id: str,
    role: str,
    preferred_partner_id: str | None,
    preferred_partner_address: str | None,
) -> tuple[int, str] | None:
    """
    Sabit adres / device_id ile hedeflenen cihaza baglanir.
    Hedef devices tablosunda kayitli ve signaling uzerinde cevrimici + karsi roldedir yeterli
    (hesap farki pairings sartina bagli degil).
    Acikca adres verildiyse basarisiz olunca rastgele baska cihaza dusulmez (fallback yok).
    """
    lookup_partner_id = preferred_partner_id or preferred_partner_address
    explicit_target = bool(str(lookup_partner_id or "").strip())

    if lookup_partner_id:
        binding = await asyncio.to_thread(app["db"].get_device_binding_by_address, lookup_partner_id)
        if not binding:
            partner_refs = await _get_paired_partner_refs(app, user_id, device_id)
            for partner_user_id, partner_id in partner_refs:
                if partner_id != lookup_partner_id:
                    continue
                partner_entry = app["online_devices"].get(_online_key(partner_user_id, partner_id))
                if partner_entry and partner_entry["role"] != role:
                    return partner_user_id, partner_id
        else:
            target_user_id = int(binding["user_id"])
            candidate_id = str(binding["device_id"])
            if candidate_id != device_id:
                partner_entry = app["online_devices"].get(_online_key(target_user_id, candidate_id))
                if partner_entry and partner_entry["role"] != role:
                    return target_user_id, candidate_id

    if explicit_target:
        return None

    fallback_partner = await _pick_online_partner(app, user_id, device_id, role)
    if fallback_partner:
        return fallback_partner
    return None


async def _handle_device_hello(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
    message: dict,
) -> None:
    device_id = str(message.get("device_id") or "").strip()
    role = message.get("role", "")
    if not device_id or role not in {"phone", "pc"}:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "device_id ve role gerekli"})
        return

    binding = await asyncio.to_thread(app["db"].get_device_binding_by_address, device_id)
    if not binding:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Cihaz bulunamadi"})
        return
    user_id = int(binding["user_id"])
    if str(binding["device_id"]) != device_id or str(binding["device_type"]) != role:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Cihaz adresi bu oturumla eslesmiyor"})
        return

    evicted = await asyncio.to_thread(app["db"].apply_mac_supersede_sessions, user_id, device_id)
    await _evict_superseded_sessions(app, evicted)

    meta["device_id"] = device_id
    meta["user_id"] = user_id
    # Telefon kontrol komutlari icin Accessibility zorunlu: client bunu bildirir.
    if role == "phone":
        meta["accessibility_enabled"] = bool(message.get("accessibility_enabled", False))
    app["online_devices"][_online_key(user_id, device_id)] = {"ws": ws, "role": role, "user_id": user_id, "device_id": device_id}
    await asyncio.to_thread(app["db"].set_device_online, user_id, device_id, True)

    preferred_partner_id = str(message.get("preferred_partner_id") or "").strip() or None
    preferred_partner_address = str(message.get("preferred_partner_address") or "").strip() or None
    allow_auto_pair = bool(message.get("auto_pair", False))
    partner_info = None
    if allow_auto_pair:
        partner_info = await _pick_preferred_online_partner(
            app,
            user_id,
            device_id,
            role,
            preferred_partner_id,
            preferred_partner_address,
        )
    if allow_auto_pair and partner_info:
        partner_user_id, partner_id = partner_info
        partner_entry = app["online_devices"][_online_key(partner_user_id, partner_id)]
        partner_ws = partner_entry["ws"]
        partner_role = partner_entry["role"]
        # Eslesmede telefon tarafinda Accessibility acik degilse session'a gecme.
        phone_ws = ws if role == "phone" else partner_ws
        phone_meta = app["ws_meta"].get(id(phone_ws)) or {}
        if phone_meta.get("accessibility_enabled") is False:
            await _send_json(
                ws,
                {
                    "type": MessageTypes.ERROR,
                    "code": "accessibility_required",
                    "message": "Telefonda Erisilebilirlik servisi kapali. Baglanti baslatilamadi.",
                },
            )
            await _send_json(
                partner_ws,
                {
                    "type": MessageTypes.ERROR,
                    "code": "accessibility_required",
                    "message": "Telefonda Erisilebilirlik servisi kapali. Baglanti baslatilamadi.",
                },
            )
            return
        session_code = f"__auto_{min(device_id, partner_id)}_{max(device_id, partner_id)}"
        app["sessions"][session_code] = {role: ws, partner_role: partner_ws}
        app["session_devices"][session_code] = {role: device_id, partner_role: partner_id}
        meta["peer_code"] = session_code
        meta["peer_role"] = role
        partner_meta = app["ws_meta"].get(id(partner_ws))
        if partner_meta:
            partner_meta["peer_code"] = session_code
            partner_meta["peer_role"] = partner_role

        if role == "phone":
            await _persist_session_pairings(app, user_id, device_id, partner_user_id, partner_id)
        else:
            await _persist_session_pairings(app, user_id, partner_id, partner_user_id, device_id)
        await _send_json(
            ws,
            {
                "type": MessageTypes.AUTO_PAIRED,
                "your_role": role,
                "partner_device_id": partner_id,
            },
        )
        await _send_json(
            partner_ws,
            {
                "type": MessageTypes.AUTO_PAIRED,
                "your_role": partner_role,
                "partner_device_id": device_id,
            },
        )
        await _broadcast_session_presence(app, user_id, device_id, partner_user_id, partner_id)
        return

    if allow_auto_pair and (preferred_partner_id or preferred_partner_address):
        await _send_json(
            ws,
            {
                "type": MessageTypes.ERROR,
                "message": "Hedef cihaz bu adreste kayitli degil veya su an cevrimici degil.",
            },
        )

    await _broadcast_presence_change(app, user_id, device_id)


async def _handle_pair_confirm(app: web.Application, meta: dict, message: dict) -> None:
    first_device_id = message.get("my_device_id", "").strip()
    second_device_id = message.get("paired_with", "").strip()
    user_id = meta.get("user_id")
    if user_id and first_device_id and second_device_id:
        partner_user_id = user_id
        peer_code = meta.get("peer_code") or ""
        peer_role = meta.get("peer_role") or ""
        if peer_code and peer_role:
            other_role = "pc" if peer_role == "phone" else "phone"
            session = app["sessions"].get(peer_code, {})
            other_ws = session.get(other_role)
            if other_ws is not None:
                other_meta = app["ws_meta"].get(id(other_ws)) or {}
                if other_meta.get("user_id"):
                    partner_user_id = other_meta["user_id"]
        await asyncio.to_thread(app["db"].save_pairing_by_device_ids, first_device_id, second_device_id)
        await _broadcast_presence_change(app, user_id, first_device_id)
        if partner_user_id != user_id:
            await _broadcast_presence_change(app, partner_user_id, second_device_id)
        else:
            await _broadcast_presence_update(app, user_id, second_device_id)


async def _handle_register_or_join(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
    message: dict,
) -> None:
    code = message.get("code", "").strip()
    role = message.get("role", "phone" if message.get("type") == MessageTypes.REGISTER else "pc")
    if not code:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "code missing"})
        return

    if meta.get("user_id") is None:
        device_id = message.get("device_id", "").strip() or meta.get("device_id")
        if not device_id:
            await _send_json(ws, {"type": MessageTypes.ERROR, "message": "device_id missing"})
            return
        binding = await asyncio.to_thread(app["db"].get_device_binding_by_address, device_id)
        if not binding:
            await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Cihaz bulunamadi"})
            return
        user_id = int(binding["user_id"])
        if str(binding["device_id"]) != device_id:
            await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Cihaz kimligi bu oturumla eslesmiyor"})
            return
        meta["user_id"] = user_id

    current_peer_code = meta.get("peer_code") or ""
    if current_peer_code.startswith("__auto_"):
        ack = MessageTypes.REGISTERED if message.get("type") == MessageTypes.REGISTER else MessageTypes.JOINED
        await _send_json(ws, {"type": ack, "code": code, "role": role, "ignored": True})
        logger.info("Ignored %s for already auto-paired device=%s", message.get("type"), meta.get("device_id"))
        return

    session = _session_entry(app, code)
    session[role] = ws
    device_id = message.get("device_id", "").strip() or meta.get("device_id")
    app["session_devices"][code][role] = device_id
    meta["peer_code"] = code
    meta["peer_role"] = role
    if role == "phone":
        meta["accessibility_enabled"] = bool(message.get("accessibility_enabled", False))
    if meta.get("user_id") and device_id:
        meta["device_id"] = device_id
        evicted = await asyncio.to_thread(app["db"].apply_mac_supersede_sessions, meta["user_id"], device_id)
        await _evict_superseded_sessions(app, evicted)
        online_key = _online_key(meta["user_id"], device_id)
        if online_key not in app["online_devices"]:
            app["online_devices"][online_key] = {"ws": ws, "role": role, "user_id": meta["user_id"], "device_id": device_id}
            await asyncio.to_thread(app["db"].set_device_online, meta["user_id"], device_id, True)
            await _broadcast_presence_change(app, meta["user_id"], device_id)

    ack = MessageTypes.REGISTERED if message.get("type") == MessageTypes.REGISTER else MessageTypes.JOINED
    await _send_json(ws, {"type": ack, "code": code, "role": role})
    if "phone" in session and "pc" in session:
        await _notify_paired(app, code)
    elif message.get("type") == MessageTypes.JOIN:
        await _send_json(ws, {"type": MessageTypes.WAITING, "message": "Telefon baglanmayi bekliyor..."})


async def _resolve_peer_ws(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
) -> web.WebSocketResponse | None:
    peer_code = meta.get("peer_code")
    peer_role = meta.get("peer_role")
    if not peer_code or not peer_role:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Not registered"})
        return None

    session = app["sessions"].get(peer_code, {})
    other_role = "pc" if peer_role == "phone" else "phone"
    other_ws = session.get(other_role)
    if not other_ws:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": f"{other_role} bagli degil"})
        return None
    return other_ws


async def _relay_message(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
    message: dict,
    raw_text: str | None = None,
) -> None:
    other_ws = await _resolve_peer_ws(app, ws, meta)
    if not other_ws:
        return
    await other_ws.send_str(raw_text if raw_text is not None else json.dumps(message, separators=(",", ":")))


async def _relay_binary_frame(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
    payload: bytes,
) -> None:
    other_ws = await _resolve_peer_ws(app, ws, meta)
    if not other_ws:
        return
    await other_ws.send_bytes(payload)


async def websocket_handler(request: web.Request) -> web.StreamResponse:
    ws_probe = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024, heartbeat=20)
    if not ws_probe.can_prepare(request).ok:
        return web.Response(text="OK\n")

    ws = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024, heartbeat=20)
    await ws.prepare(request)

    app = request.app
    meta = {"peer_code": None, "peer_role": None, "device_id": None, "user_id": None}
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

            message_type = message.get("type", "")
            if message_type not in {MessageTypes.FRAME, MessageTypes.HEARTBEAT}:
                logger.info("[%s] device_id=%s code=%s role=%s", message_type, message.get("device_id"), message.get("code"), message.get("role"))

            if message_type == MessageTypes.DEVICE_HELLO:
                await _handle_device_hello(app, ws, meta, message)
            elif message_type == MessageTypes.DEVICE_LOGOUT:
                await _handle_device_logout(app, ws, meta, message)
            elif message_type == MessageTypes.PAIR_CONFIRM:
                await _handle_pair_confirm(app, meta, message)
            elif message_type in {MessageTypes.REGISTER, MessageTypes.JOIN}:
                await _handle_register_or_join(app, ws, meta, message)
            elif message_type in {MessageTypes.REQUEST_PRESENCE, MessageTypes.HEARTBEAT}:
                device_id = meta.get("device_id")
                user_id = meta.get("user_id")
                if device_id and user_id:
                    await _send_device_ack(app, user_id, device_id)
                if message_type == MessageTypes.HEARTBEAT:
                    peer_ws = await _resolve_peer_ws(app, ws, meta) if meta.get("peer_code") else None
                    if peer_ws:
                        await peer_ws.send_str(raw.data)
            elif message_type in MessageTypes.RELAY_TYPES:
                await _relay_message(app, ws, meta, message, raw_text=raw.data)
            else:
                await _send_json(ws, {"type": MessageTypes.ERROR, "message": f"Unknown: {message_type}"})
    finally:
        device_id = meta.get("device_id")
        user_id = meta.get("user_id")
        online_key = _online_key(user_id, device_id) if device_id and user_id else None
        if not meta.get("logout_notified"):
            if online_key and app["online_devices"].get(online_key, {}).get("ws") is ws:
                app["online_devices"].pop(online_key, None)
                await asyncio.to_thread(app["db"].set_device_online, user_id, device_id, False)

        peer_code = meta.get("peer_code")
        peer_role = meta.get("peer_role")
        if peer_code and peer_role:
            session = app["sessions"].get(peer_code, {})
            if session.get(peer_role) is ws:
                session.pop(peer_role, None)
                app["session_devices"].get(peer_code, {}).pop(peer_role, None)
                other_role = "pc" if peer_role == "phone" else "phone"
                other_ws = session.get(other_role)
                if other_ws:
                    try:
                        await _send_json(other_ws, {"type": MessageTypes.PEER_DISCONNECTED, "role": peer_role})
                    except Exception:
                        pass
            if not session:
                app["sessions"].pop(peer_code, None)
                app["session_devices"].pop(peer_code, None)

        app["ws_meta"].pop(id(ws), None)
        if device_id and user_id and not meta.get("logout_notified"):
            await _broadcast_presence_change(app, user_id, device_id)
    return ws


async def auth_register(request: web.Request) -> web.Response:
    data = await _json(request)
    email = (data.get("email") or data.get("username") or "").strip()
    password = data.get("password", "")
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    phone = (data.get("phone") or "").strip() or None
    success, message = await asyncio.to_thread(
        request.app["db"].register_user,
        email,
        password,
        first_name,
        last_name,
        phone,
    )
    if not success:
        return web.json_response({"ok": False, "message": message}, status=400)

    auth_result = await asyncio.to_thread(request.app["db"].authenticate_user, email, password)
    if auth_result is None:
        return web.json_response({"ok": False, "message": "Kayit sonrasi giris yapilamadi."}, status=500)
    user_id, normalized_username = auth_result

    device_id = data.get("device_id", "").strip()
    device_type = data.get("device_type", "").strip()
    device_name = data.get("device_name", "").strip()
    mac_address = _mac_from_body(data)
    resolved_device_id = ""
    if device_type in {"phone", "pc"}:
        if device_type == "phone" and not mac_address:
            return web.json_response(
                {"ok": False, "message": "Telefon kaydi icin mac_address (cihaz parmak izi) gerekli."},
                status=400,
            )
        resolved_device_id = (
            await _upsert_device_and_evict(
                request.app,
                user_id,
                device_id,
                device_type,
                device_name,
                mac_address,
            )
            or ""
        )
        if not resolved_device_id:
            return web.json_response({"ok": False, "message": "Cihaz kaydi guncellenemedi."}, status=500)

    token = issue_token(user_id, normalized_username)
    return web.json_response(
        {
            "ok": True,
            "message": message,
            "token": token,
            "user": {
                "id": user_id,
                "username": normalized_username,
                "email": email.strip().lower(),
                "device_id": resolved_device_id,
                "address": resolved_device_id,
            },
        }
    )


async def auth_login(request: web.Request) -> web.Response:
    data = await _json(request)
    login_id = (data.get("email") or data.get("username") or "").strip()
    auth_result = await asyncio.to_thread(
        request.app["db"].authenticate_user,
        login_id,
        data.get("password", ""),
    )
    if auth_result is None:
        return web.json_response({"ok": False, "message": "Kullanici adi veya sifre hatali."}, status=401)

    user_id, username = auth_result
    device_id = data.get("device_id", "").strip()
    device_type = data.get("device_type", "").strip()
    device_name = data.get("device_name", "").strip()
    mac_address = _mac_from_body(data)
    resolved_device_id = ""
    if device_type in {"phone", "pc"}:
        if device_type == "phone" and not mac_address:
            return web.json_response(
                {"ok": False, "message": "Telefon girisi icin mac_address (cihaz parmak izi) gerekli."},
                status=400,
            )
        resolved_device_id = (
            await _upsert_device_and_evict(
                request.app,
                user_id,
                device_id,
                device_type,
                device_name,
                mac_address,
            )
            or ""
        )
        if not resolved_device_id:
            return web.json_response({"ok": False, "message": "Cihaz kaydi guncellenemedi."}, status=500)

    token = issue_token(user_id, username)
    return web.json_response(
        {
            "ok": True,
            "token": token,
            "user": {
                "id": user_id,
                "username": username,
                "email": login_id.strip().lower(),
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
    profile = await asyncio.to_thread(request.app["db"].get_user_profile, user_id, request.query.get("device_id"))
    if not profile:
        return web.json_response({"ok": False, "message": "Kullanici bulunamadi."}, status=404)
    return web.json_response({"ok": True, "user": profile})


async def upsert_device(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)

    data = await _json(request)
    device_id = data.get("device_id", "").strip()
    device_type = data.get("device_type", "").strip()
    device_name = data.get("device_name", "").strip()
    mac_address = _mac_from_body(data)
    if device_type not in {"phone", "pc"}:
        return web.json_response({"ok": False, "message": "device_id ve device_type gerekli."}, status=400)
    if device_type == "phone" and not mac_address:
        return web.json_response(
            {"ok": False, "message": "Telefon icin mac_address gerekli."},
            status=400,
        )

    resolved_device_id = (
        await _upsert_device_and_evict(
            request.app,
            user[0],
            device_id,
            device_type,
            device_name,
            mac_address,
        )
        or ""
    )
    if not resolved_device_id:
        return web.json_response({"ok": False, "message": "Cihaz kaydi guncellenemedi."}, status=500)
    return web.json_response({"ok": True, "device_id": resolved_device_id, "address": resolved_device_id})


async def list_devices(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)

    devices = await asyncio.to_thread(request.app["db"].get_user_devices, user[0])
    payload = [_device_payload(device, request.app["online_devices"]) for device in devices]
    return web.json_response({"ok": True, "devices": payload})


async def list_pairings(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)

    device_id = request.query.get("device_id")
    if not device_id:
        return web.json_response({"ok": False, "message": "device_id gerekli."}, status=400)
    owns_device = await asyncio.to_thread(request.app["db"].user_owns_device, user[0], device_id)
    if not owns_device:
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)
    pairings = await asyncio.to_thread(request.app["db"].get_device_pairings, user[0], device_id)
    payload = [_device_payload(item, request.app["online_devices"]) for item in pairings]
    return web.json_response({"ok": True, "pairings": payload})


async def list_recent_devices(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)

    device_type = (request.query.get("device_type") or "").strip()
    if device_type not in {"phone", "pc"}:
        return web.json_response({"ok": False, "message": "device_type gerekli."}, status=400)

    devices = await asyncio.to_thread(request.app["db"].get_user_recent_partner_devices, user[0], device_type)
    payload = [_device_payload(device, request.app["online_devices"]) for device in devices]
    return web.json_response({"ok": True, "devices": payload})


async def delete_pairing(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)

    data = await _json(request)
    device_id = data.get("device_id", "").strip()
    partner_device_id = data.get("partner_device_id", "").strip()
    if not device_id or not partner_device_id:
        return web.json_response({"ok": False, "message": "device_id ve partner_device_id gerekli."}, status=400)
    owns_device = await asyncio.to_thread(request.app["db"].user_owns_device, user[0], device_id)
    if not owns_device:
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)

    success = await asyncio.to_thread(
        request.app["db"].delete_pairing_by_device_ids,
        user[0],
        device_id,
        partner_device_id,
    )
    if not success:
        return web.json_response({"ok": False, "message": "Eslesme silinemedi."}, status=500)
    await _broadcast_presence_update(request.app, user[0], device_id, partner_device_id)
    return web.json_response({"ok": True})


async def on_cleanup(app: web.Application) -> None:
    app["db"].close()


def create_app() -> web.Application:
    db = ServerDbClient()
    db.init_schema()
    db.reset_all_online()

    app = web.Application()
    app["db"] = db
    app["sessions"] = {}
    app["session_devices"] = {}
    app["online_devices"] = {}
    app["ws_meta"] = {}
    app.add_routes(
        [
            web.get("/", websocket_handler),
            web.post("/auth/register", auth_register),
            web.post("/auth/login", auth_login),
            web.get("/auth/me", auth_me),
            web.post("/devices/upsert", upsert_device),
            web.get("/devices", list_devices),
            web.get("/recent-devices", list_recent_devices),
            web.get("/pairings", list_pairings),
            web.post("/pairings/delete", delete_pairing),
        ]
    )
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=ServerConfig.HOST, port=ServerConfig.PORT, access_log=None)
