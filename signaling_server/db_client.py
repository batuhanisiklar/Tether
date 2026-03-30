"""
Neon PostgreSQL — kullanıcılar, cihazlar (device_id), eşleşmeler ve bağlantı geçmişi.
Kimlik doğrulama: e-posta + şifre. Bağlantılar device_id üzerinden.
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import contextmanager
from typing import Any, Optional

import bcrypt
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

DB_URL = os.environ.get(
    "NEON_DB_URL",
    "postgresql://neondb_owner:npg_Y3JevV2SsERI@ep-crimson-sun-anqdvhsy-pooler.c-6.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
)


class ServerDbClient:
    def __init__(self, db_url: str = DB_URL):
        self._pool = ThreadedConnectionPool(1, 10, db_url)

    def close(self) -> None:
        self._pool.closeall()

    @contextmanager
    def _get_conn(self):
        conn = self._pool.getconn()
        conn.autocommit = False
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    # ─── Şema ─────────────────────────────────────────────────────────────────

    def init_schema(self) -> bool:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS users (
                            user_id SERIAL PRIMARY KEY,
                            first_name TEXT NOT NULL DEFAULT '',
                            last_name TEXT NOT NULL DEFAULT '',
                            email TEXT NOT NULL UNIQUE,
                            password_h TEXT NOT NULL,
                            phone TEXT,
                            created_at TIMESTAMPTZ DEFAULT now()
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS devices (
                            device_id TEXT PRIMARY KEY,
                            device_name TEXT NOT NULL DEFAULT '',
                            device_type TEXT NOT NULL,
                            is_active BOOLEAN DEFAULT TRUE,
                            is_online BOOLEAN DEFAULT FALSE,
                            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS pairings (
                            id SERIAL PRIMARY KEY,
                            user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                            partner_user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
                            phone_device_id TEXT NOT NULL,
                            pc_device_id TEXT NOT NULL,
                            created_at TIMESTAMPTZ DEFAULT now()
                        );
                        """
                    )
                    cur.execute("DROP TABLE IF EXISTS connections CASCADE")
                    cur.execute(
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT NOT NULL DEFAULT ''"
                    )
                    cur.execute(
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_name TEXT NOT NULL DEFAULT ''"
                    )
                    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS email TEXT")
                    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_h TEXT")
                    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT")
                    cur.execute(
                        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT FALSE"
                    )
                    cur.execute(
                        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS mac_address TEXT"
                    )
                    cur.execute("DROP INDEX IF EXISTS idx_devices_install_id")
                    cur.execute("ALTER TABLE devices DROP COLUMN IF EXISTS install_id")
                    cur.execute(
                        """
                        DELETE FROM devices d
                        USING devices d2
                        WHERE d.user_id = d2.user_id
                          AND d.device_type = d2.device_type
                          AND d.mac_address IS NOT NULL
                          AND d.mac_address = d2.mac_address
                          AND d.device_id > d2.device_id
                        """
                    )
                    cur.execute(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_user_type_mac
                        ON devices(user_id, device_type, mac_address)
                        WHERE mac_address IS NOT NULL AND mac_address <> ''
                        """
                    )
                    cur.execute(
                        "ALTER TABLE pairings ADD COLUMN IF NOT EXISTS partner_user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE"
                    )
                    # Eski (user_id, partner, phone, pc) indeksi — cift satir uretiyordu; tek satir: (phone_device_id, pc_device_id)
                    cur.execute("DROP INDEX IF EXISTS idx_pairings_udpp")
                    cur.execute(
                        """
                        DELETE FROM pairings a
                        USING pairings b
                        WHERE a.phone_device_id = b.phone_device_id
                          AND a.pc_device_id = b.pc_device_id
                          AND a.id < b.id
                        """
                    )
                    cur.execute(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_pairings_phone_pc
                        ON pairings(phone_device_id, pc_device_id)
                        """
                    )
                conn.commit()
            logger.info("DB semasi hazir")
            return True
        except Exception as e:
            logger.exception("init_schema: %s", e)
            return False

    def reset_all_online(self) -> None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE devices SET is_online = false")
                conn.commit()
        except Exception as e:
            logger.warning("reset_all_online: %s", e)

    # ─── Kimlik yardımcıları ───────────────────────────────────────────────────

    @staticmethod
    def _normalize_public_device_id(raw: str | None) -> str | None:
        if not raw:
            return None
        digits = "".join(ch for ch in str(raw) if ch.isdigit())
        if len(digits) != 12:
            return None
        return digits

    @staticmethod
    def _normalize_mac(raw: str | None) -> str | None:
        """MAC (12 hex) veya aid:... Android parmak izi; kullanici+cihaz tipi ile eslestirme."""
        if not raw:
            return None
        s = str(raw).strip().lower()
        if len(s) > 96:
            s = s[:96]
        if s.startswith("aid:"):
            return s
        hexonly = "".join(c for c in s if c in "0123456789abcdef")
        if len(hexonly) == 12:
            return hexonly
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) == 12:
            return digits
        return None

    def _mac_supersede_in_cursor(
        self,
        cur,
        device_id: str,
        device_type: str,
        mac_n: str,
    ) -> list[tuple[int, str]]:
        """Ayni MAC + cihaz tipi: diger hesap/satirlari cevrimdisi (fiziksel cihaz tekilligi)."""
        cur.execute(
            """
            UPDATE devices SET is_online = false
            WHERE mac_address = %s AND device_type = %s AND device_id != %s
            RETURNING user_id, device_id
            """,
            (mac_n, device_type, device_id),
        )
        return [(int(r[0]), str(r[1])) for r in cur.fetchall()]

    def apply_mac_supersede_sessions(self, user_id: int, device_id: str) -> list[tuple[int, str]]:
        """device_hello / WS: bu cihaz satirinin MAC'i ile ayni olan diger oturumlari offline yap."""
        n = self._normalize_public_device_id(device_id)
        if not n:
            return []
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT device_type, mac_address FROM devices
                        WHERE user_id = %s AND device_id = %s
                        """,
                        (user_id, n),
                    )
                    row = cur.fetchone()
                    if not row:
                        return []
                    device_type = str(row[0])
                    mac_n = self._normalize_mac(row[1])
                    if not mac_n:
                        return []
                    evicted = self._mac_supersede_in_cursor(cur, n, device_type, mac_n)
                conn.commit()
            return evicted
        except Exception as e:
            logger.warning("apply_mac_supersede_sessions: %s", e)
            return []

    def pairing_exists_between_devices(self, device_id_a: str, device_id_b: str) -> bool:
        a = self._normalize_public_device_id(device_id_a)
        b = self._normalize_public_device_id(device_id_b)
        if not a or not b:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1 FROM pairings
                        WHERE (phone_device_id = %s AND pc_device_id = %s)
                           OR (phone_device_id = %s AND pc_device_id = %s)
                        LIMIT 1
                        """,
                        (a, b, b, a),
                    )
                    return cur.fetchone() is not None
        except Exception as e:
            logger.error("pairing_exists_between_devices: %s", e)
            return False

    def _generate_unique_device_id(self, cur) -> str:
        for _ in range(80):
            digits = "".join(str(secrets.randbelow(10)) for _ in range(12))
            cur.execute("SELECT 1 FROM devices WHERE device_id = %s", (digits,))
            if cur.fetchone() is None:
                return digits
        raise RuntimeError("Benzersiz device_id uretilemedi")

    def _resolve_owned_device_id(
        self,
        cur,
        user_id: int,
        requested: str | None,
        device_type: str,
        device_name: str | None,
        mac_n: str | None,
    ) -> str:
        if mac_n:
            cur.execute(
                """
                SELECT device_id FROM devices
                WHERE user_id = %s AND device_type = %s AND mac_address = %s
                """,
                (user_id, device_type, mac_n),
            )
            row = cur.fetchone()
            if row:
                return str(row[0])

        normalized = self._normalize_public_device_id(requested)
        if normalized:
            cur.execute(
                """
                SELECT device_id FROM devices
                WHERE device_id = %s AND user_id = %s
                """,
                (normalized, user_id),
            )
            row = cur.fetchone()
            if row:
                d_id = str(row[0])
                if mac_n:
                    cur.execute(
                        """
                        UPDATE devices SET mac_address = %s
                        WHERE device_id = %s AND user_id = %s AND (mac_address IS NULL OR mac_address = '')
                        """,
                        (mac_n, d_id, user_id),
                    )
                return d_id
            cur.execute(
                """
                INSERT INTO devices (device_id, device_name, device_type, is_active, user_id, mac_address)
                VALUES (%s, %s, %s, TRUE, %s, %s)
                """,
                (normalized, device_name or "", device_type, user_id, mac_n),
            )
            return normalized
        new_id = self._generate_unique_device_id(cur)
        cur.execute(
            """
            INSERT INTO devices (device_id, device_name, device_type, is_active, user_id, mac_address)
            VALUES (%s, %s, %s, TRUE, %s, %s)
            """,
            (new_id, device_name or "", device_type, user_id, mac_n),
        )
        return new_id

    def _display_name(self, row: dict) -> str:
        fn = (row.get("first_name") or "").strip()
        ln = (row.get("last_name") or "").strip()
        if fn or ln:
            return f"{fn} {ln}".strip()
        return (row.get("email") or "").strip() or "Kullanici"

    # ─── Kullanıcı ─────────────────────────────────────────────────────────────

    def register_user(
        self,
        email: str,
        password: str,
        first_name: str = "",
        last_name: str = "",
        phone: str | None = None,
    ) -> tuple[bool, str]:
        email_n = email.strip().lower()
        if len(email_n) < 5 or "@" not in email_n:
            return False, "Gecerli bir e-posta adresi girin."
        if len(password) < 6:
            return False, "Sifre en az 6 karakter olmali."
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        fn = first_name.strip() or "Kullanici"
        ln = last_name.strip() or ""
        ph = (phone or "").strip() or None
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users (first_name, last_name, email, password_h, phone)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING user_id
                        """,
                        (fn, ln, email_n, pw_hash, ph),
                    )
                    row = cur.fetchone()
                    if not row:
                        conn.rollback()
                        return False, "Kayit olusturulamadi."
                conn.commit()
            logger.info("Yeni kullanici: %s", email_n)
            return True, "Kayit basarili! Giris yapabilirsiniz."
        except psycopg2.errors.UniqueViolation:
            return False, "Bu e-posta adresi zaten kayitli."
        except Exception as e:
            logger.exception("register_user: %s", e)
            return False, f"Sunucu hatasi: {e}"

    def authenticate_user(self, login: str, password: str) -> Optional[tuple[int, str]]:
        """
        login: e-posta (veya mobil/geriye uyumluluk icin kullanici adi olarak e-posta formatinda olmayan deger)
        Dönüş: (user_id, gorunen_ad) — JWT username alanında kullanılır.
        """
        key = login.strip().lower()
        if not key:
            return None
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT user_id, email, password_h, first_name, last_name
                        FROM users WHERE email = %s
                        """,
                        (key,),
                    )
                    row = cur.fetchone()
            if not row:
                return None
            if not bcrypt.checkpw(password.encode(), str(row["password_h"]).encode()):
                return None
            uid = int(row["user_id"])
            display = self._display_name(dict(row))
            logger.info("Giris: %s (id=%s)", key, uid)
            return uid, display
        except Exception as e:
            logger.exception("authenticate_user: %s", e)
            return None

    def get_user_profile(self, user_id: int, device_id_param: str | None) -> dict:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT user_id, first_name, last_name, email, phone
                        FROM users WHERE user_id = %s
                        """,
                        (user_id,),
                    )
                    u = cur.fetchone()
                    if not u:
                        return {}
                    resolved = ""
                    if device_id_param:
                        n = self._normalize_public_device_id(device_id_param)
                        if n:
                            cur.execute(
                                """
                                SELECT device_id FROM devices
                                WHERE user_id = %s AND device_id = %s
                                """,
                                (user_id, n),
                            )
                            r = cur.fetchone()
                            if r:
                                resolved = str(r["device_id"])
                    uid = int(u["user_id"])
                    return {
                        "id": uid,
                        "user_id": uid,
                        "first_name": u["first_name"],
                        "last_name": u["last_name"],
                        "email": u["email"],
                        "phone": u["phone"],
                        "username": self._display_name(dict(u)),
                        "device_id": resolved,
                        "address": resolved,
                    }
        except Exception as e:
            logger.error("get_user_profile: %s", e)
            return {}

    # ─── Cihaz ─────────────────────────────────────────────────────────────────

    def upsert_device(
        self,
        user_id: int,
        device_id: str,
        device_type: str,
        device_name: str | None,
        mac_address: str | None = None,
    ) -> tuple[str | None, list[tuple[int, str]]]:
        """
        Cihaz kaydi. mac_address ayni kullanici+cihaz tipinde eslesirse mevcut device_id doner.
        Ayni MAC baska satirda (baska hesap) ise o satirlar cevrimdisi yapilir.
        """
        if device_type not in {"phone", "pc"}:
            return None, []
        mac_n = self._normalize_mac(mac_address)
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    resolved = self._resolve_owned_device_id(
                        cur, user_id, device_id, device_type, device_name, mac_n
                    )
                    cur.execute(
                        """
                        UPDATE devices SET device_name = COALESCE(NULLIF(%s, ''), device_name),
                        device_type = %s, is_active = TRUE,
                        mac_address = COALESCE(NULLIF(%s, ''), mac_address)
                        WHERE device_id = %s AND user_id = %s
                        """,
                        (device_name or "", device_type, mac_n or "", resolved, user_id),
                    )
                    cur.execute(
                        "SELECT mac_address FROM devices WHERE user_id = %s AND device_id = %s",
                        (user_id, resolved),
                    )
                    row = cur.fetchone()
                    mac_db = self._normalize_mac(row[0] if row else None)
                    evicted = self._mac_supersede_in_cursor(cur, resolved, device_type, mac_db) if mac_db else []
                conn.commit()
            return resolved, evicted
        except Exception as e:
            logger.error("upsert_device: %s", e)
            return None, []

    def user_owns_device(self, user_id: int, device_id: str) -> bool:
        n = self._normalize_public_device_id(device_id)
        if not n:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM devices WHERE user_id = %s AND device_id = %s",
                        (user_id, n),
                    )
                    return cur.fetchone() is not None
        except Exception:
            return False

    def get_device_binding_by_address(self, device_id: str) -> dict | None:
        n = self._normalize_public_device_id(device_id)
        if not n:
            return None
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT d.device_id, d.user_id, d.device_type, u.email AS username
                        FROM devices d
                        JOIN users u ON u.user_id = d.user_id
                        WHERE d.device_id = %s
                        """,
                        (n,),
                    )
                    row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error("get_device_binding_by_address: %s", e)
            return None

    def set_device_online(self, user_id: int, device_id: str, online: bool) -> None:
        n = self._normalize_public_device_id(device_id)
        if not n:
            return
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE devices SET is_online = %s
                        WHERE user_id = %s AND device_id = %s
                        """,
                        (online, user_id, n),
                    )
                conn.commit()
        except Exception as e:
            logger.warning("set_device_online: %s", e)

    def get_user_devices(self, user_id: int) -> list[dict]:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT d.device_id, d.device_type, d.device_name,
                               d.device_id AS address,
                               COALESCE(d.is_online, false) AS is_online,
                               d.mac_address,
                               d.user_id AS owner_user_id,
                               (NULLIF(BTRIM(u.first_name || ' ' || u.last_name), '')) AS owner_name,
                               COALESCE(NULLIF(BTRIM(u.phone), ''), '') AS owner_phone,
                               COALESCE(NULLIF(BTRIM(u.email), ''), '') AS owner_email
                        FROM devices d
                        JOIN users u ON u.user_id = d.user_id
                        WHERE d.user_id = %s
                        ORDER BY d.device_type, d.device_name, d.device_id
                        """,
                        (user_id,),
                    )
                    return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_user_devices: %s", e)
            return []

    # ─── Eşleşme / bağlantı ───────────────────────────────────────────────────

    def _device_types(self, cur, a: str, b: str) -> tuple[str | None, str | None]:
        cur.execute(
            "SELECT device_id, device_type FROM devices WHERE device_id IN (%s, %s)",
            (a, b),
        )
        types = {r[0]: r[1] for r in cur.fetchall()}
        return types.get(a), types.get(b)

    def save_pairing_by_device_ids(self, first_device_id: str, second_device_id: str) -> None:
        """Iki cihaz (telefon+pc) arasinda tek pairing satiri; user_id=telefon sahibi, partner_user_id=pc sahibi."""
        a = self._normalize_public_device_id(first_device_id)
        b = self._normalize_public_device_id(second_device_id)
        if not a or not b:
            return
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    ta, tb = self._device_types(cur, a, b)
                    if not ta or not tb or ta == tb:
                        return
                    if ta == "phone" and tb == "pc":
                        phone_id, pc_id = a, b
                    else:
                        phone_id, pc_id = b, a
                    cur.execute(
                        "SELECT user_id FROM devices WHERE device_id = %s",
                        (phone_id,),
                    )
                    r_ph = cur.fetchone()
                    cur.execute(
                        "SELECT user_id FROM devices WHERE device_id = %s",
                        (pc_id,),
                    )
                    r_pc = cur.fetchone()
                    if not r_ph or not r_pc:
                        return
                    phone_user_id = int(r_ph[0])
                    pc_user_id = int(r_pc[0])
                    cur.execute(
                        """
                        INSERT INTO pairings (user_id, partner_user_id, phone_device_id, pc_device_id)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (phone_device_id, pc_device_id)
                        DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            partner_user_id = EXCLUDED.partner_user_id
                        """,
                        (phone_user_id, pc_user_id, phone_id, pc_id),
                    )
                conn.commit()
        except Exception as e:
            logger.warning("save_pairing_by_device_ids: %s", e)

    def get_paired_partner_refs(self, _user_id: int, device_id: str) -> list[tuple[int, str]]:
        n = self._normalize_public_device_id(device_id)
        if not n:
            return []
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT DISTINCT d.user_id, d.device_id
                        FROM pairings p
                        JOIN devices d ON d.device_id = (
                            CASE WHEN p.phone_device_id = %s THEN p.pc_device_id
                                 ELSE p.phone_device_id END
                        )
                        WHERE p.phone_device_id = %s OR p.pc_device_id = %s
                        """,
                        (n, n, n),
                    )
                    return [(int(r[0]), str(r[1])) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_paired_partner_refs: %s", e)
            return []

    def get_paired_partner_refs_map(
        self,
        user_id: int,
        device_ids: list[str],
    ) -> dict[str, list[tuple[int, str]]]:
        result: dict[str, list[tuple[int, str]]] = {d: [] for d in device_ids}
        for did in device_ids:
            result[did] = self.get_paired_partner_refs(user_id, did)
        return result

    def get_device_pairings(self, user_id: int, device_id: str) -> list[dict]:
        n = self._normalize_public_device_id(device_id)
        if not n:
            return []
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT DISTINCT p.phone_device_id, p.pc_device_id
                        FROM pairings p
                        WHERE (p.user_id = %s OR p.partner_user_id = %s)
                          AND (p.phone_device_id = %s OR p.pc_device_id = %s)
                        """,
                        (user_id, user_id, n, n),
                    )
                    pairs = cur.fetchall()
            other_ids: set[str] = set()
            for row in pairs:
                ph = str(row["phone_device_id"])
                pc = str(row["pc_device_id"])
                other_ids.add(pc if ph == n else ph)
            out: list[dict] = []
            for oid in other_ids:
                with self._get_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(
                            """
                            SELECT d.device_id, d.device_type, d.device_name,
                                   d.device_id AS address, COALESCE(d.is_online, false) AS is_online,
                                   d.mac_address,
                                   d.user_id AS owner_user_id,
                                   (NULLIF(BTRIM(u.first_name || ' ' || u.last_name), '')) AS owner_name,
                                   COALESCE(NULLIF(BTRIM(u.phone), ''), '') AS owner_phone,
                                   COALESCE(NULLIF(BTRIM(u.email), ''), '') AS owner_email
                            FROM devices d
                            JOIN users u ON u.user_id = d.user_id
                            WHERE d.device_id = %s
                            """,
                            (oid,),
                        )
                        r = cur.fetchone()
                        if r:
                            out.append(dict(r))
            return out
        except Exception as e:
            logger.error("get_device_pairings: %s", e)
            return []

    def get_user_recent_partner_devices(self, user_id: int, device_type: str) -> list[dict]:
        if device_type not in {"phone", "pc"}:
            return []
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT device_id FROM devices WHERE user_id = %s",
                        (user_id,),
                    )
                    mine = {str(r[0]) for r in cur.fetchall()}
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT phone_device_id, pc_device_id FROM pairings
                        WHERE user_id = %s OR partner_user_id = %s
                        """,
                        (user_id, user_id),
                    )
                    rows = cur.fetchall()
            others: set[str] = set()
            for r in rows:
                ph = str(r["phone_device_id"])
                pc = str(r["pc_device_id"])
                if ph in mine:
                    others.add(pc)
                if pc in mine:
                    others.add(ph)
            others -= mine
            out: list[dict] = []
            for oid in others:
                with self._get_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                        cur.execute(
                            """
                            SELECT d.device_id, d.device_type, d.device_name,
                                   d.device_id AS address, COALESCE(d.is_online, false) AS is_online,
                                   d.mac_address,
                                   d.user_id AS owner_user_id,
                                   (NULLIF(BTRIM(u.first_name || ' ' || u.last_name), '')) AS owner_name,
                                   COALESCE(NULLIF(BTRIM(u.phone), ''), '') AS owner_phone,
                                   COALESCE(NULLIF(BTRIM(u.email), ''), '') AS owner_email
                            FROM devices d
                            JOIN users u ON u.user_id = d.user_id
                            WHERE d.device_id = %s AND d.device_type = %s
                            """,
                            (oid, device_type),
                        )
                        r = cur.fetchone()
                        if r:
                            out.append(dict(r))
            return out
        except Exception as e:
            logger.error("get_user_recent_partner_devices: %s", e)
            return []

    def delete_pairing_by_device_ids(
        self,
        user_id: int,
        device_id: str,
        partner_device_id: str,
    ) -> bool:
        a = self._normalize_public_device_id(device_id)
        b = self._normalize_public_device_id(partner_device_id)
        if not a or not b:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    ta, tb = self._device_types(cur, a, b)
                    if ta and tb and ta != tb:
                        if ta == "phone" and tb == "pc":
                            ph, pc = a, b
                        else:
                            ph, pc = b, a
                        cur.execute(
                            """
                            DELETE FROM pairings
                            WHERE (user_id = %s OR partner_user_id = %s)
                              AND phone_device_id = %s AND pc_device_id = %s
                            """,
                            (user_id, user_id, ph, pc),
                        )
                    else:
                        cur.execute(
                            """
                            DELETE FROM pairings
                            WHERE (user_id = %s OR partner_user_id = %s)
                              AND (
                                (phone_device_id = %s AND pc_device_id = %s)
                                OR (phone_device_id = %s AND pc_device_id = %s)
                              )
                            """,
                            (user_id, user_id, a, b, b, a),
                        )
                conn.commit()
            return True
        except Exception as e:
            logger.error("delete_pairing_by_device_ids: %s", e)
            return False

