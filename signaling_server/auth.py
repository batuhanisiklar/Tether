import base64
import hashlib
import hmac
import json
import os
import time

def _secret() -> bytes:
    return os.environ.get("AUTH_SECRET", "remote-phone-control-dev-secret").encode("utf-8")

def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

def _b64decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))

def issue_token(user_id: int, username: str) -> str:
    """
    Kullanıcıya ait (user_id, username) için bir JWT-benzeri imzalı token üretir.
    """
    payload = {
        "user_id": user_id,
        "username": username,
        "iat": int(time.time()),
    }
    # json.dumps(..., sort_keys=True) ile payload'ı düzenli sırada stringleştiriyoruz.
    payload_raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64encode(payload_raw)
    signature = hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    signature_b64 = _b64encode(signature)
    token = f"{payload_b64}.{signature_b64}"
    return token

def parse_token(token: str):
    """
    Verilen token'ı doğrular ve payload'ı çözümler. Yetkisiz veya bozuksa None döner.
    Dönen değer örn: {"user_id": 3, "username": "Hasan", "iat": 1716344846}
    """
    try:
        payload_b64, signature_b64 = token.split(".", 1)
        expected_sig = hmac.new(_secret(), payload_b64.encode("ascii"), hashlib.sha256).digest()
        actual_sig = _b64decode(signature_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload_json = _b64decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
        if not isinstance(payload.get("user_id"), int):
            return None
        if not isinstance(payload.get("username"), str) or not payload.get("username"):
            return None
        return payload
    except Exception:
        return None
