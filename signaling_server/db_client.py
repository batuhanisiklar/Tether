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

def _resolve_db_url() -> str:
    """
    Render gibi platformlar genelde `DATABASE_URL` saglar.
    Projede geriye uyumluluk icin `NEON_DB_URL` da desteklenir.
    """
    db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not db_url:
        db_url = (os.environ.get("NEON_DB_URL") or "").strip()
    if not db_url:
        raise RuntimeError(
            "DB URL bulunamadi. Ortam degiskeni olarak `DATABASE_URL` (Render) veya `NEON_DB_URL` ayarlayin."
        )
    if "..." in db_url:
        raise RuntimeError(
            "DB URL gecersiz gorunuyor (icerikte '...' var). Render ortam degiskenlerini kontrol edin: `DATABASE_URL`/`NEON_DB_URL`."
        )
    return db_url

DB_URL: str | None = None

class ServerDbClient:
    def __init__(self, db_url: str | None = DB_URL):
        resolved = (db_url or "").strip() or _resolve_db_url()
        self._pool = ThreadedConnectionPool(1, 10, resolved)

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
                            created_at TIMESTAMPTZ DEFAULT now()
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS devices (
                            device_id TEXT PRIMARY KEY,
                            mac_address TEXT NOT NULL,
                            device_name TEXT NOT NULL DEFAULT '',
                            device_type TEXT NOT NULL CHECK (device_type IN ('phone', 'pc')),
                            is_online BOOLEAN DEFAULT FALSE,
                            last_seen TIMESTAMPTZ DEFAULT now(),
                            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE
                        );
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS connections (
                            id SERIAL PRIMARY KEY,
                            target_device_id TEXT NOT NULL,
                            controller_device_id TEXT NOT NULL,
                            created_at TIMESTAMPTZ DEFAULT now(),
                            FOREIGN KEY (target_device_id) REFERENCES devices(device_id) ON DELETE CASCADE,
                            FOREIGN KEY (controller_device_id) REFERENCES devices(device_id) ON DELETE CASCADE
                        );
                        """
                    )
                conn.commit()
            logger.info("DB semasi hazir")
            return True
        except Exception as e:
            logger.exception("init_schema: %s", e)
            return False

    # ─── Kullanıcı Yönetimi ───────────────────────────────────────────────────

    def register_user(self, email: str, password: str, first_name: str = '', last_name: str = '') -> Optional[int]:
        """Yeni kullanıcı kaydı oluşturur. Başarılıysa user_id döner."""
        password_h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users (first_name, last_name, email, password_h)
                        VALUES (%s, %s, %s, %s)
                        RETURNING user_id
                        """,
                        (first_name, last_name, email, password_h)
                    )
                    user_id = cur.fetchone()[0]
                conn.commit()
            return user_id
        except psycopg2.IntegrityError:
            logger.info("register_user: Duplicate entry for email %s", email)
            return None
        except Exception as e:
            logger.exception("register_user: %s", e)
            return None

    def authenticate_user(self, email: str, password: str) -> Optional[int]:
        """Kullanıcı e-posta/şifre doğrulaması. Başarılıysa user_id döner."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT user_id, password_h FROM users WHERE email = %s", (email,)
                    )
                    result = cur.fetchone()
                    if not result:
                        return None
                    user_id, password_h = result
                    if bcrypt.checkpw(password.encode(), password_h.encode()):
                        return user_id
            return None
        except Exception as e:
            logger.exception("authenticate_user: %s", e)
            return None

    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
                    return cur.fetchone()
        except Exception as e:
            logger.exception("get_user_by_id: %s", e)
            return None

    # ─── Cihaz Yönetimi ──────────────────────────────────────────────────────

    def register_device(self, device_id: str, device_name: str, device_type: str, user_id: int, mac_address: str) -> bool:
        """Yeni cihaz kaydı oluşturur. Başarılıysa True döner."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO devices (device_id, device_name, device_type, user_id, mac_address)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (device_id, device_name, device_type, user_id, mac_address)
                    )
                conn.commit()
            return True
        except psycopg2.IntegrityError:
            logger.info("register_device: Duplicate device_id %s", device_id)
            return False
        except Exception as e:
            logger.exception("register_device: %s", e)
            return False

    def set_device_online(self, device_id: str, is_online: bool) -> None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE devices
                        SET is_online = %s, last_seen = now()
                        WHERE device_id = %s
                        """,
                        (is_online, device_id)
                    )
                conn.commit()
        except Exception as e:
            logger.warning("set_device_online: %s", e)

    def get_device_by_id(self, device_id: str) -> Optional[dict]:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM devices WHERE device_id = %s", (device_id,))
                    return cur.fetchone()
        except Exception as e:
            logger.exception("get_device_by_id: %s", e)
            return None

    def get_devices_for_user(self, user_id: int) -> list[dict]:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM devices WHERE user_id = %s", (user_id,))
                    return cur.fetchall()
        except Exception as e:
            logger.exception("get_devices_for_user: %s", e)
            return []

    # ─── Bağlantı Sorguları ──────────────────────────────────────────────────

    def create_connection(self, controller_device_id: str, target_device_id: str) -> bool:
        """Yeni bağlantı kaydı oluşturur."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO connections (controller_device_id, target_device_id)
                        VALUES (%s, %s)
                        """,
                        (controller_device_id, target_device_id)
                    )
                conn.commit()
            return True
        except Exception as e:
            logger.exception("create_connection: %s", e)
            return False

    def delete_connection(self, controller_device_id: str, target_device_id: str) -> bool:
        """Belirli bir bağlantıyı siler."""
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM connections
                        WHERE controller_device_id = %s AND target_device_id = %s
                        """,
                        (controller_device_id, target_device_id)
                    )
                conn.commit()
            return True
        except Exception as e:
            logger.exception("delete_connection: %s", e)
            return False

    def get_connected_devices_as_controller(self, my_device_id: str) -> list[str]:
        """
        Controller (kontrol eden) olarak bu cihazın bağlantı kurduğu hedef cihazlarının id'lerini döndürür.
        Sadece connections tablosuna bakar.
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT target_device_id FROM connections
                        WHERE controller_device_id = %s
                        """, (my_device_id,)
                    )
                    return [row['target_device_id'] for row in cur.fetchall()]
        except Exception as e:
            logger.exception("get_connected_devices_as_controller: %s", e)
            return []

    def get_connected_devices_as_target(self, my_device_id: str) -> list[str]:
        """
        Target (hedef) olarak bu cihazın bağlantılı olduğu controller cihazlarının id'lerini döndürür.
        Sadece connections tablosuna bakar.
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT controller_device_id FROM connections
                        WHERE target_device_id = %s
                        """, (my_device_id,)
                    )
                    return [row['controller_device_id'] for row in cur.fetchall()]
        except Exception as e:
            logger.exception("get_connected_devices_as_target: %s", e)
            return []

    def get_all_connections_for_device(self, device_id: str) -> list[dict]:
        """
        Bu cihazın controller olduğu veya hedef olduğu tüm bağlantı kayıtlarını döndür.
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT * FROM connections
                        WHERE controller_device_id = %s OR target_device_id = %s
                        """, (device_id, device_id)
                    )
                    return cur.fetchall()
        except Exception as e:
            logger.exception("get_all_connections_for_device: %s", e)
            return []

    def connection_exists(self, controller_device_id: str, target_device_id: str) -> bool:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM connections WHERE controller_device_id = %s AND target_device_id = %s",
                        (controller_device_id, target_device_id)
                    )
                    return cur.fetchone() is not None
        except Exception as e:
            logger.exception("connection_exists: %s", e)
            return False