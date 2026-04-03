"""Masaüstü cihaz parmak izi (sunucu `mac_address` alanı için)."""

from __future__ import annotations

import uuid


def get_mac_fingerprint() -> str:
    node = uuid.getnode()
    return f"pc:{node:012x}"
