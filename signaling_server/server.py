"""
Signaling Server — Application factory ve startup.
"""
import logging
import os
import sys
    
from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from signaling_server.auth import ensure_auth_secret_configured
from signaling_server.config import ServerConfig
from signaling_server.db_client import ServerDbClient
from signaling_server.api.auth import auth_delete, auth_login, auth_me, auth_profile_update, auth_register
from signaling_server.api.devices import desktop_phone_bundle, list_devices, list_recent_devices, upsert_device
from signaling_server.api.pairings import delete_pairing, list_pairings
from signaling_server.ws.handler import websocket_handler

logging.basicConfig(level=logging.INFO, format=ServerConfig.LOG_FORMAT)
logger = logging.getLogger(__name__)


async def health_check(_request: web.Request) -> web.Response:
    """Yuk dengeleyici / istemci: HTTP katmaninin ayakta oldugunu dogrular (DB sart degil)."""
    return web.json_response({"ok": True, "service": "tether-signaling"})


async def on_cleanup(app: web.Application) -> None:
    db = app.get("db")
    if db:
        db.close()


def create_app() -> web.Application:
    ensure_auth_secret_configured()
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
            web.get("/health", health_check),
            web.get("/", websocket_handler),
            web.post("/auth/register", auth_register),
            web.post("/auth/login", auth_login),
            web.get("/auth/me", auth_me),
            web.post("/auth/profile", auth_profile_update),
            web.post("/auth/delete", auth_delete),
            web.post("/devices/upsert", upsert_device),
            web.get("/devices", list_devices),
            web.get("/devices/phone-bundle", desktop_phone_bundle),
            web.get("/recent-devices", list_recent_devices),
            web.get("/pairings", list_pairings),
            web.post("/pairings/delete", delete_pairing),
        ]
    )
    app.on_cleanup.append(on_cleanup)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=ServerConfig.HOST, port=ServerConfig.PORT, access_log=None)
