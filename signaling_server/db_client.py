from __future__ import annotations
import logging
import os
import secrets
from contextlib import contextmanager
from typing import Optional

import bcrypt
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

DB_URL = os.environ.get("NEON_DB_URL", "postgresql://...")


class ServerDbClient:

    # ------------------------------------------------------------------ #
    #  BAĞLANTI                                                            #
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    #  ŞEMA                                                                #
    # ------------------------------------------------------------------ #

    def init_schema(self) -> bool:
        """
        Tabloları oluşturur.

        pairings mantığı:
          - controller_device : bağlanan  (phone veya pc)
          - target_device     : bağlanılan (phone)
          Geçerli kombinasyonlar → (phone→phone) veya (pc→phone)
          Yön önemli: A→B ile B→A ayrı satır.
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                            user_id    SERIAL PRIMARY KEY,
                            first_name TEXT        NOT NULL DEFAULT '',
                            last_name  TEXT        NOT NULL DEFAULT '',
                            email      TEXT        NOT NULL UNIQUE,
                            password_h TEXT        NOT NULL,
                            phone      TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS devices (
                            device_id   TEXT PRIMARY KEY,
                            device_name TEXT    NOT NULL DEFAULT '',
                            device_type TEXT    NOT NULL CHECK (device_type IN ('phone', 'pc')),
                            is_online   BOOLEAN NOT NULL DEFAULT FALSE,
                            mac_address TEXT,
                            user_id     INTEGER NOT NULL
                                REFERENCES users(user_id) ON DELETE CASCADE
                        )
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS pairings (
                            id                SERIAL PRIMARY KEY,
                            controller_user   INTEGER NOT NULL
                                REFERENCES users(user_id)     ON DELETE CASCADE,
                            target_user       INTEGER NOT NULL
                                REFERENCES users(user_id)     ON DELETE CASCADE,
                            controller_device TEXT    NOT NULL
                                REFERENCES devices(device_id) ON DELETE CASCADE,
                            target_device     TEXT    NOT NULL
                                REFERENCES devices(device_id) ON DELETE CASCADE,
                            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
                            -- Yön önemli: aynı (controller, target) çifti bir kez olabilir
                            CONSTRAINT uq_pairing UNIQUE (controller_device, target_device)
                        )
                    """)

                    # Eski artıklar
                    cur.execute("DROP TABLE IF EXISTS connections CASCADE")
                    cur.execute("ALTER TABLE devices DROP COLUMN IF EXISTS install_id")

                    # Aynı kullanıcı + tip + MAC → tek cihaz
                    cur.execute("""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_user_type_mac
                            ON devices(user_id, device_type, mac_address)
                            WHERE mac_address IS NOT NULL AND mac_address <> ''
                    """)

                conn.commit()
            logger.info("DB şeması hazır.")
            return True
        except Exception as e:
            logger.exception("init_schema: %s", e)
            return False

    # ------------------------------------------------------------------ #
    #  NORMALİZASYON                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _norm_device_id(raw: str | None) -> str | None:
        """12 haneli rakam dizisi; geçersizse None."""
        if not raw:
            return None
        digits = "".join(c for c in str(raw) if c.isdigit())
        return digits if len(digits) == 12 else None

    @staticmethod
    def _norm_mac(raw: str | None) -> str | None:
        """MAC adresini normalize eder. 'aid:' ile başlıyorsa olduğu gibi döner."""
        if not raw:
            return None
        s = str(raw).strip().lower()[:96]
        if s.startswith("aid:"):
            return s
        hexonly = "".join(c for c in s if c in "0123456789abcdef")
        if len(hexonly) == 12:
            return hexonly
        digits = "".join(c for c in s if c.isdigit())
        return digits if len(digits) == 12 else None

    # ------------------------------------------------------------------ #
    #  YARDIMCILAR                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _display_name(row: dict) -> str:
        fn = (row.get("first_name") or "").strip()
        ln = (row.get("last_name") or "").strip()
        full = f"{fn} {ln}".strip()
        return full or (row.get("email") or "").strip() or "Kullanici"

    def _generate_device_id(self, cur) -> str:
        """Veritabanında çakışmayan 12 haneli rastgele ID üretir."""
        for _ in range(80):
            candidate = "".join(str(secrets.randbelow(10)) for _ in range(12))
            cur.execute("SELECT 1 FROM devices WHERE device_id = %s", (candidate,))
            if not cur.fetchone():
                return candidate
        raise RuntimeError("Benzersiz device_id üretilemedi.")

    def _resolve_device_id(
        self,
        cur,
        user_id: int,
        requested: str | None,
        device_type: str,
        device_name: str | None,
        mac_n: str | None,
    ) -> str:
        """
        Kullanıcıya ait cihazı bulur ya da oluşturur.

        Öncelik sırası:
          1. Aynı (user, type, MAC) → mevcut device_id döner         [MAC eşleşmesi]
          2. Aynı (device_id, user, type) → MAC boşsa yazar, döner   [ID eşleşmesi]
          3. Yeni kayıt oluşturur
        """
        norm_req = self._norm_device_id(requested)

        if mac_n:
            # 1 — MAC eşleşmesi
            cur.execute("""
                SELECT device_id FROM devices
                WHERE user_id = %s AND device_type = %s AND mac_address = %s
            """, (user_id, device_type, mac_n))
            row = cur.fetchone()
            if row:
                return str(row[0])

            # 2 — ID eşleşmesi; MAC yoksa güncelle
            if norm_req:
                cur.execute("""
                    SELECT device_id, mac_address FROM devices
                    WHERE device_id = %s AND user_id = %s AND device_type = %s
                """, (norm_req, user_id, device_type))
                row = cur.fetchone()
                if row:
                    existing_mac = self._norm_mac(row[1])
                    if existing_mac is None:
                        cur.execute("""
                            UPDATE devices SET mac_address = %s
                            WHERE device_id = %s AND user_id = %s
                        """, (mac_n, norm_req, user_id))
                        return norm_req
                    if existing_mac == mac_n:
                        return norm_req
                    # MAC çakışıyor → yeni cihaz (fall-through)

        elif norm_req:
            # MAC yok — sadece ID ile ara
            cur.execute("""
                SELECT device_id FROM devices
                WHERE device_id = %s AND user_id = %s
            """, (norm_req, user_id))
            if cur.fetchone():
                return norm_req

            # Başka kullanıcıya ait değilse aynı ID'yi kullan
            cur.execute("SELECT 1 FROM devices WHERE device_id = %s", (norm_req,))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO devices
                        (device_id, device_name, device_type, is_online, user_id, mac_address)
                    VALUES (%s, %s, %s, TRUE, %s, NULL)
                """, (norm_req, device_name or "", device_type, user_id))
                return norm_req

        # 3 — Yeni ID üret
        new_id = self._generate_device_id(cur)
        cur.execute("""
            INSERT INTO devices
                (device_id, device_name, device_type, is_online, user_id, mac_address)
            VALUES (%s, %s, %s, TRUE, %s, %s)
        """, (new_id, device_name or "", device_type, user_id, mac_n))
        return new_id

    def _set_conflicting_macs_offline(
        self, cur, device_id: str, device_type: str, mac_n: str
    ) -> list[tuple[int, str]]:
        """Aynı MAC'e sahip diğer cihazları offline yapar."""
        cur.execute("""
            UPDATE devices SET is_online = FALSE
            WHERE device_type = %s
              AND device_id != %s
              AND LOWER(BTRIM(mac_address)) = LOWER(BTRIM(%s))
            RETURNING user_id, device_id
        """, (device_type, device_id, mac_n))
        return [(int(r[0]), str(r[1])) for r in cur.fetchall()]

    # ------------------------------------------------------------------ #
    #  KULLANICI                                                           #
    # ------------------------------------------------------------------ #

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
            return False, "Geçerli bir e-posta adresi girin."
        if len(password) < 6:
            return False, "Şifre en az 6 karakter olmalı."
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO users (first_name, last_name, email, password_h, phone)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        first_name.strip() or "Kullanici",
                        last_name.strip(),
                        email_n,
                        pw_hash,
                        (phone or "").strip() or None,
                    ))
                conn.commit()
            logger.info("Yeni kullanıcı: %s", email_n)
            return True, "Kayıt başarılı! Giriş yapabilirsiniz."
        except psycopg2.errors.UniqueViolation:
            return False, "Bu e-posta adresi zaten kayıtlı."
        except Exception as e:
            logger.exception("register_user: %s", e)
            return False, f"Sunucu hatası: {e}"

    def authenticate_user(self, email: str, password: str) -> Optional[tuple[int, str]]:
        key = email.strip().lower()
        if not key:
            return None
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        SELECT user_id, password_h, first_name, last_name, email
                        FROM users WHERE email = %s
                    """, (key,))
                    row = cur.fetchone()
            if not row:
                return None
            if not bcrypt.checkpw(password.encode(), row["password_h"].encode()):
                return None
            return int(row["user_id"]), self._display_name(dict(row))
        except Exception as e:
            logger.exception("authenticate_user: %s", e)
            return None

    def get_user_profile(self, user_id: int, device_id: str | None = None) -> dict:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        SELECT user_id, first_name, last_name, email, phone
                        FROM users WHERE user_id = %s
                    """, (user_id,))
                    u = cur.fetchone()
                    if not u:
                        return {}

                    resolved = ""
                    n = self._norm_device_id(device_id)
                    if n:
                        cur.execute("""
                            SELECT device_id FROM devices
                            WHERE user_id = %s AND device_id = %s
                        """, (user_id, n))
                        r = cur.fetchone()
                        if r:
                            resolved = r["device_id"]

            uid = int(u["user_id"])
            return {
                "user_id":     uid,
                "first_name":  u["first_name"],
                "last_name":   u["last_name"],
                "email":       u["email"],
                "phone":       u["phone"],
                "username":    self._display_name(dict(u)),
                "device_id":   resolved,
            }
        except Exception as e:
            logger.error("get_user_profile: %s", e)
            return {}

    # ------------------------------------------------------------------ #
    #  CİHAZ                                                              #
    # ------------------------------------------------------------------ #

    def upsert_device(
        self,
        user_id: int,
        device_id: str,
        device_type: str,
        device_name: str | None,
        mac_address: str | None = None,
    ) -> tuple[str | None, list[tuple[int, str]]]:
        """
        Cihazı ekler veya günceller.
        Döner: (device_id, offline_yapılan_cihazlar)
        """
        if device_type not in {"phone", "pc"}:
            return None, []
        mac_n = self._norm_mac(mac_address)
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    resolved = self._resolve_device_id(
                        cur, user_id, device_id, device_type, device_name, mac_n
                    )
                    cur.execute("""
                        UPDATE devices
                        SET device_name = COALESCE(NULLIF(%s, ''), device_name),
                            is_online   = TRUE,
                            mac_address = COALESCE(NULLIF(%s, ''), mac_address)
                        WHERE device_id = %s AND user_id = %s
                    """, (device_name or "", mac_n or "", resolved, user_id))

                    # Güncel MAC ile çakışan cihazları offline yap
                    cur.execute(
                        "SELECT mac_address FROM devices WHERE device_id = %s", (resolved,)
                    )
                    row = cur.fetchone()
                    mac_db = self._norm_mac(row[0] if row else None)
                    evicted = (
                        self._set_conflicting_macs_offline(cur, resolved, device_type, mac_db)
                        if mac_db else []
                    )
                conn.commit()
            return resolved, evicted
        except Exception as e:
            logger.error("upsert_device: %s", e)
            return None, []

    def set_device_online(self, user_id: int, device_id: str, online: bool) -> None:
        n = self._norm_device_id(device_id)
        if not n:
            return
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE devices SET is_online = %s
                        WHERE user_id = %s AND device_id = %s
                    """, (online, user_id, n))
                conn.commit()
        except Exception as e:
            logger.warning("set_device_online: %s", e)

    def get_user_devices(self, user_id: int) -> list[dict]:
        """Kullanıcıya ait tüm cihazları döner."""
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        SELECT d.device_id,
                               d.device_type,
                               d.device_name,
                               d.is_online,
                               d.mac_address,
                               d.user_id AS owner_user_id,
                               NULLIF(BTRIM(u.first_name || ' ' || u.last_name), '') AS owner_name,
                               COALESCE(NULLIF(BTRIM(u.phone), ''), '') AS owner_phone,
                               COALESCE(NULLIF(BTRIM(u.email), ''), '') AS owner_email
                        FROM devices d
                        JOIN users u ON u.user_id = d.user_id
                        WHERE d.user_id = %s
                        ORDER BY d.device_type, d.device_name, d.device_id
                    """, (user_id,))
                    return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_user_devices: %s", e)
            return []

    def get_device_info(self, device_id: str) -> dict | None:
        n = self._norm_device_id(device_id)
        if not n:
            return None
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        SELECT d.device_id, d.device_type, d.device_name,
                               d.is_online, d.mac_address, d.user_id,
                               u.email AS owner_email
                        FROM devices d
                        JOIN users u ON u.user_id = d.user_id
                        WHERE d.device_id = %s
                    """, (n,))
                    row = cur.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error("get_device_info: %s", e)
            return None

    def user_owns_device(self, user_id: int, device_id: str) -> bool:
        n = self._norm_device_id(device_id)
        if not n:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM devices WHERE user_id = %s AND device_id = %s",
                        (user_id, n),
                    )
                    return bool(cur.fetchone())
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    #  PAİRİNG                                                            #
    #                                                                     #
    #  controller_device → target_device (yön önemli)                    #
    #  Geçerli: phone→phone, pc→phone                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _valid_pairing_types(controller_type: str, target_type: str) -> bool:
        return target_type == "phone" and controller_type in {"phone", "pc"}

    def save_pairing(self, controller_device_id: str, target_device_id: str) -> bool:
        c = self._norm_device_id(controller_device_id)
        t = self._norm_device_id(target_device_id)
        if not c or not t or c == t:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT device_id, device_type, user_id FROM devices
                        WHERE device_id IN (%s, %s)
                    """, (c, t))
                    rows = {r[0]: (r[1], int(r[2])) for r in cur.fetchall()}

                    if c not in rows or t not in rows:
                        return False
                    c_type, c_user = rows[c]
                    t_type, t_user = rows[t]

                    if not self._valid_pairing_types(c_type, t_type):
                        logger.warning(
                            "save_pairing: geçersiz tip çifti %s→%s", c_type, t_type
                        )
                        return False

                    cur.execute("""
                        INSERT INTO pairings
                            (controller_user, target_user, controller_device, target_device)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (controller_device, target_device)
                        DO UPDATE SET
                            controller_user = EXCLUDED.controller_user,
                            target_user     = EXCLUDED.target_user
                    """, (c_user, t_user, c, t))
                conn.commit()
            return True
        except Exception as e:
            logger.warning("save_pairing: %s", e)
            return False

    def pairing_exists(self, controller_device_id: str, target_device_id: str) -> bool:
        c = self._norm_device_id(controller_device_id)
        t = self._norm_device_id(target_device_id)
        if not c or not t:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 1 FROM pairings
                        WHERE controller_device = %s AND target_device = %s
                        LIMIT 1
                    """, (c, t))
                    return bool(cur.fetchone())
        except Exception as e:
            logger.error("pairing_exists: %s", e)
            return False

    def get_device_pairings(self, user_id: int, device_id: str) -> dict[str, list[dict]]:
        """
        Bir cihazın pairing'lerini döner.
        {
          "controlling": [...],  # bu cihazın kontrol ettiği hedefler
          "controlled_by": [...] # bu cihazı kontrol eden kontrolcüler
        }
        """
        n = self._norm_device_id(device_id)
        if not n:
            return {"controlling": [], "controlled_by": []}
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        SELECT
                            p.controller_device,
                            p.target_device,
                            d.device_id,
                            d.device_type,
                            d.device_name,
                            d.is_online,
                            d.user_id AS owner_user_id,
                            NULLIF(BTRIM(u.first_name || ' ' || u.last_name), '') AS owner_name,
                            COALESCE(NULLIF(BTRIM(u.email), ''), '') AS owner_email
                        FROM pairings p
                        JOIN devices d ON d.device_id = CASE
                            WHEN p.controller_device = %s THEN p.target_device
                            ELSE p.controller_device
                        END
                        JOIN users u ON u.user_id = d.user_id
                        WHERE (p.controller_user = %s OR p.target_user = %s)
                          AND (p.controller_device = %s OR p.target_device = %s)
                    """, (n, user_id, user_id, n, n))
                    rows = cur.fetchall()

            controlling   = []
            controlled_by = []
            for r in rows:
                info = {k: v for k, v in dict(r).items()
                        if k not in ("controller_device", "target_device")}
                if r["controller_device"] == n:
                    controlling.append(info)
                else:
                    controlled_by.append(info)

            return {"controlling": controlling, "controlled_by": controlled_by}
        except Exception as e:
            logger.error("get_device_pairings: %s", e)
            return {"controlling": [], "controlled_by": []}

    def delete_pairing(
        self, user_id: int, controller_device_id: str, target_device_id: str
    ) -> bool:
        """Yönlü pairing'i siler. Yalnızca pairing'in tarafı olan kullanıcı silebilir."""
        c = self._norm_device_id(controller_device_id)
        t = self._norm_device_id(target_device_id)
        if not c or not t:
            return False
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM pairings
                        WHERE controller_device = %s
                          AND target_device     = %s
                          AND (controller_user = %s OR target_user = %s)
                    """, (c, t, user_id, user_id))
                conn.commit()
            return True
        except Exception as e:
            logger.error("delete_pairing: %s", e)
            return False

    def get_all_paired_devices(self, device_id: str) -> list[tuple[int, str]]:
        """
        Bir cihazın dahil olduğu tüm pairing'lerin karşı ucunu döner.
        Signaling server'ın oturum yönetimi için kullanılır.
        """
        n = self._norm_device_id(device_id)
        if not n:
            return []
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT DISTINCT d.user_id, d.device_id
                        FROM pairings p
                        JOIN devices d ON d.device_id = CASE
                            WHEN p.controller_device = %s THEN p.target_device
                            ELSE p.controller_device
                        END
                        WHERE p.controller_device = %s OR p.target_device = %s
                    """, (n, n, n))
                    return [(int(r[0]), str(r[1])) for r in cur.fetchall()]
        except Exception as e:
            logger.error("get_all_paired_devices: %s", e)
            return []