import os
from dataclasses import dataclass
from typing import Set


@dataclass(frozen=True)
class ServerConfig:
    HOST: str = "0.0.0.0"
    PORT: int = int(os.environ.get("PORT", "8765"))
    LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(message)s"


class MessageTypes:
    REGISTER: str = "register"
    JOIN: str = "join"
    REGISTERED: str = "registered"
    JOINED: str = "joined"
    WAITING: str = "waiting"
    PAIR_REQUEST: str = "pair_request"
    PAIRED: str = "paired"
    PEER_DISCONNECTED: str = "peer_disconnected"
    ERROR: str = "error"
    COMMAND: str = "command"
    STREAM_INFO: str = "stream_info"
    HEARTBEAT: str = "heartbeat"
    RELAY: str = "relay"
    FRAME: str = "frame"

    DEVICE_HELLO: str = "device_hello"
    DEVICE_ACK: str = "device_ack"
    PAIR_CONFIRM: str = "pair_confirm"
    PAIRED_DEVICES: str = "paired_devices"
    REQUEST_PRESENCE: str = "request_presence"
    DEVICE_LOGOUT: str = "device_logout"

    SESSION_PING: str = "session_ping"
    SESSION_PONG: str = "session_pong"

    RELAY_TYPES: Set[str] = frozenset({
        COMMAND, STREAM_INFO, RELAY, FRAME, SESSION_PING, SESSION_PONG,
    })
