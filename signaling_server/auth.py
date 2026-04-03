import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any


def _secret() -> bytes:
    return os.environ.get("AUTH_SECRET", "remote-phone-control-dev-secret").encode("utf-8")


def _ttl_seconds() -> int:
    raw = (os.environ.get("AUTH_TOKEN_TTL_SEC") or "86400").strip()
    try:
        ttl = int(raw)
    except ValueError:
        ttl = 86400
    return max(300, ttl)


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def issue_token(user_id: int, username: str) -> str:
    issued_at = int(time.time())
    payload = {
        "user_id": int(user_id),
        "username": str(username),
        "iat": issued_at,
        "exp": issued_at + _ttl_seconds(),
    }
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_part = _b64encode(payload_raw)
    signature = hmac.new(_secret(), payload_part.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_part}.{_b64encode(signature)}"


def parse_token(token: str) -> dict[str, Any] | None:
    try:
        payload_part, signature_part = token.split(".", 1)
        expected = hmac.new(_secret(), payload_part.encode("ascii"), hashlib.sha256).digest()
        actual = _b64decode(signature_part)
        if not hmac.compare_digest(expected, actual):
            return None

        payload = json.loads(_b64decode(payload_part).decode("utf-8"))
        user_id = payload.get("user_id")
        username = payload.get("username")
        exp = payload.get("exp")
        now = int(time.time())

        if not isinstance(user_id, int) or not str(username or "").strip():
            return None
        if not isinstance(exp, int) or exp < now:
            return None
        return payload
    except Exception:
        return None
