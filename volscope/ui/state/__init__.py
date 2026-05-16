"""Single Source of Truth for VolScope UI state.

See store.py for the AppState dataclass and accessor API.
"""
from volscope.ui.state.store import (
    AppState,
    get_state,
    hydrate_from_url,
    push_history,
    set_ticker,
    sync_to_url,
)

__all__ = [
    "AppState",
    "get_state",
    "hydrate_from_url",
    "push_history",
    "set_ticker",
    "sync_to_url",
]
