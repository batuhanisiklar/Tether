from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiohttp import web


@dataclass
class SessionRegistry:
    sessions: dict[str, dict[str, web.WebSocketResponse]] = field(default_factory=dict)
    session_devices: dict[str, dict[str, str]] = field(default_factory=dict)
    online_devices: dict[str, dict[str, Any]] = field(default_factory=dict)
    ws_meta: dict[web.WebSocketResponse, dict[str, Any]] = field(default_factory=dict)

    def attach(self, app: web.Application) -> None:
        app["registry"] = self
        app["sessions"] = self.sessions
        app["session_devices"] = self.session_devices
        app["online_devices"] = self.online_devices
        app["ws_meta"] = self.ws_meta


__all__ = ["SessionRegistry"]
