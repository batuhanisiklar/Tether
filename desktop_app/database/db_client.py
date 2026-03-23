"""
DbClient — Neon (PostgreSQL) bağlantısı.
Tüm DB işlemleri burada toplanır: schema init, kullanıcı auth, cihaz kaydı, pairing.
"""

import logging
import threading
import bcrypt
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from desktop_app.config import Prefs

logger = logging.getLogger(__name__)

# ─── Şema ─────────────────────────────────────────────────────────────────────
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    username    TEXT UNIQUE NOT NULL,
    password_h  TEXT NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS devices (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    device_id   TEXT UNIQUE NOT NULL,
    device_type TEXT NOT NULL,
    last_seen   TIMESTAMPTZ DEFAULT now()
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
        logger.info("Neon DB pool oluşturuluyor...")
        self._pool = ThreadedConnectionPool(1, 10, self._url)

    @contextmanager
    def _get_conn(self):
        """Pool'dan thread-safe bağlantı alır ve işlemi bitince geri koyar."""
        conn = self._pool.getconn()
        conn.autocommit = False
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def close(self):
        if self._pool:
            self._pool.closeall()

    # ─── Schema ───────────────────────────────────────────────────────────────

    def init_schema(self) -> bool:
        """Tabloları oluşturur. Uygulama başlangıcında bir kez çağrılır."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(_SCHEMA_SQL)
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
        try:
            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            with self._get_conn() as conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO users (username, password_h) VALUES (%s, %s) RETURNING id",
                            (username.strip().lower(), pw_hash),
                        )
                        user_id = cur.fetchone()[0]
                    conn.commit()
                    logger.info(f"Kullanıcı kaydedildi: {username} (id={user_id})")
                    return True, "Kayıt başarılı! Giriş yapabilirsiniz."
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                    return False, "Bu kullanıcı adı zaten kullanımda."
        except Exception as e:
            logger.error(f"Register hatası: {e}")
            return False, f"Sunucu hatası: {e}"

    def authenticate_user(self, username: str, password: str) -> Optional[tuple[int, str]]:
        """
        Kullanıcıyı doğrular.
        Dönüş: (user_id, username) veya None
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, username, password_h FROM users WHERE username = %s",
                        (username.strip().lower(),),
                    )
                    row = cur.fetchone()
            if row is None:
                return None
            uid, uname, pw_hash = row
            if bcrypt.checkpw(password.encode(), pw_hash.encode()):
                logger.info(f"Giriş başarılı: {uname} (id={uid})")
                return uid, uname
            return None
        except Exception as e:
            logger.error(f"Auth hatası: {e}")
            return None

    # ─── Cihaz yönetimi ───────────────────────────────────────────────────────

    def upsert_device(self, user_id: int, device_id: str, device_type: str) -> bool:
        """Cihazı DB'ye ekler ya da last_seen günceller."""
        try:
            with self._get_conn() as conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO devices (user_id, device_id, device_type, last_seen)
                            VALUES (%s, %s, %s, now())
                            ON CONFLICT (device_id) DO UPDATE
                                SET last_seen = now(), user_id = EXCLUDED.user_id
                        """, (user_id, device_id, device_type))
                    conn.commit()
                    return True
                except Exception:
                    conn.rollback()
                    raise
        except Exception as e:
            logger.error(f"Upsert device hatası: {e}")
            return False

    def get_paired_devices(self, user_id: int, pc_device_id: str) -> list[dict]:
        """
        Bu kullanıcının PC'siyle eşleşmiş tüm telefonları döner.
        Dönüş: [{"device_id": str, "last_seen": datetime | None}]
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("""
                        SELECT p.phone_device_id AS device_id,
                               d.last_seen
                        FROM pairings p
                        LEFT JOIN devices d ON d.device_id = p.phone_device_id
                        WHERE p.user_id = %s AND p.pc_device_id = %s
                        ORDER BY d.last_seen DESC NULLS LAST
                    """, (user_id, pc_device_id))
                    rows = cur.fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"get_paired_devices hatası: {e}")
            return []

    # ─── Pairing ──────────────────────────────────────────────────────────────

    def save_pairing(self, user_id: int, phone_device_id: str, pc_device_id: str) -> bool:
        """Eşleşmeyi DB'ye kaydeder (idempotent)."""
        try:
            with self._get_conn() as conn:
                try:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO pairings (user_id, phone_device_id, pc_device_id)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (phone_device_id, pc_device_id) DO NOTHING
                        """, (user_id, phone_device_id, pc_device_id))
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

    def get_device_last_seen(self, device_id: str) -> Optional[datetime]:
        """Bir cihazın son görülme zamanını döner."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT last_seen FROM devices WHERE device_id = %s",
                        (device_id,)
                    )
                    row = cur.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"get_device_last_seen hatası: {e}")
            return None
