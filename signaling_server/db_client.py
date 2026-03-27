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

CREATE TABLE IF NOT EXISTS user_devices (
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    device_id   TEXT REFERENCES devices(device_id) ON DELETE CASCADE,
    address     TEXT UNIQUE,
    is_online   BOOLEAN DEFAULT false,
    created_at  TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, device_id)
);

CREATE TABLE IF NOT EXISTS pairings (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    partner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    phone_device_id TEXT NOT NULL,
    pc_device_id    TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
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
                    cur.execute("CREATE SEQUENCE IF NOT EXISTS user_device_address_seq START 200000000000")
                    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT")
                    cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_name TEXT")
                    cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT false")
                    cur.execute("ALTER TABLE devices DROP COLUMN IF EXISTS last_seen")
                    cur.execute("ALTER TABLE user_devices ADD COLUMN IF NOT EXISTS address TEXT")
                    cur.execute("ALTER TABLE user_devices ADD COLUMN IF NOT EXISTS is_online BOOLEAN DEFAULT false")
                    cur.execute("ALTER TABLE pairings ADD COLUMN IF NOT EXISTS partner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
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
                    cur.execute("ALTER TABLE pairings DROP CONSTRAINT IF EXISTS pairings_phone_device_id_pc_device_id_key")
                    cur.execute("""
                        INSERT INTO user_devices (user_id, device_id, is_online)
                        SELECT d.user_id, d.device_id, COALESCE(d.is_online, false)
                        FROM devices d
                        WHERE d.user_id IS NOT NULL
                        ON CONFLICT (user_id, device_id) DO UPDATE
                            SET is_online = EXCLUDED.is_online
                    """)
                    cur.execute("""
                        SELECT setval(
                            'user_device_address_seq',
                            GREATEST(
                                COALESCE((SELECT MAX(address::bigint) FROM user_devices WHERE address ~ '^[0-9]{12}$'), 200000000000),
                                200000000000
                            ),
                            true
                        )
                    """)
                    cur.execute("""
                        UPDATE user_devices
                        SET address = nextval('user_device_address_seq')::text
                        WHERE address IS NULL OR address = ''
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_user_devices_device
                        ON user_devices(device_id)
                    """)
                    cur.execute("""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_user_devices_address
                        ON user_devices(address)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_user_devices_user_online
                        ON user_devices(user_id, is_online)
                    """)
                    cur.execute("""
                        DROP INDEX IF EXISTS idx_pairings_user_device_pair
                    """)
                    cur.execute("""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_pairings_user_device_pair
                        ON pairings(user_id, partner_user_id, phone_device_id, pc_device_id)
                    """)
                    cur.execute("""
                        UPDATE pairings p
                        SET user_id = d.user_id
                        FROM devices d
                        WHERE p.user_id IS NULL AND d.device_id = p.phone_device_id
                    """)
                    cur.execute("""
                        UPDATE pairings p
                        SET partner_user_id = counterpart_ud.user_id
                        FROM user_devices own_ud
                        JOIN user_devices counterpart_ud
                          ON counterpart_ud.device_id = CASE
                                WHEN own_ud.device_id = p.phone_device_id THEN p.pc_device_id
                                ELSE p.phone_device_id
                             END
                         AND counterpart_ud.user_id <> p.user_id
                        WHERE p.partner_user_id IS NULL
                          AND own_ud.user_id = p.user_id
                          AND own_ud.device_id IN (p.phone_device_id, p.pc_device_id)
                    """)
                    cur.execute("""
                        UPDATE pairings
                        SET partner_user_id = user_id
                        WHERE partner_user_id IS NULL
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

    def get_user_profile(self, user_id: int, device_id: str | None = None) -> dict | None:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    if device_id:
                        cur.execute(
                            """
                            SELECT u.id, u.username, COALESCE(ud.address, u.address) AS address
                            FROM users u
                            LEFT JOIN user_devices ud
                              ON ud.user_id = u.id AND ud.device_id = %s
                            WHERE u.id = %s
                            """,
                            (device_id, user_id),
                        )
                    else:
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
                        """
                        INSERT INTO devices (user_id, device_id, device_type, device_name, is_online)
                        VALUES (%s, %s, %s, NULLIF(%s, ''), false)
                        ON CONFLICT (device_id) DO UPDATE
                            SET device_type = EXCLUDED.device_type,
                                device_name = COALESCE(EXCLUDED.device_name, devices.device_name)
                        RETURNING device_id
                        """,
                        (user_id, device_id, device_type, device_name),
                    )
                    if cur.fetchone() is None:
                        conn.rollback()
                        return False
                    cur.execute(
                        """
                        INSERT INTO user_devices (user_id, device_id, address, is_online)
                        VALUES (%s, %s, nextval('user_device_address_seq')::text, false)
                        ON CONFLICT (user_id, device_id) DO UPDATE
                            SET address = COALESCE(user_devices.address, EXCLUDED.address),
                                is_online = user_devices.is_online
                        """,
                        (user_id, device_id),
                    )
                conn.commit()
            return True
        except Exception as exc:
            logger.error("Device upsert hatasi: %s", exc)
            return False

    def reset_all_online(self) -> None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("UPDATE user_devices SET is_online = false WHERE is_online = true")
                    cur.execute("UPDATE devices SET is_online = false WHERE is_online = true")
                conn.commit()
        except Exception as exc:
            logger.error("reset_all_online hatasi: %s", exc)

    def set_device_online(self, user_id: int, device_id: str, is_online: bool) -> None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE user_devices
                        SET is_online = %s
                        WHERE user_id = %s AND device_id = %s
                        """,
                        (is_online, user_id, device_id),
                    )
                    cur.execute(
                        """
                        UPDATE devices
                        SET is_online = EXISTS (
                            SELECT 1
                            FROM user_devices
                            WHERE device_id = %s AND is_online = true
                        )
                        WHERE device_id = %s
                        """,
                        (device_id, device_id),
                    )
                conn.commit()
        except Exception as exc:
            logger.error("set_device_online hatasi: %s", exc)

    def get_user_id_by_address(self, address: str) -> int | None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM users WHERE address = %s", (address,))
                    row = cur.fetchone()
            return row[0] if row else None
        except Exception as exc:
            logger.error("Address ile user id bulma hatasi: %s", exc)
            return None

    def get_user_device_address(self, user_id: int, device_id: str) -> str | None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT address
                        FROM user_devices
                        WHERE user_id = %s AND device_id = %s
                        LIMIT 1
                        """,
                        (user_id, device_id),
                    )
                    row = cur.fetchone()
            return row[0] if row else None
        except Exception as exc:
            logger.error("User device address alma hatasi: %s", exc)
            return None

    def get_device_binding_by_address(self, address: str) -> dict | None:
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT ud.user_id, ud.device_id, ud.address, ud.is_online,
                               d.device_type, d.device_name
                        FROM user_devices ud
                        JOIN devices d ON d.device_id = ud.device_id
                        WHERE ud.address = %s
                        LIMIT 1
                        """,
                        (address,),
                    )
                    row = cur.fetchone()
            return dict(row) if row else None
        except Exception as exc:
            logger.error("Address ile cihaz bagi bulma hatasi: %s", exc)
            return None

    def get_paired_partners(self, user_id: int, device_id: str) -> list[str]:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT pc_device_id AS partner_id
                        FROM pairings
                        WHERE user_id = %s AND phone_device_id = %s
                        UNION
                        SELECT phone_device_id AS partner_id
                        FROM pairings
                        WHERE user_id = %s AND pc_device_id = %s
                        """,
                        (user_id, device_id, user_id, device_id),
                    )
                    rows = cur.fetchall()
            return [row[0] for row in rows]
        except Exception as exc:
            logger.error("Partner listeleme hatasi: %s", exc)
            return []

    def get_paired_partners_map(self, user_id: int, device_ids: list[str]) -> dict[str, list[str]]:
        if not device_ids:
            return {}

        unique_ids = list(dict.fromkeys(device_ids))
        result: dict[str, list[str]] = {device_id: [] for device_id in unique_ids}
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT p.phone_device_id AS device_id, p.pc_device_id AS partner_id
                        FROM pairings p
                        WHERE p.user_id = %s AND p.phone_device_id = ANY(%s)
                        UNION ALL
                        SELECT p.pc_device_id AS device_id, p.phone_device_id AS partner_id
                        FROM pairings p
                        WHERE p.user_id = %s AND p.pc_device_id = ANY(%s)
                        """,
                        (user_id, unique_ids, user_id, unique_ids),
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
                        FROM user_devices
                        WHERE user_id = %s AND device_id = %s
                        LIMIT 1
                        """,
                        (user_id, device_id),
                    )
                    return cur.fetchone() is not None
        except Exception as exc:
            logger.error("Cihaz sahiplik kontrolu hatasi: %s", exc)
            return False

    def save_pairing_by_device_ids(
        self,
        user_id: int,
        first_device_id: str,
        second_device_id: str,
        partner_user_id: int | None = None,
    ) -> bool:
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
                    phone_device_id, pc_device_id = self._resolve_pair_ids(first_device_id, second_device_id, first, second)
                    cur.execute(
                        """
                        INSERT INTO pairings (user_id, partner_user_id, phone_device_id, pc_device_id)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id, partner_user_id, phone_device_id, pc_device_id) DO UPDATE
                            SET partner_user_id = EXCLUDED.partner_user_id
                        """,
                        (user_id, partner_user_id or user_id, phone_device_id, pc_device_id),
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
                        SELECT d.device_id, d.device_type, d.device_name, ud.is_online, ud.address
                        FROM user_devices ud
                        JOIN devices d ON d.device_id = ud.device_id
                        WHERE ud.user_id = %s
                        ORDER BY ud.is_online DESC, d.device_name ASC NULLS LAST
                        """,
                        (user_id,),
                    )
                    return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.error("Cihaz listeleme hatasi: %s", exc)
            return []

    def get_device_pairings(self, user_id: int, device_id: str) -> list[dict]:
        query = """
            SELECT counterpart.device_id, counterpart.device_type, counterpart.device_name,
                   counterpart_ud.is_online, counterpart_ud.address
            FROM pairings p
            JOIN devices counterpart
              ON counterpart.device_id = CASE
                    WHEN p.phone_device_id = %(device_id)s THEN p.pc_device_id
                    ELSE p.phone_device_id
                 END
            JOIN user_devices counterpart_ud
              ON counterpart_ud.user_id = COALESCE(p.partner_user_id, p.user_id)
             AND counterpart_ud.device_id = counterpart.device_id
            WHERE p.user_id = %(user_id)s
              AND (p.phone_device_id = %(device_id)s OR p.pc_device_id = %(device_id)s)
            ORDER BY counterpart_ud.is_online DESC, counterpart.device_name ASC NULLS LAST
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(query, {"user_id": user_id, "device_id": device_id})
                    return [dict(row) for row in cur.fetchall()]
        except Exception as exc:
            logger.error("Pairings listeleme hatasi: %s", exc)
            return []

    def get_user_recent_partner_devices(self, user_id: int, partner_type: str) -> list[dict]:
        query = """
            SELECT DISTINCT ON (counterpart_ud.address)
                   counterpart.device_id,
                   counterpart.device_type,
                   counterpart.device_name,
                   counterpart_ud.is_online,
                   counterpart_ud.address,
                   p.created_at
            FROM pairings p
            JOIN devices counterpart
              ON counterpart.device_id IN (p.phone_device_id, p.pc_device_id)
            JOIN user_devices counterpart_ud
              ON counterpart_ud.user_id = COALESCE(p.partner_user_id, p.user_id)
             AND counterpart_ud.device_id = counterpart.device_id
            WHERE p.user_id = %(user_id)s
              AND counterpart.device_type = %(partner_type)s
            ORDER BY counterpart_ud.address, p.created_at DESC
        """
        try:
            with self._get_conn() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(query, {"user_id": user_id, "partner_type": partner_type})
                    rows = [dict(row) for row in cur.fetchall()]
            rows.sort(key=lambda row: (not bool(row.get("is_online")), row.get("device_name") or "", row.get("address") or ""))
            return rows
        except Exception as exc:
            logger.error("Recent cihazlari listeleme hatasi: %s", exc)
            return []

    def find_phone_device_by_address(self, address: str) -> str | None:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.device_id
                        FROM user_devices ud
                        JOIN devices d ON d.device_id = ud.device_id
                        WHERE ud.address = %s AND d.device_type = 'phone'
                        ORDER BY ud.is_online DESC, d.id DESC
                        LIMIT 1
                        """,
                        (address,),
                    )
                    row = cur.fetchone()
            return row[0] if row else None
        except Exception as exc:
            logger.error("Address ile phone cihaz bulma hatasi: %s", exc)
            return None

    def get_device_ids_by_address(self, address: str, device_type: str) -> list[str]:
        try:
            with self._get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT d.device_id
                        FROM user_devices ud
                        JOIN devices d ON d.device_id = ud.device_id
                        WHERE ud.address = %s AND d.device_type = %s
                        ORDER BY ud.is_online DESC, d.id DESC
                        """,
                        (address, device_type),
                    )
                    rows = cur.fetchall()
            return [row[0] for row in rows]
        except Exception as exc:
            logger.error("Address ile cihaz bulma hatasi: %s", exc)
            return []

    def delete_pairing_by_device_ids(
        self,
        user_id: int,
        first_device_id: str,
        second_device_id: str,
        partner_address: str | None = None,
    ) -> bool:
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
                    phone_device_id, pc_device_id = self._resolve_pair_ids(first_device_id, second_device_id, first, second)
                    partner_user_id = user_id
                    if partner_address:
                        cur.execute(
                            "SELECT user_id FROM user_devices WHERE address = %s LIMIT 1",
                            (partner_address,),
                        )
                        partner_row = cur.fetchone()
                        if partner_row:
                            partner_user_id = partner_row["user_id"]
                    cur.execute(
                        """
                        DELETE FROM pairings
                        WHERE user_id = %s
                          AND partner_user_id = %s
                          AND phone_device_id = %s
                          AND pc_device_id = %s
                        """,
                        (user_id, partner_user_id, phone_device_id, pc_device_id),
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
