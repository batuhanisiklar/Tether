import logging
import os
from contextlib import contextmanager

import bcrypt
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

DB_URL = os.environ.get(
    "NEON_DB_URL",
    "postgresql://neondb_owner:npg_Y3JevV2SsERI@ep-crimson-sun-anqdvhsy-pooler.c-6.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
)

SCHEMA_SQL = """
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


class ServerDbClient:
    def __init__(self, db_url: str = DB_URL):
        self._pool = ThreadedConnectionPool(1, 10, db_url)

    @contextmanager
    def _get_conn(self):
        conn = self._pool.getconn()
        conn.autocommit = False
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    def close(self):
        self._pool.closeall()

    def init_schema(self) -> bool:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(SCHEMA_SQL)
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
                    cur.execute("""
                        UPDATE pairings p
                        SET user_id = d.user_id
                        FROM devices d
                        WHERE p.user_id IS NULL AND d.device_id = p.phone_device_id
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_pairings_user_phone
                        ON pairings(user_id, phone_device_id)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_pairings_user_pc
                        ON pairings(user_id, pc_device_id)
                    """)
                conn.commit()
            return True
        except Exception as exc:
            logger.error("Schema init hatasi: %s", exc)
            return False

    def register_user(self, username: str, password: str) -> tuple[bool, str]:
        normalized = username.strip().lower()
        if len(normalized) < 3:
            return False, "Kullanici adi en az 3 karakter olmali."
        if len(password) < 6:
            return False, "Sifre en az 6 karakter olmali."

        try:
            password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
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
                            (normalized, password_hash),
                        )
                    conn.commit()
                    return True, "Kayit basarili."
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                    return False, "Bu kullanici adi zaten kullanimda."
        except Exception as exc:
            logger.error("Register hatasi: %s", exc)
            return False, "Kayit sirasinda bir hata olustu."

    def authenticate_user(self, username: str, password: str) -> tuple[int, str, str] | None:
        normalized = username.strip().lower()
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, username, address, password_h FROM users WHERE username = %s",
                        (normalized,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    user_id, stored_username, address, password_hash = row
                    if not bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8")):
                        return None
                    if address is None:
                        address = str(111111111110 + user_id)
                        cur.execute(
                            "UPDATE users SET address = %s WHERE id = %s AND address IS NULL",
                            (address, user_id),
                        )
                        conn.commit()
                    return user_id, stored_username, address or ""
        except Exception as exc:
            logger.error("Auth hatasi: %s", exc)
            return None

    def get_user_profile(self, user_id: int) -> dict | None:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        "SELECT id, username, address FROM users WHERE id = %s",
                        (user_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None
                    result = dict(row)
                    if result.get("address") is None:
                        new_address = str(111111111110 + user_id)
                        cur.execute(
                            "UPDATE users SET address = %s WHERE id = %s AND address IS NULL",
                            (new_address, user_id),
                        )
                        conn.commit()
                        result["address"] = new_address
            return result
        except Exception as exc:
            logger.error("Profil alma hatasi: %s", exc)
            return None

    def upsert_device(
        self,
        user_id: int,
        device_id: str,
        device_type: str,
        device_name: str | None = None,
    ) -> bool:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT user_id FROM devices WHERE device_id = %s",
                        (device_id,),
                    )
                    existing_row = cur.fetchone()
                    previous_user_id = existing_row[0] if existing_row else None
                    if previous_user_id is not None and previous_user_id != user_id:
                        cur.execute(
                            """
                            DELETE FROM pairings
                            WHERE phone_device_id = %s OR pc_device_id = %s
                            """,
                            (device_id, device_id),
                        )
                    cur.execute(
                        """
                        INSERT INTO devices (user_id, device_id, device_type, device_name)
                        VALUES (%s, %s, %s, NULLIF(%s, ''))
                        ON CONFLICT (device_id) DO UPDATE
                            SET user_id = EXCLUDED.user_id,
                                device_type = EXCLUDED.device_type,
                                device_name = COALESCE(EXCLUDED.device_name, devices.device_name)
                        RETURNING device_id
                        """,
                        (user_id, device_id, device_type, device_name),
                    )
                    if cur.fetchone() is None:
                        conn.rollback()
                        return False
                conn.commit()
            return True
        except Exception as exc:
            logger.error("Device upsert hatasi: %s", exc)
            return False

    def reset_all_online(self) -> None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE devices SET is_online = false WHERE is_online = true")
                conn.commit()
        except Exception as exc:
            logger.error("reset_all_online hatasi: %s", exc)

    def set_device_online(self, device_id: str, is_online: bool) -> None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE devices SET is_online = %s WHERE device_id = %s",
                        (is_online, device_id),
                    )
                conn.commit()
        except Exception as exc:
            logger.error("set_device_online hatasi: %s", exc)

    def get_account_partner_devices(self, device_id: str) -> list[str]:
        return self.get_account_partner_devices_map([device_id]).get(device_id, [])

    def get_account_partner_devices_map(self, device_ids: list[str]) -> dict[str, list[str]]:
        if not device_ids:
            return {}

        unique_ids = list(dict.fromkeys(device_ids))
        result: dict[str, list[str]] = {device_id: [] for device_id in unique_ids}
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT device_id, user_id, device_type
                        FROM devices
                        WHERE device_id = ANY(%s)
                        """,
                        (unique_ids,),
                    )
                    owner_rows = [dict(row) for row in cur.fetchall()]
                    owner_by_id = {row["device_id"]: row for row in owner_rows}
                    user_ids = list({row["user_id"] for row in owner_rows if row.get("user_id") is not None})
                    if not user_ids:
                        return result

                    cur.execute(
                        """
                        SELECT device_id, user_id, device_type, is_online
                        FROM devices
                        WHERE user_id = ANY(%s)
                        ORDER BY is_online DESC, device_name ASC NULLS LAST, id DESC
                        """,
                        (user_ids,),
                    )
                    devices_by_user: dict[int, list[dict]] = {}
                    for row in cur.fetchall():
                        item = dict(row)
                        devices_by_user.setdefault(item["user_id"], []).append(item)

            for device_id in unique_ids:
                owner = owner_by_id.get(device_id)
                if not owner:
                    continue
                opposite_type = "phone" if owner["device_type"] == "pc" else "pc"
                candidates = devices_by_user.get(owner["user_id"], [])
                result[device_id] = [
                    candidate["device_id"]
                    for candidate in candidates
                    if candidate["device_type"] == opposite_type and candidate["device_id"] != device_id
                ]
            return result
        except Exception as exc:
            logger.error("Hesap karsi cihazlari listeleme hatasi: %s", exc)
            return result

    def get_paired_partners(self, device_id: str) -> list[str]:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        WITH owner AS (
                            SELECT user_id
                            FROM devices
                            WHERE device_id = %s
                            LIMIT 1
                        )
                        SELECT pc_device_id AS partner_id
                        FROM pairings
                        WHERE phone_device_id = %s
                          AND user_id = (SELECT user_id FROM owner)
                        UNION
                        SELECT phone_device_id AS partner_id
                        FROM pairings
                        WHERE pc_device_id = %s
                          AND user_id = (SELECT user_id FROM owner)
                        """,
                        (device_id, device_id, device_id),
                    )
                    rows = cur.fetchall()
            return [row[0] for row in rows]
        except Exception as exc:
            logger.error("Partner listeleme hatasi: %s", exc)
            return []

    def get_paired_partners_map(self, device_ids: list[str]) -> dict[str, list[str]]:
        if not device_ids:
            return {}

        unique_ids = list(dict.fromkeys(device_ids))
        result: dict[str, list[str]] = {device_id: [] for device_id in unique_ids}
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        WITH owners AS (
                            SELECT device_id, user_id
                            FROM devices
                            WHERE device_id = ANY(%s)
                        )
                        SELECT p.phone_device_id AS device_id, p.pc_device_id AS partner_id
                        FROM pairings p
                        JOIN owners o ON o.device_id = p.phone_device_id AND o.user_id = p.user_id
                        UNION ALL
                        SELECT p.pc_device_id AS device_id, p.phone_device_id AS partner_id
                        FROM pairings p
                        JOIN owners o ON o.device_id = p.pc_device_id AND o.user_id = p.user_id
                        """,
                        (unique_ids,),
                    )
                    for device_id, partner_id in cur.fetchall():
                        if partner_id not in result.setdefault(device_id, []):
                            result[device_id].append(partner_id)
            return result
        except Exception as exc:
            logger.error("Toplu partner listeleme hatasi: %s", exc)
            return result

    def user_owns_device(self, user_id: int, device_id: str) -> bool:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT 1
                        FROM devices
                        WHERE user_id = %s AND device_id = %s
                        LIMIT 1
                        """,
                        (user_id, device_id),
                    )
                    return cur.fetchone() is not None
        except Exception as exc:
            logger.error("Cihaz sahiplik kontrolu hatasi: %s", exc)
            return False

    def save_pairing_by_device_ids(self, first_device_id: str, second_device_id: str) -> bool:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT device_id, user_id, device_type
                        FROM devices
                        WHERE device_id IN (%s, %s)
                        """,
                        (first_device_id, second_device_id),
                    )
                    rows = {row["device_id"]: row for row in cur.fetchall()}

                    first = rows.get(first_device_id)
                    second = rows.get(second_device_id)
                    first_user_id = first.get("user_id") if first else None
                    second_user_id = second.get("user_id") if second else None
                    user_id = first_user_id or second_user_id
                    if user_id is None:
                        logger.warning("Pairing kaydedilemedi; cihaz sahipleri bulunamadi: %s %s", first_device_id, second_device_id)
                        conn.rollback()
                        return False
                    if first_user_id and second_user_id and first_user_id != second_user_id:
                        logger.warning(
                            "Farkli hesap cihazlari eslestirilmeye calisildi: %s(%s) %s(%s)",
                            first_device_id,
                            first_user_id,
                            second_device_id,
                            second_user_id,
                        )
                        conn.rollback()
                        return False

                    phone_device_id, pc_device_id = self._resolve_pair_ids(first_device_id, second_device_id, first, second)
                    cur.execute(
                        """
                        DELETE FROM pairings
                        WHERE phone_device_id = %s AND pc_device_id = %s AND COALESCE(user_id, -1) <> %s
                        """,
                        (phone_device_id, pc_device_id, user_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO pairings (user_id, phone_device_id, pc_device_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (phone_device_id, pc_device_id) DO UPDATE
                            SET user_id = EXCLUDED.user_id
                        """,
                        (user_id, phone_device_id, pc_device_id),
                    )
                conn.commit()
            return True
        except Exception as exc:
            logger.error("Pairing kaydetme hatasi: %s", exc)
            return False

    def get_user_devices(self, user_id: int) -> list[dict]:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT device_id, device_type, device_name, is_online
                        FROM devices
                        WHERE user_id = %s
                        ORDER BY is_online DESC, device_name ASC NULLS LAST
                        """,
                        (user_id,),
                    )
                    return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.error("Cihaz listeleme hatasi: %s", exc)
            return []

    def get_device_pairings(self, device_id: str) -> list[dict]:
        query = """
            WITH current_owner AS (
                SELECT user_id
                FROM devices
                WHERE device_id = %(device_id)s
                LIMIT 1
            )
            SELECT counterpart.device_id, counterpart.device_type, counterpart.device_name,
                   counterpart.is_online, owner_user.address
            FROM pairings p
            JOIN devices counterpart
              ON counterpart.device_id = CASE
                    WHEN p.phone_device_id = %(device_id)s THEN p.pc_device_id
                    ELSE p.phone_device_id
                 END
            LEFT JOIN users owner_user ON owner_user.id = counterpart.user_id
            WHERE (p.phone_device_id = %(device_id)s OR p.pc_device_id = %(device_id)s)
              AND p.user_id = (SELECT user_id FROM current_owner)
            ORDER BY counterpart.is_online DESC, counterpart.device_name ASC NULLS LAST
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(query, {"device_id": device_id})
                    return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.error("Pairings listeleme hatasi: %s", exc)
            return []

    def find_phone_device_by_address(self, address: str) -> str | None:
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
        except Exception as exc:
            logger.error("Address ile phone cihaz bulma hatasi: %s", exc)
            return None

    def delete_pairing_by_device_ids(self, first_device_id: str, second_device_id: str) -> bool:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT device_id, device_type, user_id
                        FROM devices
                        WHERE device_id IN (%s, %s)
                        """,
                        (first_device_id, second_device_id),
                    )
                    rows = {row["device_id"]: row for row in cur.fetchall()}
                    first = rows.get(first_device_id)
                    second = rows.get(second_device_id)
                    user_id = (first.get("user_id") if first else None) or (second.get("user_id") if second else None)
                    if user_id is None:
                        conn.rollback()
                        return False
                    phone_device_id, pc_device_id = self._resolve_pair_ids(first_device_id, second_device_id, first, second)
                    cur.execute(
                        """
                        DELETE FROM pairings
                        WHERE phone_device_id = %s AND pc_device_id = %s AND user_id = %s
                        """,
                        (phone_device_id, pc_device_id, user_id),
                    )
                conn.commit()
            return True
        except Exception as exc:
            logger.error("Pairing silme hatasi: %s", exc)
            return False

    @staticmethod
    def _resolve_pair_ids(
        first_device_id: str,
        second_device_id: str,
        first_row: dict | None,
        second_row: dict | None,
    ) -> tuple[str, str]:
        def role_of(device_id: str, row: dict | None) -> str:
            if row and row.get("device_type") in {"phone", "pc"}:
                return row["device_type"]
            if device_id.startswith("phone-"):
                return "phone"
            return "pc"

        first_role = role_of(first_device_id, first_row)
        second_role = role_of(second_device_id, second_row)
        if first_role == "phone" and second_role == "pc":
            return first_device_id, second_device_id
        if first_role == "pc" and second_role == "phone":
            return second_device_id, first_device_id
        if first_device_id.startswith("phone-") or second_role == "pc":
            return first_device_id, second_device_id
        return second_device_id, first_device_id
