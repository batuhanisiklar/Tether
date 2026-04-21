import os


# ── Cihaz / sistem ───────────────────────────────────────────────────────────

def desktop_device_name() -> str:
    """Mevcut bilgisayarın adını döner."""
    return os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "Bu Bilgisayar"


# ── Adres formatlamak ────────────────────────────────────────────────────────

def address_digits(value: str | None) -> str:
    """Verilen değerden en fazla 12 rakam çeker."""
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:12]


def format_address(addr: str) -> str:
    """12 rakamı 'XXXX-XXXX-XXXX' biçimine dönüştürür."""
    digits = address_digits(addr)
    return "-".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def format_address_spaced(addr: str) -> str:
    """format_address ile aynı; semantik ayrım için alias."""
    return format_address(addr)


# ── Cihaz görüntü adı ────────────────────────────────────────────────────────

def display_device_name(device_name: str | None, address: str | None, device_id: str) -> str:
    """Öncelik sırasıyla device_name → address → device_id döner."""
    if device_name and device_name.strip():
        return device_name.strip()
    if address and address.strip():
        return format_address(address)
    return "..." + device_id[-8:] if len(device_id) > 8 else device_id


def compact_label(text: str, limit: int = 24) -> str:
    """Metni belirtilen karakter sınırında '...' ile keser."""
    text = text.strip()
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def display_username(username: str | None) -> str:
    """Kullanıcı adını büyük harfle başlatarak döner."""
    value = (username or "").strip()
    if not value:
        return "Kullanıcı"
    return value[:1].upper() + value[1:]


# ── Sekme etiketleri ─────────────────────────────────────────────────────────

def session_tab_label(
    owner_name: str | None,
    device_label: str | None,
    address_raw: str | None,
) -> str:
    """Oturum sekmesi için 'Sahip - Cihaz - XXXX-XXXX-XXXX' biçimli etiket."""
    owner = (owner_name or "").strip()
    device = (device_label or "").strip()
    addr = address_digits(address_raw)
    addr_fmt = format_address(addr) if addr else ""
    parts = [p for p in (owner, device, addr_fmt) if p]
    return " - ".join(parts) if parts else "Oturum"


# ── WebSocket yardımcıları ───────────────────────────────────────────────────

def ws_device_id_set(items: list | None) -> set[str]:
    """WS device_ack listesinden temiz device_id seti oluşturur."""
    return {str(x).strip() for x in (items or []) if str(x).strip()}


def phone_row_key(device: dict) -> str:
    """Cihaz satırı için benzersiz anahtar; device_id kullanır."""
    return str(device.get("device_id") or "").strip()


def is_accessibility_ws_error(message: str, code: str) -> bool:
    """WS hata mesajının erişilebilirlik kaynaklı olup olmadığını belirler."""
    if (code or "").strip() == "accessibility_required":
        return True
    folded = (message or "").translate(
        str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC")
    ).lower()
    return "erisilebilirlik" in folded or "accessibility" in folded


# ── Cihaz satırı birleştirme ─────────────────────────────────────────────────

def merge_phone_device_row(existing: dict, row: dict) -> dict:
    """
    İki farklı API endpoint'inden gelen aynı telefon kaydını birleştirir.
    Adres çakışmalarını device_id'ye göre çözer.
    """
    did = str(row.get("device_id") or existing.get("device_id") or "").strip()
    dd  = address_digits(did)
    ra  = address_digits(row.get("address"))
    ea  = address_digits(existing.get("address"))

    if ra == dd and dd:
        addr = dd
    elif ea == dd and dd:
        addr = dd
    else:
        addr = ra or ea or dd

    out = {**existing, **row, "address": addr, "device_id": did}

    if "is_online" in row:
        out["is_online"] = bool(row["is_online"])
        
    # Mevcut verideki bilgileri kaybetmemek için boş gelenleri geri yükle
    for key in ("owner_name", "owner_phone", "owner_email", "owner_user_id", "device_name"):
        if not str(out.get(key) or "").strip() and str(existing.get(key) or "").strip():
            out[key] = existing[key]

    # owner veya user nesnesinden ad/soyad çek
    if not (str(out.get("owner_name") or "").strip()):
        owner_obj = row.get("owner") or existing.get("owner") or row.get("user") or existing.get("user")
        if isinstance(owner_obj, dict):
            fn = str(owner_obj.get("first_name") or owner_obj.get("firstName") or "").strip()
            ln = str(owner_obj.get("last_name") or owner_obj.get("lastName") or "").strip()
            full = f"{fn} {ln}".strip()
            if full:
                out["owner_name"] = full
            else:
                name = str(owner_obj.get("name") or "").strip()
                if name:
                    out["owner_name"] = name
                else:
                    alt = str(owner_obj.get("username") or owner_obj.get("email") or "").strip()
                    if alt:
                        out["owner_name"] = alt
        else:
            fn = str(
                row.get("owner_first_name") or row.get("ownerFirstName") or existing.get("owner_first_name") or
                row.get("user_first_name") or row.get("first_name") or row.get("firstName") or ""
            ).strip()
            ln = str(
                row.get("owner_last_name") or row.get("ownerLastName") or existing.get("owner_last_name") or
                row.get("user_last_name") or row.get("last_name") or row.get("lastName") or ""
            ).strip()
            full = f"{fn} {ln}".strip()
            if full:
                out["owner_name"] = full
            else:
                alt = str(
                    row.get("username") or row.get("email") or
                    row.get("owner_email") or row.get("user_email") or
                    existing.get("owner_email") or existing.get("user_email") or
                    row.get("owner_name") or existing.get("owner_name") or ""
                ).strip()
                if alt:
                    out["owner_name"] = alt
    return out


# ── Adres input imleci yönetimi ──────────────────────────────────────────────

def digits_before_cursor(text: str, cursor: int) -> int:
    """İmlecin solundaki rakam sayısını döner."""
    return sum(1 for ch in text[:cursor] if ch.isdigit())


def cursor_for_digit_count(text: str, digit_count: int) -> int:
    """Metinde ilk `digit_count` rakamdan sonraki karakter indeksini döner."""
    seen = 0
    for i, ch in enumerate(text):
        if ch.isdigit():
            seen += 1
            if seen == digit_count:
                return i + 1
    return len(text)
