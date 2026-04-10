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
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            try:
                conn.rollback()
            except Exception:
                pass
            self._pool.putconn(conn)

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
                            phone TEXT,
                            email TEXT NOT NULL UNIQUE,
                            password_h TEXT NOT NULL,
                            created_at TIMESTAMPTZ DEFAULT now()
                        );
                        """
                    )
                    # Migration safety: eski DB'lerde phone kolonu yoksa ekle.
                    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone TEXT")
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

    def register_user(
        self,
        email: str,
        password: str,
        first_name: str = '',
        last_name: str = '',
        phone: str | None = None,
    ) -> Optional[int]:
        password_h = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        phone_norm = (phone or "").strip() or None
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO users (first_name, last_name, phone, email, password_h)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING user_id
                        """,
                        (first_name, last_name, phone_norm, email, password_h)
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

    def update_user_profile(
        self,
        user_id: int,
        *,
        email: str | None = None,
        phone: str | None = None,
        new_password: str | None = None,
        old_password: str | None = None,
    ) -> tuple[bool, str]:
        """
        Kullanıcı profil alanlarını günceller.
        - email UNIQUE olduğu için çakışma olursa hata döner.
        - Boş string gelirse ilgili alanı temizler (phone için None/'' -> NULL).
        """
        if user_id <= 0:
            return False, "Gecersiz kullanici."

        email_norm = (email or "").strip().lower() if email is not None else None
        phone_norm = (phone or "").strip() if phone is not None else None
        if phone_norm is not None and not phone_norm:
            phone_norm = None
        password_norm = (new_password or "").strip() if new_password is not None else None
        if password_norm is not None and len(password_norm) < 6:
            return False, "Sifre en az 6 karakter olmali."
        old_norm = (old_password or "").strip() if old_password is not None else None
        if password_norm is not None and not old_norm:
            return False, "Mevcut sifre gerekli."

        fields: list[str] = []
        values: list[Any] = []
        if email_norm is not None:
            fields.append("email = %s")
            values.append(email_norm)
        if phone is not None:
            fields.append("phone = %s")
            values.append(phone_norm)
        if password_norm is not None:
            # Eski sifreyi dogrula
            try:
                with self._get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT password_h FROM users WHERE user_id = %s", (int(user_id),))
                        row = cur.fetchone()
                        if not row:
                            return False, "Kullanici bulunamadi."
                        current_h = str(row[0] or "")
                        if not current_h or not bcrypt.checkpw(old_norm.encode(), current_h.encode()):
                            return False, "Mevcut sifre hatali."
            except Exception as e:
                logger.exception("update_user_profile password verify: %s", e)
                return False, "Sifre dogrulanamadi."

            password_h = bcrypt.hashpw(password_norm.encode(), bcrypt.gensalt()).decode()
            fields.append("password_h = %s")
            values.append(password_h)

        if not fields:
            return True, ""

        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE users SET {', '.join(fields)} WHERE user_id = %s",
                        tuple(values + [int(user_id)]),
                    )
                conn.commit()
            return True, ""
        except psycopg2.IntegrityError:
            logger.info("update_user_profile: email conflict for user_id=%s email=%s", user_id, email_norm)
            return False, "Bu e-posta zaten kayitli."
        except Exception as e:
            logger.exception("update_user_profile: %s", e)
            return False, "Profil guncellenemedi."

    def register_device(self, device_id: str, device_name: str, device_type: str, user_id: int, mac_address: str) -> bool:
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

    def create_connection(self, controller_device_id: str, target_device_id: str) -> bool:
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