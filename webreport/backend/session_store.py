"""Bounded index of live chat sessions.

The index stores recency timestamps only — never agents, never checkpoints.
Eviction is driven by the caller: it picks a victim, deletes the checkpoint
thread, and only then forgets the entry (delete-then-forget, spec D1).
"""
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from importlib import import_module
import sys
import time

# Parent of the mounted bd_shared directory, same convention as main.py:16
sys.path.insert(0, '/')

# bd_shared resolves only through the path bootstrap above, so it is imported
# dynamically rather than as a static resolution target.
_config = import_module("bd_shared.config")

MAX_SESSIONS = 1024


class SessionIndex:
    """Recency-ordered set of live session ids, bounded by the caller."""

    def __init__(
        self,
        max_size: int = MAX_SESSIONS,
        ttl: float = _config.CHECKPOINT_TTL_SECONDS,
    ):
        self._recency: "OrderedDict[str, float]" = OrderedDict()
        self._max_size: int = max_size
        self._ttl: float = ttl

    def __len__(self) -> int:
        return len(self._recency)

    @property
    def max_size(self) -> int:
        """Capacity the caller enforces before admitting a new session."""
        return self._max_size

    async def touch(self, session_id: str) -> None:
        """Admit the session id, or refresh the recency of one already indexed."""
        self._recency.pop(session_id, None)
        self._recency[session_id] = time.monotonic()

    async def is_live(self, session_id: str) -> bool:
        """Report whether the id is indexed and still inside its TTL."""
        stamp = self._recency.get(session_id)
        return stamp is not None and not self._is_expired(stamp)

    async def drop(self, session_id: str) -> None:
        """Forget the session id; unknown ids are ignored so retries stay safe."""
        self._recency.pop(session_id, None)

    async def expired_ids(self) -> list[str]:
        """List ids past their TTL, oldest first. Removal is left to the caller."""
        return [sid for sid, stamp in self._recency.items() if self._is_expired(stamp)]

    async def lru_victim(self, pinned: Mapping[str, int]) -> str | None:
        """Return the least recently touched unpinned id, or None when all are pinned.

        `pinned` is a refcount mapping: an id with a positive count has a request
        in flight and can never be evicted (spec D3).
        """
        for session_id in self._recency:
            if pinned.get(session_id, 0) <= 0:
                return session_id
        return None

    async def seed(self, newest_first_ids: Iterable[str]) -> None:
        """Install newest-first ids oldest-first, restarting the TTL clock (spec D7)."""
        for session_id in reversed(list(newest_first_ids)):
            await self.touch(session_id)

    def _is_expired(self, stamp: float) -> bool:
        return time.monotonic() - stamp > self._ttl
