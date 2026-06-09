"""
HTTP device endpoint'leri — upsert, list, recent, phone-bundle.
"""
from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from signaling_server.helpers import device_payload, normalize_device_id, parse_json_body
from signaling_server.ws.auth import require_user
from signaling_server.ws.presence import register_or_reuse_device


async def upsert_device(request: web.Request) -> web.Response:
    user = await require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user

    data = await parse_json_body(request)
    device_id = str(data.get("device_id") or "")
    device_type = str(data.get("device_type") or "")
    device_name = str(data.get("device_name") or "")
    mac_address = str(data.get("mac_address") or data.get("macAddress") or "")
    if device_type not in {"phone", "pc"}:
        return web.json_response({"ok": False, "message": "device_type gecersiz."}, status=400)

    resolved_device_id, err = await register_or_reuse_device(
        request.app,
        int(user_id),
        device_id,
        device_type,
        device_name,
        mac_address,
    )
    if not resolved_device_id:
        return web.json_response({"ok": False, "message": err or "Cihaz kaydi yapilamadi."}, status=400)
    return web.json_response({"ok": True, "device_id": resolved_device_id, "address": resolved_device_id})


async def list_devices(request: web.Request) -> web.Response:
    user = await require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user
    devices = await asyncio.to_thread(request.app["db"].get_devices_for_user, int(user_id))
    owner_cache: dict[int, dict[str, Any]] = {}
    payload = [
        device_payload(device, request.app["online_devices"], db=request.app["db"], owner_cache=owner_cache)
        for device in devices
    ]
    return web.json_response({"ok": True, "devices": payload})


async def list_recent_devices(request: web.Request) -> web.Response:
    user = await require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user
    device_type = str(request.query.get("device_type") or "").strip()
    if device_type not in {"", "phone", "pc"}:
        return web.json_response({"ok": False, "message": "device_type gecersiz."}, status=400)

    user_devices = await asyncio.to_thread(request.app["db"].get_devices_for_user, int(user_id))
    partner_ids: set[str] = set()
    for dev in user_devices:
        own_id = normalize_device_id(str(dev.get("device_id") or ""))
        if not own_id:
            continue
        as_controller = await asyncio.to_thread(request.app["db"].get_connected_devices_as_controller, own_id)
        as_target = await asyncio.to_thread(request.app["db"].get_connected_devices_as_target, own_id)
        for raw_partner_id in list(as_controller) + list(as_target):
            normalized_partner_id = normalize_device_id(str(raw_partner_id))
            if normalized_partner_id:
                partner_ids.add(normalized_partner_id)

    devices_payload: list[dict[str, Any]] = []
    owner_cache: dict[int, dict[str, Any]] = {}
    for partner_id in partner_ids:
        partner_device = await asyncio.to_thread(request.app["db"].get_device_by_id, partner_id)
        if not partner_device:
            continue
        if device_type and str(partner_device.get("device_type") or "") != device_type:
            continue
        devices_payload.append(
            device_payload(
                partner_device,
                request.app["online_devices"],
                db=request.app["db"],
                owner_cache=owner_cache,
            )
        )
    return web.json_response({"ok": True, "devices": devices_payload})


async def desktop_phone_bundle(request: web.Request) -> web.Response:
    """
    Masaustu istemci: /devices + /recent-devices?phone + /pairings tek round-trip.
    """
    user = await require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _ = user
    pc_id = normalize_device_id(request.query.get("device_id") or "")
    if not pc_id:
        return web.json_response({"ok": False, "message": "device_id gerekli."}, status=400)

    own = await asyncio.to_thread(request.app["db"].get_device_by_id, pc_id)
    if not own or int(own.get("user_id")) != int(user_id):
        return web.json_response({"ok": False, "message": "Bu cihaza erisim yetkiniz yok."}, status=403)

    online = request.app["online_devices"]
    owner_cache: dict[int, dict[str, Any]] = {}

    partner_ids_raw = await asyncio.to_thread(request.app["db"].get_connected_devices_as_controller, pc_id)
    partner_ids_raw += await asyncio.to_thread(request.app["db"].get_connected_devices_as_target, pc_id)
    seen_pair: set[str] = set()
    pairings_payload: list[dict[str, Any]] = []
    for raw_partner_id in partner_ids_raw:
        partner_id = normalize_device_id(str(raw_partner_id))
        if not partner_id or partner_id in seen_pair:
            continue
        seen_pair.add(partner_id)
        partner_device = await asyncio.to_thread(request.app["db"].get_device_by_id, partner_id)
        if not partner_device:
            continue
        pairings_payload.append(device_payload(partner_device, online, db=request.app["db"], owner_cache=owner_cache))

    recent_payload: list[dict[str, Any]] = []
    for partner_id in seen_pair:
        partner_device = await asyncio.to_thread(request.app["db"].get_device_by_id, partner_id)
        if not partner_device:
            continue
        if str(partner_device.get("device_type") or "") != "phone":
            continue
        recent_payload.append(device_payload(partner_device, online, db=request.app["db"], owner_cache=owner_cache))

    return web.json_response(
        {
            "ok": True,
            "devices": [],
            "recent_devices": recent_payload,
            "pairings": pairings_payload,
        }
    )
