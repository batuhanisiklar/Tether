"""
HTTP pairing endpoint'leri — list, delete.
"""
from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from signaling_server.helpers import device_payload, normalize_device_id, parse_json_body
from signaling_server.ws.auth import require_user
from signaling_server.ws.presence import broadcast_presence_for_devices


async def list_pairings(request: web.Request) -> web.Response:
    user = await require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user
    device_id = normalize_device_id(request.query.get("device_id"))
    if not device_id:
        return web.json_response({"ok": False, "message": "device_id gerekli."}, status=400)

    device = await asyncio.to_thread(request.app["db"].get_device_by_id, device_id)
    if not device or int(device.get("user_id")) != int(user_id):
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)

    partner_ids_raw = await asyncio.to_thread(request.app["db"].get_connected_devices_as_controller, device_id)
    partner_ids_raw += await asyncio.to_thread(request.app["db"].get_connected_devices_as_target, device_id)

    seen: set[str] = set()
    pairings_payload: list[dict[str, Any]] = []
    owner_cache: dict[int, dict[str, Any]] = {}
    for raw_partner_id in partner_ids_raw:
        partner_id = normalize_device_id(str(raw_partner_id))
        if not partner_id or partner_id in seen:
            continue
        seen.add(partner_id)
        partner_device = await asyncio.to_thread(request.app["db"].get_device_by_id, partner_id)
        if not partner_device:
            continue
        pairings_payload.append(
            device_payload(
                partner_device,
                request.app["online_devices"],
                db=request.app["db"],
                owner_cache=owner_cache,
            )
        )
    return web.json_response({"ok": True, "pairings": pairings_payload})


async def delete_pairing(request: web.Request) -> web.Response:
    user = await require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user

    data = await parse_json_body(request)
    device_id = normalize_device_id(str(data.get("device_id") or ""))
    partner_device_id = normalize_device_id(str(data.get("partner_device_id") or ""))
    if not device_id or not partner_device_id:
        return web.json_response({"ok": False, "message": "device_id ve partner_device_id gerekli."}, status=400)

    own_device = await asyncio.to_thread(request.app["db"].get_device_by_id, device_id)
    if not own_device or int(own_device.get("user_id")) != int(user_id):
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)

    # Tek yönlü kayıt: PC (controller) → telefon (target)
    deleted = await asyncio.to_thread(request.app["db"].delete_connection, device_id, partner_device_id)
    if not deleted:
        deleted = await asyncio.to_thread(request.app["db"].delete_connection, partner_device_id, device_id)
    if not deleted:
        return web.json_response({"ok": False, "message": "Eslesme silinemedi."}, status=500)

    await broadcast_presence_for_devices(request.app, device_id, partner_device_id)
    return web.json_response({"ok": True})
