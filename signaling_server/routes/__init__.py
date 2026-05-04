from __future__ import annotations

from aiohttp import web


def register_routes(app: web.Application) -> None:
    """Register HTTP and WebSocket routes without changing public paths."""

    from signaling_server import server

    app.add_routes(
        [
            web.get("/health", server.health_check),
            web.get("/", server.websocket_handler),
            web.post("/auth/register", server.auth_register),
            web.post("/auth/login", server.auth_login),
            web.get("/auth/me", server.auth_me),
            web.post("/auth/profile", server.auth_profile_update),
            web.post("/devices/upsert", server.upsert_device),
            web.get("/devices", server.list_devices),
            web.get("/devices/phone-bundle", server.desktop_phone_bundle),
            web.get("/recent-devices", server.list_recent_devices),
            web.get("/pairings", server.list_pairings),
            web.post("/pairings/delete", server.delete_pairing),
        ]
    )


__all__ = ["register_routes"]
