"""
DbClient — Neon (PostgreSQL) bağlantısı.
Tüm DB işlemleri burada toplanır: schema init, kullanıcı auth, cihaz kaydı, pairing.
"""

import logging
import bcrypt
import psycopg2
import psycopg2.extras
from contextlib import contextmanager
from typing import Optional

from desktop_app.config import Prefs

logger = logging.getLogger(__name__)

# ─── Şema ─────────────────────────────────────────────────────────────────────
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL,
    address     TEXT UNIQUE,
    password_h  TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devices (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    device_id   TEXT UNIQUE NOT NULL,
    device_type TEXT NOT NULL,
    device_name TEXT,
    is_online   BOOLEAN DEFAULT false
);

CREATE TABLE IF NOT EXISTS pairings (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    phone_device_id TEXT NOT NULL,
    pc_device_id    TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(phone_device_id, pc_device_id)
);
"""


class DbClient:
    """
    Thread-safe Neon PostgreSQL istemcisi.
    Tüm metodlar çağrıldığı thread'den çalışır;
    birden fazla thread'den çağrılmaması tavsiye edilir (PyQt slot'larından kullanın).
    """

    def __init__(self, db_url: str = Prefs.DB_URL):
        self._url = db_url
        logger.info("Desktop DB istemcisi hazirlandi (islem bazli baglanti)")

    @staticmethod
    def _is_retryable_db_error(exc: Exception) -> bool:
        text = str(exc).lower()
        retryable_fragments = (
            "cursor already closed",
            "connection already closed",
            "connection pool is closed",
            "closed the connection unexpectedly",
            "ssl connection has been closed unexpectedly",
        )
        return any(fragment in text for fragment in retryable_fragments)

    @contextmanager
    def _get_conn(self):
        """
        Desktop uygulamasi seyrek DB kullandigi icin her islemde taze baglanti acar.
        Bu, Neon'un bosta kalan pooled baglantilari kapatmasindan kaynaklanan
        stale cursor / closed connection sorunlarini belirgin sekilde azaltir.
        """
        conn = psycopg2.connect(
            self._url,
            connect_timeout=10,
            application_name="remote_phone_control_desktop",
        )
        conn.autocommit = False
        try:
            yield conn
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def close(self):
        # Islem bazli baglanti modelinde kalici pool yok.
        return None

    # ─── Schema ───────────────────────────────────────────────────────────────

    def init_schema(self) -> bool:
        """Tabloları oluşturur. Uygulama başlangıcında bir kez çağrılır."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(_SCHEMA_SQL)
                    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT")
                    cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_name TEXT")
                    cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT false")
                    cur.execute("ALTER TABLE devices DROP COLUMN IF EXISTS last_seen")
                    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_address_unique_idx ON users(address)")
                    cur.execute("UPDATE users SET address = (111111111110 + id)::text WHERE address IS NULL")
                    cur.execute("""
                        CREATE OR REPLACE FUNCTION set_user_address()
                        RETURNS TRIGGER AS $$
                        BEGIN
                            IF NEW.address IS NULL THEN
                                NEW.address := (111111111110 + NEW.id)::text;
                            END IF;
                            RETURN NEW;
                        END;
                        $$ LANGUAGE plpgsql;
                    """)
                    cur.execute("""
                        DROP TRIGGER IF EXISTS trg_set_user_address ON users;
                        CREATE TRIGGER trg_set_user_address
                        BEFORE INSERT ON users
                        FOR EACH ROW EXECUTE FUNCTION set_user_address();
                    """)
                    cur.execute("ALTER TABLE pairings ALTER COLUMN user_id DROP NOT NULL")
                conn.commit()
            logger.info("DB schema geçerli")
            return True
        except Exception as e:
            logger.error(f"Schema init hatası: {e}")
            return False

    # ─── Kullanıcı yönetimi ───────────────────────────────────────────────────

    def register_user(self, username: str, password: str) -> tuple[bool, str]:
        """
        Yeni kullanıcı kaydeder.
        Dönüş: (başarı, mesaj)
        """
        if len(username.strip()) < 3:
            return False, "Kullanıcı adı en az 3 karakter olmalı."
        if len(password) < 6:
            return False, "Şifre en az 6 karakter olmalı."
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        normalized_username = username.strip().lower()
        for attempt in range(2):
            try:
                with self._get_conn() as conn:
                    try:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                WITH new_row AS (
                                    INSERT INTO users (username, password_h)
                                    VALUES (%s, %s)
                                    RETURNING id
                                )
                                UPDATE users
                                SET address = (111111111110 + new_row.id)::text
                                FROM new_row
                                WHERE users.id = new_row.id
                                RETURNING users.id
                                """,
                                (normalized_username, pw_hash),
                            )
                            user_id = cur.fetchone()[0]
                        conn.commit()
                        logger.info(f"Kullanıcı kaydedildi: {username} (id={user_id})")
                        return True, "Kayıt başarılı! Giriş yapabilirsiniz."
                    except psycopg2.errors.UniqueViolation:
                        conn.rollback()
                        return False, "Bu kullanıcı adı zaten kullanımda."
            except Exception as e:
                if attempt == 0 and self._is_retryable_db_error(e):
                    logger.warning("Register sirasinda gecici DB hatasi algilandi, tekrar denenecek: %s", e)
                    continue
                logger.exception("Register hatası")
                return False, f"Sunucu hatası: {e}"

    def authenticate_user(self, username: str, password: str) -> Optional[tuple[int, str]]:
        """
        Kullanıcıyı doğrular.
        Dönüş: (user_id, username) veya None
        """
        normalized_username = username.strip().lower()
        for attempt in range(2):
            try:
                with self._get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT id, username, address, password_h FROM users WHERE username = %s",
                            (normalized_username,),
                        )
                        row = cur.fetchone()
                if row is None:
                    return None
                uid, uname, _address, pw_hash = row
                if bcrypt.checkpw(password.encode(), pw_hash.encode()):
                    logger.info(f"Giriş başarılı: {uname} (id={uid})")
                    return uid, uname
                return None
            except Exception as e:
                if attempt == 0 and self._is_retryable_db_error(e):
                    logger.warning("Auth sirasinda gecici DB hatasi algilandi, tekrar denenecek: %s", e)
                    continue
                logger.exception("Auth hatası")
                return None

    def authenticate_user_with_error(self, username: str, password: str) -> tuple[Optional[tuple[int, str]], str]:
        """
        UI'nin kullaniciya yanlis 'sifre hatali' gostermemesi icin detayli auth sonucu.
        Dönüş: ((user_id, username) | None, hata_mesaji)
        """
        normalized_username = username.strip().lower()
        for attempt in range(2):
            try:
                with self._get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT id, username, address, password_h FROM users WHERE username = %s",
                            (normalized_username,),
                        )
                        row = cur.fetchone()
                if row is None:
                    return None, ""
                uid, uname, _address, pw_hash = row
                if bcrypt.checkpw(password.encode(), pw_hash.encode()):
                    logger.info(f"Giriş başarılı: {uname} (id={uid})")
                    return (uid, uname), ""
                return None, ""
            except Exception as e:
                if attempt == 0 and self._is_retryable_db_error(e):
                    logger.warning("Detayli auth sirasinda gecici DB hatasi algilandi, tekrar denenecek: %s", e)
                    continue
                logger.exception("Detayli auth hatası")
                return None, f"Sunucu hatası: {e}"

    # ─── Cihaz yönetimi ───────────────────────────────────────────────────────

    def upsert_device(self, user_id: int, device_id: str, device_type: str, device_name: str | None = None) -> bool:
        """Cihazı DB'ye ekler veya günceller."""
        try:
            with self._get_conn() as conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO devices (user_id, device_id, device_type, device_name)
                            VALUES (%s, %s, %s, NULLIF(%s, ''))
                            ON CONFLICT (device_id) DO UPDATE
                                SET user_id = EXCLUDED.user_id,
                                    device_type = EXCLUDED.device_type,
                                    device_name = COALESCE(EXCLUDED.device_name, devices.device_name)
                        """, (user_id, device_id, device_type, device_name))
                    conn.commit()
                    return True
                except Exception:
                    conn.rollback()
                    raise
        except Exception as e:
            logger.error(f"Upsert device hatası: {e}")
            return False

    def get_paired_devices(self, pc_device_id: str) -> list[dict]:
        """
        Bu PC ile daha once eşleşmiş tüm telefonları döner.
        Dönüş: [{"device_id": str, "device_name": str|None, "is_online": bool, "address": str|None}]
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        SELECT p.phone_device_id AS device_id,
                               d.device_name,
                               COALESCE(d.is_online, false) AS is_online,
                               u.address
                        FROM pairings p
                        LEFT JOIN devices d ON d.device_id = p.phone_device_id
                        LEFT JOIN users u ON u.id = d.user_id
                        WHERE p.pc_device_id = %s
                        ORDER BY d.is_online DESC, d.device_name ASC NULLS LAST
                    """, (pc_device_id,))
                    rows = cur.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_paired_devices hatası: {e}")
            return []

    # ─── Pairing ──────────────────────────────────────────────────────────────

    def save_pairing(self, phone_device_id: str, pc_device_id: str) -> bool:
        """Eşleşmeyi DB'ye kaydeder (idempotent)."""
        try:
            with self._get_conn() as conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO pairings (user_id, phone_device_id, pc_device_id)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (phone_device_id, pc_device_id) DO NOTHING
                        """, (None, phone_device_id, pc_device_id))
                    conn.commit()
                    logger.info(f"Pairing kaydedildi: {phone_device_id} <-> {pc_device_id}")
                    return True
                except Exception:
                    conn.rollback()
                    raise
        except Exception as e:
            logger.error(f"save_pairing hatası: {e}")
            return False

    def delete_pairing(self, phone_device_id: str, pc_device_id: str) -> bool:
        """Eşleşmeyi DB'den siler."""
        try:
            with self._get_conn() as conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            DELETE FROM pairings
                            WHERE phone_device_id = %s AND pc_device_id = %s
                        """, (phone_device_id, pc_device_id))
                    conn.commit()
                    return True
                except Exception:
                    conn.rollback()
                    raise
        except Exception as e:
            logger.error(f"delete_pairing hatası: {e}")
            return False

    def find_phone_device_by_address(self, address: str) -> Optional[str]:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.device_id
                        FROM devices d
                        JOIN users u ON u.id = d.user_id
                        WHERE u.address = %s AND d.device_type = 'phone'
                        ORDER BY d.is_online DESC, d.id DESC
                        LIMIT 1
                        """,
                        (address,),
                    )
                    row = cur.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"find_phone_device_by_address hatası: {e}")
            return None

    def get_user_address(self, user_id: int) -> str | None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT address FROM users WHERE id = %s", (user_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    if row[0] is None:
                        new_address = str(111111111110 + user_id)
                        cur.execute(
                            "UPDATE users SET address = %s WHERE id = %s AND address IS NULL",
                            (new_address, user_id),
                        )
                        conn.commit()
                        return new_address
            return row[0]
        except Exception as e:
            logger.error(f"get_user_address hatası: {e}")
            return None
