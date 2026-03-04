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

sessions: dict = {}


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
            logger.info(f"[{msg_type}] code={msg.get('code')} role={msg.get('role')}")

            if msg_type in (MessageTypes.REGISTER, MessageTypes.JOIN):
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
