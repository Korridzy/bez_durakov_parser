from collections import OrderedDict
from typing import Dict
import time

MAX_SESSIONS = 1024
SESSION_TTL_SECONDS = 3600


class SessionStore:
    """LRU + TTL bounded session cache."""

    def __init__(self, max_size: int = MAX_SESSIONS, ttl: float = float(SESSION_TTL_SECONDS)):
        self._store: OrderedDict = OrderedDict()
        self._accessed: Dict[str, float] = {}
        self._max_size = max_size
        self._ttl = ttl

    def _expired(self, session_id: str) -> bool:
        return time.monotonic() - self._accessed.get(session_id, 0.0) > self._ttl

    def __contains__(self, session_id: object) -> bool:
        if not isinstance(session_id, str) or session_id not in self._store:
            return False
        if self._expired(session_id):
            self._drop(session_id)
            return False
        return True

    def __getitem__(self, session_id: str):
        if session_id not in self._store:
            raise KeyError(session_id)
        if self._expired(session_id):
            self._drop(session_id)
            raise KeyError(session_id)
        self._store.move_to_end(session_id)
        self._accessed[session_id] = time.monotonic()
        return self._store[session_id]

    def __setitem__(self, session_id: str, value) -> None:
        if session_id in self._store:
            self._store.move_to_end(session_id)
        elif len(self._store) >= self._max_size:
            oldest, _ = self._store.popitem(last=False)
            self._accessed.pop(oldest, None)
        self._store[session_id] = value
        self._accessed[session_id] = time.monotonic()

    def _drop(self, session_id: str) -> None:
        self._store.pop(session_id, None)
        self._accessed.pop(session_id, None)
