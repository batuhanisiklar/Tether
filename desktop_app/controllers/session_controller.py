from __future__ import annotations


class SessionController:
    def __init__(self) -> None:
        self.mode = "idle"
        self.reconnect_session_code: str | None = None
        self.manual_disconnect = False

    def mark_presence(self) -> None:
        self.mode = "presence"
        self.reconnect_session_code = None

    def mark_session(self, code: str | None) -> None:
        self.mode = "session"
        self.reconnect_session_code = code

    def mark_manual_disconnect(self) -> None:
        self.manual_disconnect = True
        self.mark_presence()
