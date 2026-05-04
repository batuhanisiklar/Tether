"""Session-state helpers extracted as public refactor anchors."""

from signaling_server.server import (
    _evict_stale_session_slots_for_device,
    _notify_paired,
    _prune_closed_peers_from_session,
    _session_entry,
    _session_peer_ws_only,
)

__all__ = [
    "_evict_stale_session_slots_for_device",
    "_notify_paired",
    "_prune_closed_peers_from_session",
    "_session_entry",
    "_session_peer_ws_only",
]
