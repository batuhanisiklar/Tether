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

    # Persistent device identity & auto-pairing
    DEVICE_HELLO: str = "device_hello"    # Client → Server: announce device_id + role
    DEVICE_ACK: str = "device_ack"        # Server → Client: acknowledged, pairing status
    AUTO_PAIRED: str = "auto_paired"      # Server → Both: paired partner came online
    PAIR_CONFIRM: str = "pair_confirm"    # Client → Server: confirm pairing after code-join
    PAIRED_DEVICES: str = "paired_devices"  # Server → Client: list of known paired devices
    REQUEST_PRESENCE: str = "request_presence"  # Client → Server: refresh device_ack

    RELAY_TYPES: Set[str] = frozenset({
        COMMAND, STREAM_INFO, RELAY, FRAME,
    })
