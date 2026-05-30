"""
HTTP auth endpoint'leri â€” register, login, me, profile update.
"""
from __future__ import annotations

import asyncio
from typing import Any

from aiohttp import web

from signaling_server.auth import issue_token
from signaling_server.helpers import normalize_device_id, parse_json_body, username_from_email
from signaling_server.ws.auth import require_user
from signaling_server.ws.presence import register_or_reuse_device


async def auth_register(request: web.Request) -> web.Response:
    data = await parse_json_body(request)
    email = str(data.get("email") or data.get("username") or "").strip().lower()
    password = str(data.get("password") or "")
    first_name = str(data.get("first_name") or "").strip()
    last_name = str(data.get("last_name") or "").strip()
    phone = str(data.get("phone") or "").strip()
    if not email or not password:
        return web.json_response({"ok": False, "message": "email ve password gerekli."}, status=400)
    if phone:
        phone_digits = "".join(ch for ch in phone if ch.isdigit())
        if len(phone_digits) != 11:
            return web.json_response({"ok": False, "message": "Telefon numarasÄ± 11 hane olmalÄ±dÄ±r."}, status=400)
        phone = phone_digits

    user_id = await asyncio.to_thread(
        request.app["db"].register_user,
        email,
        password,
        first_name,
        last_name,
        phone or None,
    )
    if user_id is None:
        return web.json_response({"ok": False, "message": "Bu e-posta zaten kayitli."}, status=400)

    device_id = str(data.get("device_id") or "")
    device_type = str(data.get("device_type") or "")
    device_name = str(data.get("device_name") or "")
    mac_address = str(data.get("mac_address") or data.get("macAddress") or "")
    resolved_device_id = ""
    if device_type in {"phone", "pc"}:
        resolved_device_id, device_err = await register_or_reuse_device(
            request.app,
            int(user_id),
            device_id,
            device_type,
            device_name,
            mac_address,
        )
        if not resolved_device_id:
            await asyncio.to_thread(request.app["db"].delete_user, int(user_id))
            return web.json_response({"ok": False, "message": device_err or "Cihaz kaydi yapilamadi."}, status=400)

    username = username_from_email(email)
    token = issue_token(int(user_id), username)
    return web.json_response(
        {
            "ok": True,
            "token": token,
            "user": {
                "id": int(user_id),
                "username": username,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "phone": phone or "",
                "device_id": resolved_device_id,
                "address": resolved_device_id,
            },
        }
    )


async def auth_login(request: web.Request) -> web.Response:
    data = await parse_json_body(request)
    email = str(data.get("email") or data.get("username") or "").strip().lower()
    password = str(data.get("password") or "")
    user_id = await asyncio.to_thread(request.app["db"].authenticate_user, email, password)
    if user_id is None:
        return web.json_response({"ok": False, "message": "KullanÄ±cÄ± adÄ± veya ÅŸifre hatalÄ±."}, status=401)

    device_id = str(data.get("device_id") or "")
    device_type = str(data.get("device_type") or "")
    device_name = str(data.get("device_name") or "")
    mac_address = str(data.get("mac_address") or data.get("macAddress") or "")
    resolved_device_id = ""
    if device_type in {"phone", "pc"}:
        resolved_device_id, device_err = await register_or_reuse_device(
            request.app,
            int(user_id),
            device_id,
            device_type,
            device_name,
            mac_address,
        )
        if not resolved_device_id:
            return web.json_response({"ok": False, "message": device_err or "Cihaz kaydi yapilamadi."}, status=400)

    username = username_from_email(email)
    token = issue_token(int(user_id), username)
    profile = await asyncio.to_thread(request.app["db"].get_user_by_id, int(user_id))
    return web.json_response(
        {
            "ok": True,
            "token": token,
            "user": {
                "id": int(user_id),
                "username": username,
                "email": email,
                "first_name": str((profile or {}).get("first_name") or ""),
                "last_name": str((profile or {}).get("last_name") or ""),
                "phone": str((profile or {}).get("phone") or ""),
                "device_id": resolved_device_id,
                "address": resolved_device_id,
            },
        }
    )


async def auth_me(request: web.Request) -> web.Response:
    user = await require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, username = user
    profile = await asyncio.to_thread(request.app["db"].get_user_by_id, int(user_id))
    if not profile:
        return web.json_response({"ok": False, "message": "Kullanici bulunamadi."}, status=404)

    device_id = normalize_device_id(str(request.query.get("device_id") or ""))
    if device_id:
        device = await asyncio.to_thread(request.app["db"].get_device_by_id, device_id)
        address = device_id if device and int(device.get("user_id")) == int(user_id) else ""
    else:
        address = ""
    return web.json_response(
        {
            "ok": True,
            "user": {
                "id": int(profile["user_id"]),
                "username": username,
                "email": str(profile.get("email") or ""),
                "first_name": str(profile.get("first_name") or ""),
                "last_name": str(profile.get("last_name") or ""),
                "phone": str(profile.get("phone") or ""),
                "address": address,
            },
        }
    )


async def auth_profile_update(request: web.Request) -> web.Response:
    user = await require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _old_username = user

    data = await parse_json_body(request)
    email = data.get("email")
    phone = data.get("phone")
    old_pwd = data.get("old_password")
    pwd1 = data.get("password")
    pwd2 = data.get("password2")

    # email varsa basit doÄŸrulama
    if email is not None:
        em = str(email).strip().lower()
        if not em or "@" not in em or len(em) < 5:
            return web.json_response({"ok": False, "message": "GeÃ§erli bir e-posta girin."}, status=400)
        email = em

    if phone is not None:
        phone_digits = "".join(ch for ch in str(phone).strip() if ch.isdigit())
        if phone_digits and len(phone_digits) != 11:
            return web.json_response({"ok": False, "message": "Telefon numarasÄ± 11 hane olmalÄ±dÄ±r."}, status=400)
        phone = phone_digits

    new_password: str | None = None
    if pwd1 is not None or pwd2 is not None:
        p1 = str(pwd1 or "")
        p2 = str(pwd2 or "")
        op = str(old_pwd or "")
        if not op:
            return web.json_response({"ok": False, "message": "Mevcut ÅŸifre gerekli."}, status=400)
        if not p1 or not p2:
            return web.json_response({"ok": False, "message": "Åžifre iki kere girilmelidir."}, status=400)
        if p1 != p2:
            return web.json_response({"ok": False, "message": "Åžifreler eÅŸleÅŸmiyor."}, status=400)
        if p1 == op:
            return web.json_response({"ok": False, "message": "Mevcut şifre ile yeni şifre aynı olamaz."}, status=400)
        if len(p1) < 6:
            return web.json_response({"ok": False, "message": "Åžifre en az 6 karakter olmalÄ±."}, status=400)
        new_password = p1

    ok, err = await asyncio.to_thread(
        request.app["db"].update_user_profile,
        int(user_id),
        email=email if email is not None else None,
        phone=phone if phone is not None else None,
        new_password=new_password,
        old_password=str(old_pwd or "").strip() if (pwd1 is not None or pwd2 is not None) else None,
    )
    if not ok:
        return web.json_response({"ok": False, "message": err or "Profil gÃ¼ncellenemedi."}, status=400)

    profile = await asyncio.to_thread(request.app["db"].get_user_by_id, int(user_id))
    if not profile:
        return web.json_response({"ok": False, "message": "KullanÄ±cÄ± bulunamadÄ±."}, status=404)

    new_email = str(profile.get("email") or "").strip().lower()
    new_username = username_from_email(new_email)
    token = issue_token(int(user_id), new_username)
    return web.json_response(
        {
            "ok": True,
            "token": token,
            "user": {
                "id": int(profile["user_id"]),
                "username": new_username,
                "email": new_email,
                "first_name": str(profile.get("first_name") or ""),
                "last_name": str(profile.get("last_name") or ""),
                "phone": str(profile.get("phone") or ""),
            },
        }
    )


async def auth_delete(request: web.Request) -> web.Response:
    user = await require_user(request)
    if not user:
        return web.json_response({"ok": False, "message": "Yetkisiz istek."}, status=401)
    user_id, _username = user

    data = await parse_json_body(request)
    email = str(data.get("email") or "").strip().lower()
    password = str(data.get("password") or "")
    if not email or not password:
        return web.json_response({"ok": False, "message": "E-posta ve ÅŸifre gereklidir."}, status=400)

    profile = await asyncio.to_thread(request.app["db"].get_user_by_id, int(user_id))
    if not profile:
        return web.json_response({"ok": False, "message": "KullanÄ±cÄ± bulunamadÄ±."}, status=404)

    profile_email = str(profile.get("email") or "").strip().lower()
    if profile_email != email:
        return web.json_response({"ok": False, "message": "E-posta eÅŸleÅŸmiyor."}, status=400)

    verified_user_id = await asyncio.to_thread(request.app["db"].authenticate_user, email, password)
    if verified_user_id is None or int(verified_user_id) != int(user_id):
        return web.json_response({"ok": False, "message": "E-posta veya ÅŸifre hatalÄ±."}, status=401)

    deleted = await asyncio.to_thread(request.app["db"].delete_user, int(user_id))
    if not deleted:
        return web.json_response({"ok": False, "message": "Hesap silinemedi."}, status=500)

    return web.json_response({"ok": True, "message": "Hesap silindi."})

