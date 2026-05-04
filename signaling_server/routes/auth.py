"""Auth route handlers.

Handlers are re-exported from the legacy server module while behavior is kept
stable during the first refactor step.
"""

from signaling_server.server import auth_login, auth_me, auth_profile_update, auth_register

__all__ = ["auth_login", "auth_me", "auth_profile_update", "auth_register"]
