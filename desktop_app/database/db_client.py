from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import psycopg2
from psycopg2 import sql

from desktop_app.config.constants import Prefs

logger = logging.getLogger(__name__)


def _normalize_device_id(raw_value: str | None) -> str:
    if not raw_value:
        return ""
    return "".join(ch for ch in str(raw_value) if ch.isdigit())[:12]


def _ordered_pair(first_device_id: str, second_device_id: str) -> tuple[str, str]:
    left, right = first_device_id, second_device_id
    if left > right:
        left, right = right, left
    return left, right


class DbClient:
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or Prefs.DB_URL
        self._conn: Any = None

    def _connect(self) -> Any:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self._dsn)
        return self._conn

    def close(self) -> None:
        if self._conn and not self._conn.closed:
            try:
                self._conn.close()
            except Exception:
                logger.exception("db close error")
        self._conn = None

    @staticmethod
    def _table_columns(cur, table_name: str) -> set[str]:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            (table_name,),
        )
        return {str(row[0]) for row in cur.fetchall()}

    @staticmethod
    def _pairing_columns(pairing_cols: set[str]) -> tuple[str, str] | None:
        if {"phone_device_id", "pc_device_id"}.issubset(pairing_cols):
            return "phone_device_id", "pc_device_id"
        if {"controller_device_id", "target_device_id"}.issubset(pairing_cols):
            return "controller_device_id", "target_device_id"
        return None

    def init_schema(self) -> bool:
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                # Base tables
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS devices (
                        user_id BIGINT NOT NULL,
                        device_id TEXT NOT NULL,
                        device_type TEXT NOT NULL,
                        device_name TEXT,
                        PRIMARY KEY (user_id, device_id)
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pairings (
                        phone_device_id TEXT NOT NULL,
                        pc_device_id TEXT NOT NULL
                    );
                    """
                )

                # Migration safety: eksik kolonlari ekle.
                cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_name TEXT")
                cur.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ DEFAULT NOW()")
                cur.execute("ALTER TABLE pairings ADD COLUMN IF NOT EXISTS phone_device_id TEXT")
                cur.execute("ALTER TABLE pairings ADD COLUMN IF NOT EXISTS pc_device_id TEXT")
                cur.execute("ALTER TABLE pairings ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ DEFAULT NOW()")

                # Uyum icin controller/target kolonlari varsa phone/pc'ye backfill dene.
                pairing_cols = self._table_columns(cur, "pairings")
                if {"controller_device_id", "target_device_id"}.issubset(pairing_cols):
                    cur.execute(
                        """
                        UPDATE pairings
                        SET
                            phone_device_id = COALESCE(phone_device_id, LEAST(controller_device_id, target_device_id)),
                            pc_device_id = COALESCE(pc_device_id, GREATEST(controller_device_id, target_device_id))
                        WHERE
                            (phone_device_id IS NULL OR pc_device_id IS NULL)
                            AND controller_device_id IS NOT NULL
                            AND target_device_id IS NOT NULL
                        """
                    )

                cur.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_pairings_phone_pc
                    ON pairings (phone_device_id, pc_device_id)
                    """
                )
            conn.commit()
            return True
        except Exception as exc:
            logger.error("init_schema: %s", exc)
            try:
                conn.rollback()
            except Exception:
                pass
            return False

    def upsert_device(
        self,
        user_id: int,
        device_id: str,
        device_type: str,
        device_name: str | None = None,
    ) -> bool:
        normalized_device_id = _normalize_device_id(device_id) or str(device_id).strip()
        if user_id <= 0 or not normalized_device_id:
            return False
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                device_cols = self._table_columns(cur, "devices")
                has_last_seen = "last_seen" in device_cols
                has_device_name = "device_name" in device_cols

                insert_cols = ["user_id", "device_id", "device_type"]
                values = [user_id, normalized_device_id, device_type]
                if has_device_name:
                    insert_cols.append("device_name")
                    values.append(device_name)
                if has_last_seen:
                    insert_cols.append("last_seen")
                    values.append(datetime.now(timezone.utc))

                update_sql_parts: list[sql.Composable] = [
                    sql.SQL("device_type = %s"),
                ]
                update_values: list[Any] = [device_type]
                if has_device_name:
                    update_sql_parts.append(sql.SQL("device_name = COALESCE(%s, device_name)"))
                    update_values.append(device_name)
                if has_last_seen:
                    update_sql_parts.append(sql.SQL("last_seen = NOW()"))

                # Bazı eski veritabanlarında (user_id, device_id) unique/PK kısıtı yok.
                # ON CONFLICT kullanmak yerine önce UPDATE, sonra gerekirse INSERT ile güvenli upsert yap.
                update_query = sql.SQL(
                    "UPDATE devices SET {updates} WHERE user_id = %s AND device_id = %s"
                ).format(
                    updates=sql.SQL(", ").join(update_sql_parts),
                )
                cur.execute(update_query, tuple(update_values + [user_id, normalized_device_id]))
                if cur.rowcount == 0:
                    insert_query = sql.SQL(
                        "INSERT INTO devices ({cols}) VALUES ({vals})"
                    ).format(
                        cols=sql.SQL(", ").join(sql.Identifier(c) for c in insert_cols),
                        vals=sql.SQL(", ").join(sql.Placeholder() for _ in insert_cols),
                    )
                    try:
                        cur.execute(insert_query, tuple(values))
                    except Exception:
                        # Yarış durumunda arada başka süreç INSERT etmiş olabilir; tekrar UPDATE dene.
                        cur.execute(update_query, tuple(update_values + [user_id, normalized_device_id]))
            conn.commit()
            return True
        except Exception as exc:
            logger.error("upsert_device: %s", exc)
            try:
                conn.rollback()
            except Exception:
                pass
            return False

    def get_user_address(self, user_id: int) -> str | None:
        if user_id <= 0:
            return None
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                device_cols = self._table_columns(cur, "devices")
                order_by = "last_seen DESC NULLS LAST, device_id DESC" if "last_seen" in device_cols else "device_id DESC"
                cur.execute(
                    f"""
                    SELECT device_id
                    FROM devices
                    WHERE user_id = %s AND device_type = 'pc'
                    ORDER BY {order_by}
                    LIMIT 1
                    """,
                    (user_id,),
                )
                row = cur.fetchone()
            return _normalize_device_id(str(row[0])) if row else None
        except Exception as exc:
            logger.error("get_user_address: %s", exc)
            return None

    def get_paired_devices(self, local_device_id: str) -> list[dict[str, Any]]:
        normalized_local_id = _normalize_device_id(local_device_id) or str(local_device_id).strip()
        if not normalized_local_id:
            return []

        paired_devices: list[dict[str, Any]] = []
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                pairing_cols = self._table_columns(cur, "pairings")
                pair_cols = self._pairing_columns(pairing_cols)
                if pair_cols is None:
                    return []

                col_left, col_right = pair_cols
                has_last_seen = "last_seen" in pairing_cols
                select_last_seen = ", last_seen" if has_last_seen else ""
                cur.execute(
                    f"""
                    SELECT {col_left}, {col_right}{select_last_seen}
                    FROM pairings
                    WHERE {col_left} = %s OR {col_right} = %s
                    """,
                    (normalized_local_id, normalized_local_id),
                )
                rows = cur.fetchall()

            for row in rows:
                first_id = _normalize_device_id(str(row[0])) or str(row[0]).strip()
                second_id = _normalize_device_id(str(row[1])) or str(row[1]).strip()
                if first_id == normalized_local_id:
                    partner_id = second_id
                elif second_id == normalized_local_id:
                    partner_id = first_id
                else:
                    continue
                if partner_id == normalized_local_id:
                    continue

                seen_at = row[2] if len(row) > 2 else None
                if seen_at and getattr(seen_at, "tzinfo", None) is None:
                    seen_at = seen_at.replace(tzinfo=timezone.utc)

                paired_devices.append(
                    {
                        "device_id": partner_id,
                        "address": partner_id,
                        "is_online": False,
                        "last_seen": seen_at.isoformat() if seen_at else None,
                    }
                )
            return paired_devices
        except Exception as exc:
            logger.error("get_paired_devices: %s", exc)
            return []

    def save_pairing(self, first_device_id: str, second_device_id: str) -> bool:
        left_id = _normalize_device_id(first_device_id) or str(first_device_id).strip()
        right_id = _normalize_device_id(second_device_id) or str(second_device_id).strip()
        if not left_id or not right_id or left_id == right_id:
            return False
        ordered_left_id, ordered_right_id = _ordered_pair(left_id, right_id)

        try:
            conn = self._connect()
            with conn.cursor() as cur:
                pairing_cols = self._table_columns(cur, "pairings")
                pair_cols = self._pairing_columns(pairing_cols)
                if pair_cols is None:
                    return False
                col_left, col_right = pair_cols
                has_last_seen = "last_seen" in pairing_cols

                if has_last_seen:
                    cur.execute(
                        f"""
                        INSERT INTO pairings ({col_left}, {col_right}, last_seen)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT ({col_left}, {col_right}) DO UPDATE SET
                            last_seen = NOW()
                        """,
                        (ordered_left_id, ordered_right_id),
                    )
                else:
                    cur.execute(
                        f"""
                        INSERT INTO pairings ({col_left}, {col_right})
                        VALUES (%s, %s)
                        ON CONFLICT ({col_left}, {col_right}) DO NOTHING
                        """,
                        (ordered_left_id, ordered_right_id),
                    )
            conn.commit()
            return True
        except Exception as exc:
            logger.error("save_pairing: %s", exc)
            try:
                conn.rollback()
            except Exception:
                pass
            return False

    def delete_pairing(self, partner_device_id: str, local_device_id: str) -> bool:
        partner_id = _normalize_device_id(partner_device_id) or str(partner_device_id).strip()
        self_id = _normalize_device_id(local_device_id) or str(local_device_id).strip()
        if not partner_id or not self_id:
            return False
        ordered_left_id, ordered_right_id = _ordered_pair(partner_id, self_id)

        try:
            conn = self._connect()
            with conn.cursor() as cur:
                pairing_cols = self._table_columns(cur, "pairings")
                pair_cols = self._pairing_columns(pairing_cols)
                if pair_cols is None:
                    return False
                col_left, col_right = pair_cols
                cur.execute(
                    f"DELETE FROM pairings WHERE {col_left} = %s AND {col_right} = %s",
                    (ordered_left_id, ordered_right_id),
                )
            conn.commit()
            return True
        except Exception as exc:
            logger.error("delete_pairing: %s", exc)
            try:
                conn.rollback()
            except Exception:
                pass
            return False
