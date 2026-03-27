"""Bu makineye ozgü sabit parmak izi (MAC tabanlı veya uuid.getnode). Sunucuda cihaz satiri eslestirmek icin."""

from __future__ import annotations

import uuid


def get_mac_fingerprint() -> str:
    """12 hex karakter — gercek MAC olmayabilir; ayni kurulumda sabit kalir."""
    n = uuid.getnode()
    return f"{n & 0xFFFFFFFFFFFF:012x}"
