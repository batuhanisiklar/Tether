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
    PAIRED: str = "paired"
    PEER_DISCONNECTED: str = "peer_disconnected"
    ERROR: str = "error"
    COMMAND: str = "command"
    STREAM_INFO: str = "stream_info"
    HEARTBEAT: str = "heartbeat"
    RELAY: str = "relay"
    FRAME: str = "frame"

    RELAY_TYPES: Set[str] = frozenset({
        COMMAND, STREAM_INFO, HEARTBEAT, RELAY, FRAME,
    })
