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

# ------------------------------------------------------------------ #
#  YARDIMCI FONKSİYONLAR                                              #
# ------------------------------------------------------------------ #

def _online_key(user_id: int, device_id: str) -> str:
    return f"{user_id}:{device_id}"


def _canon_device_id(raw: str | None) -> str | None:
    if not raw:
        return None
    return ServerDbClient._norm_device_id(str(raw).strip())


def _opposite_role(role: str) -> str:
    return "target" if role == "controller" else "controller"


def _device_payload(device: dict, online_devices: dict[str, dict]) -> dict:
    did  = str(device.get("device_id") or "")
    ouid = device.get("owner_user_id")
    db_flag = bool(device.get("is_online"))
    if ouid is not None and did:
        try:
            is_online = _online_key(int(ouid), did) in online_devices
        except (TypeError, ValueError):
            is_online = db_flag
    else:
        is_online = db_flag
    payload = {
        "device_id":   device["device_id"],
        "device_type": device["device_type"],
        "device_name": device.get("device_name"),
        "is_online":   is_online,
        "mac_address": device.get("mac_address"),
    }
    for key in ("owner_name", "owner_phone", "owner_email"):
        val = (device.get(key) or "").strip()
        if val:
            payload[key] = val
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


def _mac_from_body(data: dict) -> str | None:
    m = (data.get("mac_address") or data.get("macAddress") or "").strip()
    return m or None


# ------------------------------------------------------------------ #
#  SESSION YARDIMCILARI                                               #
# ------------------------------------------------------------------ #

def _session_entry(app: web.Application, code: str) -> dict:
    if code not in app["sessions"]:
        app["sessions"][code] = {}
        app["session_devices"][code] = {}
    return app["sessions"][code]


# ------------------------------------------------------------------ #
#  ONLINE / EVICT                                                     #
# ------------------------------------------------------------------ #

async def _evict_superseded_sessions(
    app: web.Application, evicted: list[tuple[int, str]]
) -> None:
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
        user_id, device_id, device_type, device_name, mac_address,
    )
    if not result or result[0] is None:
        return None
    resolved, evicted = result
    await _evict_superseded_sessions(app, evicted)
    return resolved


# ------------------------------------------------------------------ #
#  PRESENCE                                                           #
# ------------------------------------------------------------------ #

async def _get_all_paired_devices(
    app: web.Application, device_id: str
) -> list[tuple[int, str]]:
    return await asyncio.to_thread(app["db"].get_all_paired_devices, device_id)


async def _send_device_ack(
    app: web.Application,
    user_id: int,
    device_id: str,
) -> None:
    """Cihaza güncel pairing ve online durumunu gönderir."""
    canon = _canon_device_id(device_id) or device_id
    entry = app["online_devices"].get(_online_key(user_id, canon))
    if not entry:
        return

    # Bu cihazın tüm paired partnerlarını çek
    all_partners = await _get_all_paired_devices(app, canon)
    paired_ids = [str(pid) for _, pid in all_partners]
    online_paired: list[str] = []
    seen: set[str] = set()
    for puid, pid in all_partners:
        pc = _canon_device_id(pid) or pid
        if pc in seen or pc == canon:
            continue
        if _online_key(int(puid), pc) in app["online_devices"]:
            online_paired.append(pc)
            seen.add(pc)

    await _send_json(
        entry["ws"],
        {
            "type": MessageTypes.DEVICE_ACK,
            "device_id": canon,
            "paired_with": paired_ids[0] if paired_ids else "",
            "paired_devices": paired_ids,
            "online_paired_devices": online_paired,
            "partner_online": bool(online_paired),
        },
    )


async def _broadcast_presence_change(
    app: web.Application, user_id: int, device_id: str
) -> None:
    """Değişen cihaz ve tüm paired partnerlarına ACK yayınlar."""
    canon = _canon_device_id(device_id) or device_id

    # Önce cihazın kendisine gönder
    await _send_device_ack(app, user_id, canon)

    # Tüm paired partnerlarına da gönder
    partners = await _get_all_paired_devices(app, canon)
    seen: set[tuple[int, str]] = set()
    for puid, pid in partners:
        t = (int(puid), str(pid))
        if t in seen:
            continue
        seen.add(t)
        if _online_key(t[0], t[1]) not in app["online_devices"]:
            continue
        try:
            await _send_device_ack(app, t[0], t[1])
        except Exception:
            logger.exception("Presence fan-out basarisiz: uid=%s did=%s", t[0], t[1])


# ------------------------------------------------------------------ #
#  PAIRING KAYIT                                                      #
# ------------------------------------------------------------------ #

async def _persist_pairing(
    app: web.Application,
    controller_device_id: str,
    target_device_id: str,
) -> bool:
    """controller → target yönlü pairing'i kaydeder."""
    return await asyncio.to_thread(
        app["db"].save_pairing,
        controller_device_id,
        target_device_id,
    )


# ------------------------------------------------------------------ #
#  SESSION PAİRİNG BİLDİRİMİ                                         #
# ------------------------------------------------------------------ #

async def _notify_paired(app: web.Application, code: str) -> None:
    """
    Session'da iki cihaz da bağlandığında eşleşme bildirir.
    Roller: 'controller' (bağlanan: phone veya pc) ve 'target' (bağlanılan: phone).
    """
    session = app["sessions"].get(code, {})
    session_devices = app["session_devices"].get(code, {})

    if "controller" not in session or "target" not in session:
        return

    ctrl_ws  = session["controller"]
    tgt_ws   = session["target"]
    ctrl_did = session_devices.get("controller", "")
    tgt_did  = session_devices.get("target", "")

    ctrl_meta = app["ws_meta"].get(id(ctrl_ws)) or {}
    tgt_meta  = app["ws_meta"].get(id(tgt_ws)) or {}

    # Accessibility kontrolü: target (phone) tarafında zorunlu
    if tgt_meta.get("accessibility_enabled") is False:
        err = {
            "type": MessageTypes.ERROR,
            "code": "accessibility_required",
            "message": "Hedef telefonda Erisilebilirlik servisi kapali.",
        }
        await _send_json(ctrl_ws, err)
        await _send_json(tgt_ws, {
            "type": MessageTypes.ERROR,
            "code": "accessibility_required",
            "message": "Erisilebilirlik kapali. Kontrole izin vermek icin etkinlestirin.",
        })
        return

    ctrl_uid = ctrl_meta.get("user_id")
    tgt_uid  = tgt_meta.get("user_id")
    if not ctrl_uid or not tgt_uid:
        for ws in (ctrl_ws, tgt_ws):
            await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Baglanti kullanici bilgisi eksik."})
        return

    # Pairing kaydet: controller → target
    ok = await _persist_pairing(app, ctrl_did, tgt_did)
    if not ok:
        logger.warning("_notify_paired: pairing kaydedilemedi %s -> %s", ctrl_did, tgt_did)

    logger.info("Paired session: %s (%s -> %s)", code, ctrl_did, tgt_did)

    await _send_json(ctrl_ws, {
        "type": MessageTypes.PAIRED,
        "code": code,
        "your_role": "controller",
        "partner_device_id": tgt_did,
    })
    await _send_json(tgt_ws, {
        "type": MessageTypes.PAIRED,
        "code": code,
        "your_role": "target",
        "partner_device_id": ctrl_did,
    })

    # Her iki tarafa presence yayını
    await _broadcast_presence_change(app, ctrl_uid, ctrl_did)
    if tgt_uid != ctrl_uid:
        await _broadcast_presence_change(app, tgt_uid, tgt_did)


# ------------------------------------------------------------------ #
#  OTOMATİK PARTNER BULMA                                             #
# ------------------------------------------------------------------ #

async def _pick_online_partner(
    app: web.Application, device_id: str
) -> tuple[int, str] | None:
    """Paired partnerlar arasından online olanı seçer."""
    partners = await _get_all_paired_devices(app, device_id)
    for puid, pid in partners:
        if _online_key(int(puid), pid) in app["online_devices"]:
            return int(puid), str(pid)
    return None


async def _pick_preferred_online_partner(
    app: web.Application,
    device_id: str,
    preferred_id: str | None,
) -> tuple[int, str] | None:
    """
    Tercih edilen cihaza bağlanmayı dener.
    Tercih yoksa paired listesinden online birini seçer.
    Açıkça hedef verilmişse fallback yapılmaz.
    """
    explicit = bool(preferred_id)

    if preferred_id:
        info = await asyncio.to_thread(app["db"].get_device_info, preferred_id)
        if info:
            puid = int(info["user_id"])
            pid  = str(info["device_id"])
            if pid != device_id and _online_key(puid, pid) in app["online_devices"]:
                return puid, pid

    if explicit:
        return None  # Hedef belirtildi ama bulunamadı → fallback yok

    return await _pick_online_partner(app, device_id)


# ------------------------------------------------------------------ #
#  WEBSOCKETd MESAJ İŞLEYİCİLERİ                                     #
# ------------------------------------------------------------------ #

async def _handle_device_logout(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
    message: dict,
) -> None:
    device_id = str(message.get("device_id") or meta.get("device_id") or "").strip()
    if not device_id:
        return
    info = await asyncio.to_thread(app["db"].get_device_info, device_id)
    if not info:
        return
    user_id = int(info["user_id"])
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


async def _handle_device_hello(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
    message: dict,
) -> None:
    """
    Cihaz bağlantı isteği.
    role: 'controller' (bağlanan: phone veya pc) veya 'target' (bağlanılan: phone)
    """
    raw_addr = str(message.get("device_id") or "").strip()
    role = message.get("role", "")
    if not raw_addr or role not in {"controller", "target"}:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "device_id ve role (controller/target) gerekli"})
        return

    info = await asyncio.to_thread(app["db"].get_device_info, raw_addr)
    if not info:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Cihaz bulunamadi"})
        return

    user_id   = int(info["user_id"])
    device_id = str(info["device_id"])
    device_type = str(info["device_type"])

    # Target her zaman phone olmalı; controller phone veya pc olabilir
    if role == "target" and device_type != "phone":
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Sadece telefon hedef (target) olabilir"})
        return

    # MAC çakışması varsa eski oturumu kapat
    result = await asyncio.to_thread(app["db"].upsert_device, user_id, device_id, device_type, None, None)
    if result and result[1]:
        await _evict_superseded_sessions(app, result[1])

    meta["device_id"] = device_id
    meta["user_id"]   = user_id
    # Accessibility yalnızca target (phone) için gerekli
    if role == "target":
        meta["accessibility_enabled"] = bool(message.get("accessibility_enabled", False))

    app["online_devices"][_online_key(user_id, device_id)] = {
        "ws": ws, "role": role, "user_id": user_id, "device_id": device_id
    }
    await asyncio.to_thread(app["db"].set_device_online, user_id, device_id, True)

    # Otomatik eşleşme
    allow_auto_pair = bool(message.get("auto_pair", False))
    preferred_id = (
        str(message.get("preferred_partner_id") or message.get("preferred_partner_address") or "").strip()
        or None
    )

    if allow_auto_pair:
        partner_info = await _pick_preferred_online_partner(app, device_id, preferred_id)
        if partner_info:
            puid, pid = partner_info
            partner_entry = app["online_devices"][_online_key(puid, pid)]
            partner_ws   = partner_entry["ws"]
            partner_role = partner_entry["role"]

            # Target tarafında accessibility kontrolü
            target_ws   = ws if role == "target" else partner_ws
            target_meta = app["ws_meta"].get(id(target_ws)) or {}
            if target_meta.get("accessibility_enabled") is False:
                err_msg = {
                    "type": MessageTypes.ERROR,
                    "code": "accessibility_required",
                    "message": "Hedef telefonda Erisilebilirlik kapali.",
                }
                await _send_json(ws, err_msg)
                await _send_json(partner_ws, err_msg)
                await _broadcast_presence_change(app, user_id, device_id)
                return

            # Session kur: controller ve target rolleriyle
            if role == "controller":
                ctrl_did, tgt_did = device_id, pid
                ctrl_uid, tgt_uid = user_id, puid
            else:
                ctrl_did, tgt_did = pid, device_id
                ctrl_uid, tgt_uid = puid, user_id

            session_code = f"__auto_{min(device_id, pid)}_{max(device_id, pid)}"
            app["sessions"][session_code] = {role: ws, partner_role: partner_ws}
            app["session_devices"][session_code] = {role: device_id, partner_role: pid}
            meta["peer_code"] = session_code
            meta["peer_role"] = role
            partner_meta = app["ws_meta"].get(id(partner_ws))
            if partner_meta:
                partner_meta["peer_code"] = session_code
                partner_meta["peer_role"] = partner_role

            ok = await _persist_pairing(app, ctrl_did, tgt_did)
            if not ok:
                logger.warning("Auto-pair: pairing kaydedilemedi %s -> %s", ctrl_did, tgt_did)

            await _send_json(ws, {
                "type": MessageTypes.AUTO_PAIRED,
                "your_role": role,
                "partner_device_id": pid,
            })
            await _send_json(partner_ws, {
                "type": MessageTypes.AUTO_PAIRED,
                "your_role": partner_role,
                "partner_device_id": device_id,
            })
            await _broadcast_presence_change(app, ctrl_uid, ctrl_did)
            if tgt_uid != ctrl_uid:
                await _broadcast_presence_change(app, tgt_uid, tgt_did)
            return

        if preferred_id:
            await _send_json(ws, {
                "type": MessageTypes.ERROR,
                "message": "Hedef cihaz bulunamadi veya cevrimici degil.",
            })

    await _broadcast_presence_change(app, user_id, device_id)


async def _handle_pair_confirm(
    app: web.Application, meta: dict, message: dict
) -> None:
    """Manuel pairing onayı: controller → target."""
    ctrl_did = message.get("my_device_id", "").strip()
    tgt_did  = message.get("paired_with", "").strip()
    user_id  = meta.get("user_id")
    if not (user_id and ctrl_did and tgt_did):
        return

    ok = await _persist_pairing(app, ctrl_did, tgt_did)
    if not ok:
        logger.warning("pair_confirm: pairing kaydedilemedi %s -> %s", ctrl_did, tgt_did)
        return

    await _broadcast_presence_change(app, user_id, ctrl_did)

    # Partner farklı kullanıcıysa ona da yayın yap
    tgt_info = await asyncio.to_thread(app["db"].get_device_info, tgt_did)
    if tgt_info:
        tgt_uid = int(tgt_info["user_id"])
        if tgt_uid != user_id:
            await _broadcast_presence_change(app, tgt_uid, tgt_did)
        else:
            await _send_device_ack(app, tgt_uid, tgt_did)


async def _handle_register_or_join(
    app: web.Application,
    ws: web.WebSocketResponse,
    meta: dict,
    message: dict,
) -> None:
    """
    Manuel session kurma.
    REGISTER → controller (bağlanan taraf)
    JOIN     → target (bağlanılan taraf: phone)
    """
    code = message.get("code", "").strip()
    # Eski API uyumluluğu: role gönderilmişse kullan, yoksa mesaj tipine göre belirle
    role = message.get("role") or (
        "controller" if message.get("type") == MessageTypes.REGISTER else "target"
    )
    if role not in {"controller", "target"}:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Gecersiz rol."})
        return
    if not code:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "code gerekli"})
        return

    # Kullanıcı bilgisi yoksa cihazdan çek
    if meta.get("user_id") is None:
        raw_did = (message.get("device_id") or "").strip() or meta.get("device_id")
        if not raw_did:
            await _send_json(ws, {"type": MessageTypes.ERROR, "message": "device_id gerekli"})
            return
        info = await asyncio.to_thread(app["db"].get_device_info, raw_did)
        if not info:
            await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Cihaz bulunamadi"})
            return
        meta["user_id"]   = int(info["user_id"])
        meta["device_id"] = str(info["device_id"])

    # Zaten auto-paired ise yoksay
    if str(meta.get("peer_code") or "").startswith("__auto_"):
        ack = MessageTypes.REGISTERED if message.get("type") == MessageTypes.REGISTER else MessageTypes.JOINED
        await _send_json(ws, {"type": ack, "code": code, "role": role, "ignored": True})
        return

    session = _session_entry(app, code)
    session[role] = ws
    device_id = _canon_device_id(
        str(message.get("device_id") or meta.get("device_id") or "")
    ) or str(meta.get("device_id") or "")
    app["session_devices"][code][role] = device_id
    meta["peer_code"] = code
    meta["peer_role"]  = role

    if role == "target":
        meta["accessibility_enabled"] = bool(message.get("accessibility_enabled", False))

    if meta.get("user_id") and device_id:
        meta["device_id"] = device_id
        online_key = _online_key(meta["user_id"], device_id)
        if online_key not in app["online_devices"]:
            app["online_devices"][online_key] = {
                "ws": ws, "role": role,
                "user_id": meta["user_id"], "device_id": device_id,
            }
            await asyncio.to_thread(app["db"].set_device_online, meta["user_id"], device_id, True)
            await _broadcast_presence_change(app, meta["user_id"], device_id)

    ack = MessageTypes.REGISTERED if message.get("type") == MessageTypes.REGISTER else MessageTypes.JOINED
    await _send_json(ws, {"type": ack, "code": code, "role": role})

    if "controller" in session and "target" in session:
        await _notify_paired(app, code)
    elif message.get("type") == MessageTypes.JOIN:
        await _send_json(ws, {"type": MessageTypes.WAITING, "message": "Diger cihaz baglanmayi bekliyor..."})


async def _resolve_peer_ws(
    app: web.Application, ws: web.WebSocketResponse, meta: dict
) -> web.WebSocketResponse | None:
    peer_code = meta.get("peer_code")
    peer_role = meta.get("peer_role")
    if not peer_code or not peer_role:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Not registered"})
        return None
    other_role = _opposite_role(peer_role)
    other_ws = app["sessions"].get(peer_code, {}).get(other_role)
    if not other_ws:
        await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Diger cihaz bagli degil"})
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
    await other_ws.send_str(
        raw_text if raw_text is not None else json.dumps(message, separators=(",", ":"))
    )


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


# ------------------------------------------------------------------ #
#  ANA WEBSOCKET HANDLER                                              #
# ------------------------------------------------------------------ #

async def websocket_handler(request: web.Request) -> web.StreamResponse:
    ws_probe = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024, heartbeat=20)
    if not ws_probe.can_prepare(request).ok:
        return web.Response(text="OK\n")

    ws = web.WebSocketResponse(max_msg_size=5 * 1024 * 1024, heartbeat=20)
    await ws.prepare(request)

    app  = request.app
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
                await _send_json(ws, {"type": MessageTypes.ERROR, "message": "Gecersiz JSON"})
                continue

            msg_type = message.get("type", "")
            if msg_type not in {MessageTypes.FRAME, MessageTypes.HEARTBEAT}:
                logger.info(
                    "[%s] device_id=%s code=%s role=%s",
                    msg_type,
                    message.get("device_id"),
                    message.get("code"),
                    message.get("role"),
                )

            if msg_type == MessageTypes.DEVICE_HELLO:
                await _handle_device_hello(app, ws, meta, message)

            elif msg_type == MessageTypes.DEVICE_LOGOUT:
                await _handle_device_logout(app, ws, meta, message)

            elif msg_type == MessageTypes.PAIR_CONFIRM:
                await _handle_pair_confirm(app, meta, message)

            elif msg_type in {MessageTypes.REGISTER, MessageTypes.JOIN}:
                await _handle_register_or_join(app, ws, meta, message)

            elif msg_type in {MessageTypes.REQUEST_PRESENCE, MessageTypes.HEARTBEAT}:
                device_id = meta.get("device_id")
                user_id   = meta.get("user_id")
                if device_id and user_id:
                    await _send_device_ack(app, int(user_id), str(device_id))
                if msg_type == MessageTypes.HEARTBEAT:
                    peer_ws = (
                        await _resolve_peer_ws(app, ws, meta)
                        if meta.get("peer_code") else None
                    )
                    if peer_ws:
                        await peer_ws.send_str(raw.data)

            elif msg_type in MessageTypes.RELAY_TYPES:
                await _relay_message(app, ws, meta, message, raw_text=raw.data)

            else:
                await _send_json(ws, {"type": MessageTypes.ERROR, "message": f"Bilinmeyen mesaj tipi: {msg_type}"})

    finally:
        device_id  = meta.get("device_id")
        user_id    = meta.get("user_id")
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
                other_role = _opposite_role(peer_role)
                other_ws   = session.get(other_role)
                if other_ws:
                    try:
                        await _send_json(other_ws, {
                            "type": MessageTypes.PEER_DISCONNECTED, "role": peer_role
                        })
                    except Exception:
                        pass
            if not session:
                app["sessions"].pop(peer_code, None)
                app["session_devices"].pop(peer_code, None)

        app["ws_meta"].pop(id(ws), None)
        if device_id and user_id and not meta.get("logout_notified"):
            await _broadcast_presence_change(app, user_id, device_id)

    return ws


# ------------------------------------------------------------------ #
#  HTTP ENDPOINT'LERİ                                                 #
# ------------------------------------------------------------------ #

async def auth_register(request: web.Request) -> web.Response:
    data = await _json(request)
    email      = (data.get("email") or data.get("username") or "").strip()
    password   = data.get("password", "")
    first_name = (data.get("first_name") or "").strip()
    last_name  = (data.get("last_name") or "").strip()
    phone      = (data.get("phone") or "").strip() or None

    success, message = await asyncio.to_thread(
        request.app["db"].register_user, email, password, first_name, last_name, phone
    )
    if not success:
        return web.json_response({"ok": False, "message": message}, status=400)

    auth_result = await asyncio.to_thread(request.app["db"].authenticate_user, email, password)
    if not auth_result:
        return web.json_response({"ok": False, "message": "Kayit sonrasi giris yapilamadi."}, status=500)
    user_id, username = auth_result

    device_type = data.get("device_type", "").strip()
    mac_address = _mac_from_body(data)
    resolved_device_id = ""
    if device_type in {"phone", "pc"}:
        if device_type == "phone" and not mac_address:
            return web.json_response(
                {"ok": False, "message": "Telefon kaydi icin mac_address gerekli."}, status=400
            )
        resolved_device_id = await _upsert_device_and_evict(
            request.app, user_id,
            data.get("device_id", "").strip(),
            device_type,
            data.get("device_name", "").strip(),
            mac_address,
        ) or ""
        if not resolved_device_id:
            return web.json_response({"ok": False, "message": "Cihaz kaydi guncellenemedi."}, status=500)

    token = issue_token(user_id, username)
    return web.json_response({
        "ok": True, "message": message, "token": token,
        "user": {
            "id": user_id, "username": username,
            "email": email.lower(),
            "device_id": resolved_device_id,
        },
    })


async def auth_login(request: web.Request) -> web.Response:
    data   = await _json(request)
    login  = (data.get("email") or data.get("username") or "").strip()
    result = await asyncio.to_thread(
        request.app["db"].authenticate_user, login, data.get("password", "")
    )
    if not result:
        return web.json_response({"ok": False, "message": "Kullanici adi veya sifre hatali."}, status=401)
    user_id, username = result

    device_type = data.get("device_type", "").strip()
    mac_address = _mac_from_body(data)
    resolved_device_id = ""
    if device_type in {"phone", "pc"}:
        if device_type == "phone" and not mac_address:
            return web.json_response(
                {"ok": False, "message": "Telefon girisi icin mac_address gerekli."}, status=400
            )
        resolved_device_id = await _upsert_device_and_evict(
            request.app, user_id,
            data.get("device_id", "").strip(),
            device_type,
            data.get("device_name", "").strip(),
            mac_address,
        ) or ""
        if not resolved_device_id:
            return web.json_response({"ok": False, "message": "Cihaz kaydi guncellenemedi."}, status=500)

    token = issue_token(user_id, username)
    return web.json_response({
        "ok": True, "token": token,
        "user": {
            "id": user_id, "username": username,
            "email": login.lower(),
            "device_id": resolved_device_id,
        },
    })


async def auth_me(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    profile = await asyncio.to_thread(
        request.app["db"].get_user_profile, user[0], request.query.get("device_id")
    )
    if not profile:
        return web.json_response({"ok": False, "message": "Kullanici bulunamadi."}, status=404)
    return web.json_response({"ok": True, "user": profile})


async def upsert_device(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    data = await _json(request)
    device_type = data.get("device_type", "").strip()
    mac_address = _mac_from_body(data)
    if device_type not in {"phone", "pc"}:
        return web.json_response({"ok": False, "message": "Gecersiz device_type."}, status=400)
    if device_type == "phone" and not mac_address:
        return web.json_response({"ok": False, "message": "Telefon icin mac_address gerekli."}, status=400)
    resolved = await _upsert_device_and_evict(
        request.app, user[0],
        data.get("device_id", "").strip(),
        device_type,
        data.get("device_name", "").strip(),
        mac_address,
    ) or ""
    if not resolved:
        return web.json_response({"ok": False, "message": "Cihaz kaydi guncellenemedi."}, status=500)
    return web.json_response({"ok": True, "device_id": resolved})


async def list_devices(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    devices = await asyncio.to_thread(request.app["db"].get_user_devices, user[0])
    return web.json_response({
        "ok": True,
        "devices": [_device_payload(d, request.app["online_devices"]) for d in devices],
    })


async def list_pairings(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    device_id = request.query.get("device_id", "").strip()
    if not device_id:
        return web.json_response({"ok": False, "message": "device_id gerekli."}, status=400)
    if not await asyncio.to_thread(request.app["db"].user_owns_device, user[0], device_id):
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)

    result = await asyncio.to_thread(request.app["db"].get_device_pairings, user[0], device_id)
    # get_device_pairings → {"controlling": [...], "controlled_by": [...]}
    all_devices = result.get("controlling", []) + result.get("controlled_by", [])
    return web.json_response({
        "ok": True,
        "pairings": [_device_payload(d, request.app["online_devices"]) for d in all_devices],
        "controlling":   [_device_payload(d, request.app["online_devices"]) for d in result.get("controlling", [])],
        "controlled_by": [_device_payload(d, request.app["online_devices"]) for d in result.get("controlled_by", [])],
    })


async def delete_pairing(request: web.Request) -> web.Response:
    user = await _require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    data = await _json(request)
    device_id         = data.get("device_id", "").strip()
    partner_device_id = data.get("partner_device_id", "").strip()
    if not device_id or not partner_device_id:
        return web.json_response({"ok": False, "message": "device_id ve partner_device_id gerekli."}, status=400)
    if not await asyncio.to_thread(request.app["db"].user_owns_device, user[0], device_id):
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)

    # Yön: bu cihaz controller mı target mı?
    # Her iki ihtimali de dene (kullanıcı hangi yönden silmek istediğini bilmeyebilir)
    ok = await asyncio.to_thread(
        request.app["db"].delete_pairing, user[0], device_id, partner_device_id
    )
    if not ok:
        # Ters yönü dene
        ok = await asyncio.to_thread(
            request.app["db"].delete_pairing, user[0], partner_device_id, device_id
        )
    if not ok:
        return web.json_response({"ok": False, "message": "Eslesme silinemedi."}, status=500)

    await _broadcast_presence_change(app=request.app, user_id=user[0], device_id=device_id)
    tgt_info = await asyncio.to_thread(request.app["db"].get_device_info, partner_device_id)
    if tgt_info:
        tgt_uid = int(tgt_info["user_id"])
        if tgt_uid != user[0]:
            await _broadcast_presence_change(request.app, tgt_uid, partner_device_id)
    return web.json_response({"ok": True})


async def on_cleanup(app: web.Application) -> None:
    app["db"].close()


# ------------------------------------------------------------------ #
#  UYGULAMA                                                           #
# ------------------------------------------------------------------ #

def create_app() -> web.Application:
    db = ServerDbClient()
    db.init_schema()

    app = web.Application()
    app["db"]             = db
    app["sessions"]       = {}
    app["session_devices"] = {}
    app["online_devices"] = {}
    app["ws_meta"]        = {}

    app.add_routes([
        web.get("/",                  websocket_handler),
        web.post("/auth/register",    auth_register),
        web.post("/auth/login",       auth_login),
        web.get("/auth/me",           auth_me),
        web.post("/devices/upsert",   upsert_device),
        web.get("/devices",           list_devices),
        web.get("/pairings",          list_pairings),
        web.post("/pairings/delete",  delete_pairing),
    ])
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=ServerConfig.HOST, port=ServerConfig.PORT, access_log=None)