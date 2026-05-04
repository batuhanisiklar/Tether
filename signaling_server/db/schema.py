"""Schema initialization facade."""

from signaling_server.db_client import ServerDbClient


def init_schema(db: ServerDbClient) -> bool:
    return db.init_schema()


__all__ = ["init_schema"]
