import asyncio
import json
import logging
import os
import sys
from datetime import datetime

from aiohttp import WSMsgType, web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signaling_server.auth import issue_token, parse_token
from signaling_server.config import MessageTypes, ServerConfig
from signaling_server.db_client import ServerDbClient

logging.basicConfig(level=logging.INFO, format=ServerConfig.LOG_FORMAT)
logger = logging.getLogger(__name__)


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _device_payload(device: dict, online_devices: dict[str, dict]) -> dict:
    return {
        "device_id": device["device_id"],
        "device_type": device["device_type"],
        "device_name": device.get("device_name"),
        "address": device.get("address"),
        "last_seen": _serialize_datetime(device.get("last_seen")),
        "online": device["device_id"] in online_devices,
    }


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


async def _get_paired_partners(app: web.Application, device_id: str) -> list[str]:
    return await asyncio.to_thread(app["db"].get_paired_partners, device_id)


async def _get_paired_partners_map(app: web.Application, device_ids: list[str]) -> dict[str, list[str]]:
    return await asyncio.to_thread(app["db"].get_paired_partners_map, device_ids)


async def _send_device_ack(
    app: web.Application,
    device_id: str,
    paired_partners_map: dict[str, list[str]] | None = None,
) -> None:
    device_entry = app["online_devices"].get(device_id)
    if not device_entry:
        return

    role = device_entry["role"]
    paired_devices = (
        paired_partners_map.get(device_id, [])
        if paired_partners_map is not None
        else await _get_paired_partners(app, device_id)
    )
    online_paired_devices = [
        partner_id
        for partner_id in paired_devices
        if partner_id in app["online_devices"] and app["online_devices"][partner_id]["role"] != role
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


async def _broadcast_presence_update(app: web.Application, *device_ids: str) -> None:
    root_device_ids = list(dict.fromkeys(device_id for device_id in device_ids if device_id))
    if not root_device_ids:
        return

    direct_partners_map = await _get_paired_partners_map(app, root_device_ids)
    impacted_device_ids: set[str] = set(root_device_ids)
    for partner_ids in direct_partners_map.values():
        impacted_device_ids.update(partner_ids)

    paired_partners_map = dict(direct_partners_map)
    missing_ids = [device_id for device_id in impacted_device_ids if device_id not in paired_partners_map]
    if missing_ids:
        paired_partners_map.update(await _get_paired_partners_map(app, missing_ids))

    for impacted_device_id in impacted_device_ids:
        try:
            await _send_device_ack(app, impacted_device_id, paired_partners_map)
        except Exception:
            logger.exception("Presence update gonderilemedi: %s", impacted_device_id)


async def _notify_paired(app: web.Application, code: str) -> None:
    session = app["sessions"].get(code, {})
    session_devices = app["session_devices"].get(code, {})
    if "phone" not in session or "pc" not in session:
        return

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


async def _pick_online_partner(app: web.Application, device_id: str, role: str) -> str | None:
    partners = await _get_paired_partners(app, device_id)
    for partner_id in partners:
        partner_entry = app["online_devices"].get(partner_id)
        if partner_entry and partner_entry["role"] != role:
            return partner_id
    return None


async def _pick_preferred_online_partner(
    app: web.Application,
    device_id: str,
    role: str,
    preferred_partner_id: str | None,
) -> str | None:
    if preferred_partner_id:
        partner_entry = app["online_devices"].get(preferred_partner_id)
        if partner_entry and partner_entry["role"] != role:
            return preferred_partner_id
    return await _pick_online_partner(app, device_id, role)


async def _handle_device_hello(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
    message: dict,
) -> None:
    device_id = str(message.get("device_id") or "").strip()
    role = message.get("role", "")
    if not device_id or role not in {"phone", "pc"}:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "device_id and role required"})
        return

    meta["device_id"] = device_id
    app["online_devices"][device_id] = {"ws": ws, "role": role}

    preferred_partner_id = str(message.get("preferred_partner_id") or "").strip() or None
    allow_auto_pair = bool(message.get("auto_pair", False))
    partner_id = None
    if allow_auto_pair:
        partner_id = await _pick_preferred_online_partner(app, device_id, role, preferred_partner_id)
    if allow_auto_pair and partner_id:
        partner_entry = app["online_devices"][partner_id]
        partner_ws = partner_entry["ws"]
        partner_role = partner_entry["role"]
        session_code = f"__auto_{min(device_id, partner_id)}_{max(device_id, partner_id)}"
        app["sessions"][session_code] = {role: ws, partner_role: partner_ws}
        app["session_devices"][session_code] = {role: device_id, partner_role: partner_id}
        meta["peer_code"] = session_code
        meta["peer_role"] = role
        partner_meta = app["ws_meta"].get(id(partner_ws))
        if partner_meta:
            partner_meta["peer_code"] = session_code
            partner_meta["peer_role"] = partner_role

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
        await _broadcast_presence_update(app, device_id, partner_id)
        return

    await _broadcast_presence_update(app, device_id)


async def _handle_pair_confirm(app: web.Application, message: dict) -> None:
    first_device_id = message.get("my_device_id", "").strip()
    second_device_id = message.get("paired_with", "").strip()
    if first_device_id and second_device_id:
        await asyncio.to_thread(app["db"].save_pairing_by_device_ids, first_device_id, second_device_id)
        await _broadcast_presence_update(app, first_device_id, second_device_id)


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

    current_peer_code = meta.get("peer_code") or ""
    if current_peer_code.startswith("__auto_"):
        ack = MessageTypes.REGISTERED if message.get("type") == MessageTypes.REGISTER else MessageTypes.JOINED
        await _send_json(ws, {"type": ack, "code": code, "role": role, "ignored": True})
        logger.info("Ignored %s for already auto-paired device=%s", message.get("type"), meta.get("device_id"))
        return

    session = _session_entry(app, code)
    session[role] = ws
    app["session_devices"][code][role] = message.get("device_id", "").strip() or meta.get("device_id")
    meta["peer_code"] = code
    meta["peer_role"] = role

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
    meta = {"peer_code": None, "peer_role": None, "device_id": None}
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
            if message_type != MessageTypes.FRAME:
                logger.info("[%s] device_id=%s code=%s role=%s", message_type, message.get("device_id"), message.get("code"), message.get("role"))

            if message_type == MessageTypes.DEVICE_HELLO:
                await _handle_device_hello(app, ws, meta, message)
            elif message_type == MessageTypes.PAIR_CONFIRM:
                await _handle_pair_confirm(app, message)
            elif message_type in {MessageTypes.REGISTER, MessageTypes.JOIN}:
                await _handle_register_or_join(app, ws, meta, message)
            elif message_type in MessageTypes.RELAY_TYPES:
                await _relay_message(app, ws, meta, message, raw_text=raw.data)
            else:
                await _send_json(ws, {"type": MessageTypes.ERROR, "message": f"Unknown: {message_type}"})
    finally:
        device_id = meta.get("device_id")
        if device_id and app["online_devices"].get(device_id, {}).get("ws") is ws:
            app["online_devices"].pop(device_id, None)

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
        if device_id:
            await _broadcast_presence_update(app, device_id)
    return ws


async def auth_register(request: web.Request) -> web.Response:
    data = await _json(request)
    username = data.get("username", "")
    password = data.get("password", "")
    success, message = await asyncio.to_thread(request.app["db"].register_user, username, password)
    if not success:
        return web.json_response({"ok": False, "message": message}, status=400)

    auth_result = await asyncio.to_thread(request.app["db"].authenticate_user, username, password)
    if auth_result is None:
        return web.json_response({"ok": False, "message": "Kayit sonrasi giris yapilamadi."}, status=500)
    user_id, normalized_username, address = auth_result

    device_id = data.get("device_id", "").strip()
    device_type = data.get("device_type", "").strip()
    device_name = data.get("device_name", "").strip()
    if device_id and device_type in {"phone", "pc"}:
        claimed = await asyncio.to_thread(request.app["db"].upsert_device, user_id, device_id, device_type, device_name)
        if not claimed:
            return web.json_response({"ok": False, "message": "Bu cihaz baska bir hesapta kayitli."}, status=403)

    token = issue_token(user_id, normalized_username)
    return web.json_response(
        {
            "ok": True,
            "message": message,
            "token": token,
            "user": {"id": user_id, "username": normalized_username, "address": address},
        }
    )


async def auth_login(request: web.Request) -> web.Response:
    data = await _json(request)
    auth_result = await asyncio.to_thread(
        request.app["db"].authenticate_user,
        data.get("username", ""),
        data.get("password", ""),
    )
    if auth_result is None:
        return web.json_response({"ok": False, "message": "Kullanici adi veya sifre hatali."}, status=401)

    user_id, username, address = auth_result
    device_id = data.get("device_id", "").strip()
    device_type = data.get("device_type", "").strip()
    device_name = data.get("device_name", "").strip()
    if device_id and device_type in {"phone", "pc"}:
        claimed = await asyncio.to_thread(request.app["db"].upsert_device, user_id, device_id, device_type, device_name)
        if not claimed:
            return web.json_response({"ok": False, "message": "Bu cihaz baska bir hesapta kayitli."}, status=403)

    token = issue_token(user_id, username)
    return web.json_response(
        {
            "ok": True,
            "token": token,
            "user": {"id": user_id, "username": username, "address": address},
        }
    )


async def auth_me(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, username = user
    profile = await asyncio.to_thread(request.app["db"].get_user_profile, user_id)
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
    if not device_id or device_type not in {"phone", "pc"}:
        return web.json_response({"ok": False, "message": "device_id ve device_type gerekli."}, status=400)

    claimed = await asyncio.to_thread(request.app["db"].upsert_device, user[0], device_id, device_type, device_name)
    if not claimed:
        return web.json_response({"ok": False, "message": "Bu cihaz baska bir hesapta kayitli."}, status=403)
    return web.json_response({"ok": True})


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
    pairings = await asyncio.to_thread(request.app["db"].get_device_pairings, device_id)
    payload = [_device_payload(item, request.app["online_devices"]) for item in pairings]
    return web.json_response({"ok": True, "pairings": payload})


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
        device_id,
        partner_device_id,
    )
    if not success:
        return web.json_response({"ok": False, "message": "Eslesme silinemedi."}, status=500)
    return web.json_response({"ok": True})


async def on_cleanup(app: web.Application) -> None:
    app["db"].close()


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
            web.get("/", websocket_handler),
            web.post("/auth/register", auth_register),
            web.post("/auth/login", auth_login),
            web.get("/auth/me", auth_me),
            web.post("/devices/upsert", upsert_device),
            web.get("/devices", list_devices),
            web.get("/pairings", list_pairings),
            web.post("/pairings/delete", delete_pairing),
        ]
    )
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=ServerConfig.HOST, port=ServerConfig.PORT, access_log=None)
