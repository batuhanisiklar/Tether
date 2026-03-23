import asyncio
import json
import logging
import sys
import os
import http
import signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websockets

from signaling_server.config import ServerConfig, MessageTypes

logging.basicConfig(
    level=logging.INFO,
    format=ServerConfig.LOG_FORMAT,
)
logger = logging.getLogger(__name__)

logging.getLogger("websockets.server").setLevel(logging.CRITICAL)

# ── Session-based pairing (6-digit code flow — unchanged) ─────────────────────
sessions: dict = {}

# ── Persistent device registry ────────────────────────────────────────────────
# device_id → websocket (currently online devices)
online_devices: dict[str, object] = {}

# device_id → {"role": "phone"|"pc", "paired_with": device_id | None}
device_registry: dict[str, dict] = {}

# pairing table: device_id → partner device_id  (bidirectional)
pairings: dict[str, str] = {}


async def process_request(connection, request):
    if request.path == "/":
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None
        return connection.respond(http.HTTPStatus.OK, "OK\n")
    return None


async def send_json(ws, data: dict):
    await ws.send(json.dumps(data))


async def handler(ws):
    peer_code = None
    peer_role = None
    peer_device_id = None   # persistent device identity

    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                preview = str(raw)[:100]
                logger.warning(f"Invalid JSON received. Preview: {preview}...")
                await send_json(ws, {"type": MessageTypes.ERROR, "message": "Invalid JSON payload"})
                continue

            msg_type = msg.get("type", "")
            if msg_type != MessageTypes.FRAME:
                logger.info(f"[{msg_type}] device_id={msg.get('device_id')} code={msg.get('code')} role={msg.get('role')}")

            # ── DEVICE HELLO ───────────────────────────────────────────────────
            if msg_type == MessageTypes.DEVICE_HELLO:
                device_id = msg.get("device_id", "").strip()
                role = msg.get("role", "")
                if not device_id or role not in ("phone", "pc"):
                    await send_json(ws, {"type": MessageTypes.ERROR, "message": "device_id and role required"})
                    continue

                peer_device_id = device_id

                # Register / update online presence
                online_devices[device_id] = ws
                if device_id not in device_registry:
                    device_registry[device_id] = {"role": role, "paired_with": None}
                else:
                    device_registry[device_id]["role"] = role

                # Do we already have a pairing?
                partner_id = pairings.get(device_id)
                partner_online = partner_id and partner_id in online_devices

                if partner_online:
                    partner_ws = online_devices[partner_id]
                    partner_role = device_registry[partner_id]["role"]
                    logger.info(f"✅ Auto-paired: {device_id}({role}) <-> {partner_id}({partner_role})")

                    # Feed them into a fresh session so relay works
                    session_code = f"__auto_{device_id}_{partner_id}"
                    sessions[session_code] = {role: ws, partner_role: partner_ws}
                    peer_code = session_code
                    peer_role = role

                    partner_meta = _get_handler_meta(partner_ws)
                    if partner_meta:
                        partner_meta["peer_code"] = session_code
                        partner_meta["peer_role"] = partner_role

                    await send_json(ws, {
                        "type": MessageTypes.AUTO_PAIRED,
                        "your_role": role,
                        "partner_device_id": partner_id,
                    })
                    await send_json(partner_ws, {
                        "type": MessageTypes.AUTO_PAIRED,
                        "your_role": partner_role,
                        "partner_device_id": device_id,
                    })
                else:
                    await send_json(ws, {
                        "type": MessageTypes.DEVICE_ACK,
                        "device_id": device_id,
                        "paired_with": partner_id,
                        "partner_online": False,
                    })
                    logger.info(f"Device hello: {device_id} ({role}), partner={'none' if not partner_id else partner_id + ' (offline)'}")

            # ── PAIR CONFIRM ────────────────────────────────────────────────────
            elif msg_type == MessageTypes.PAIR_CONFIRM:
                my_device_id   = msg.get("my_device_id", "").strip()
                peer_device_id_confirm = msg.get("paired_with", "").strip()
                if my_device_id and peer_device_id_confirm:
                    pairings[my_device_id]           = peer_device_id_confirm
                    pairings[peer_device_id_confirm] = my_device_id
                    if my_device_id in device_registry:
                        device_registry[my_device_id]["paired_with"] = peer_device_id_confirm
                    if peer_device_id_confirm in device_registry:
                        device_registry[peer_device_id_confirm]["paired_with"] = my_device_id
                    logger.info(f"Pairing saved: {my_device_id} <-> {peer_device_id_confirm}")
                    if peer_device_id is None:
                        peer_device_id = my_device_id

            # ── REGISTER / JOIN (6-digit code flow — unchanged) ────────────────
            elif msg_type in (MessageTypes.REGISTER, MessageTypes.JOIN):
                code = msg.get("code", "").strip()
                role = msg.get("role", "phone" if msg_type == MessageTypes.REGISTER else "pc")

                if not code:
                    await send_json(ws, {"type": MessageTypes.ERROR, "message": "code missing"})
                    continue

                if code not in sessions:
                    sessions[code] = {}

                sessions[code][role] = ws
                peer_code = code
                peer_role = role

                ack = MessageTypes.REGISTERED if msg_type == MessageTypes.REGISTER else MessageTypes.JOINED
                await send_json(ws, {"type": ack, "code": code, "role": role})
                logger.info(f"{ack}: code={code}, role={role}")

                s = sessions.get(code, {})
                if "phone" in s and "pc" in s:
                    await _notify_paired(code, s)
                elif msg_type == MessageTypes.JOIN:
                    await send_json(ws, {
                        "type": MessageTypes.WAITING,
                        "message": "Telefon bağlanmayı bekliyor..."
                    })

            # ── RELAY (unchanged) ───────────────────────────────────────────────
            elif msg_type in MessageTypes.RELAY_TYPES:
                if not peer_code or not peer_role:
                    await send_json(ws, {"type": MessageTypes.ERROR, "message": "Not registered"})
                    continue

                s = sessions.get(peer_code, {})
                other_role = "pc" if peer_role == "phone" else "phone"
                other_ws = s.get(other_role)

                if other_ws:
                    try:
                        await other_ws.send(json.dumps(msg))
                    except Exception:
                        await send_json(ws, {
                            "type": MessageTypes.ERROR,
                            "message": "Karşı taraf bağlantısı koptu"
                        })
                else:
                    await send_json(ws, {
                        "type": MessageTypes.ERROR,
                        "message": f"{other_role} bağlı değil"
                    })

            else:
                await send_json(ws, {"type": MessageTypes.ERROR, "message": f"Unknown: {msg_type}"})

    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"Connection closed: code={peer_code}, role={peer_role} ({e})")
    except Exception as e:
        logger.warning(f"Handler error: {e}")
    finally:
        # Clean up online_devices
        if peer_device_id and online_devices.get(peer_device_id) is ws:
            del online_devices[peer_device_id]
            logger.info(f"Device offline: {peer_device_id}")

        if peer_code and peer_role:
            s = sessions.get(peer_code, {})
            if s.get(peer_role) is ws:
                del s[peer_role]
                logger.info(f"Removed: code={peer_code}, role={peer_role}")

                other_role = "pc" if peer_role == "phone" else "phone"
                other_ws = s.get(other_role)
                if other_ws:
                    try:
                        await send_json(other_ws, {
                            "type": MessageTypes.PEER_DISCONNECTED,
                            "role": peer_role
                        })
                    except Exception:
                        pass

            if not s:
                sessions.pop(peer_code, None)


# ── Handler meta — needed so auto-pair can update partner handler state ────────
# Since Python coroutines share the peer_code/peer_role as locals, we can't
# mutate them from outside. Instead we track a shared mutable dict per ws.
_ws_meta: dict = {}   # ws → {"peer_code": ..., "peer_role": ...}


def _get_handler_meta(ws):
    return _ws_meta.get(id(ws))


async def _notify_paired(code: str, s: dict):
    logger.info(f"✅ Paired! code={code}")
    for role, ws in s.items():
        try:
            await send_json(ws, {"type": MessageTypes.PAIRED, "code": code, "your_role": role})
        except Exception:
            pass


async def main():
    host = ServerConfig.HOST
    port = ServerConfig.PORT
    logger.info(f"Signaling server starting on ws://{host}:{port}")

    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Shutdown signal received. Closing server...")
        stop_event.set()

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, signal_handler)
    except NotImplementedError:
        signal.signal(signal.SIGINT, lambda s, f: signal_handler())
        signal.signal(signal.SIGTERM, lambda s, f: signal_handler())


    async with websockets.serve(
        handler,
        host,
        port,
        process_request=process_request,
        ping_interval=20,
        ping_timeout=20,
        max_size=5 * 1024 * 1024
    ) as server:
        logger.info(f"✅ Server listening on ws://{host}:{port}")

        await stop_event.wait()

    logger.info("Server completely shut down.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
