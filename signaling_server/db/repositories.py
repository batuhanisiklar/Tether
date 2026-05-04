"""Repository refactor anchor.

Current query implementations remain on `ServerDbClient`. New repository
classes should be introduced here incrementally.
"""

from signaling_server.db_client import ServerDbClient

__all__ = ["ServerDbClient"]
