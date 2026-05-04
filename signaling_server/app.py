"""Application factory entry point.

The legacy `server.py` module still owns the implementation during the
incremental refactor. Import from this module in new deployments/tests.
"""

from signaling_server.server import create_app

__all__ = ["create_app"]
