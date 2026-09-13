"""Small in-memory report cache. No user analytics or credentials are written to Git/disk."""

from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
from datetime import datetime, timezone
from threading import RLock
import time


class ReportCache:
    def __init__(self, capacity=128, clock=time.monotonic):
        self.capacity, self.clock = capacity, clock
        self.entries = OrderedDict()
        self.pending = {}
        self.lock = RLock()

    def _purge(self):
        for key in list(self.entries):
            if self.entries[key][0] <= self.clock():
                del self.entries[key]

    def fetch(self, key, loader, ttl=300, refresh=False):
        with self.lock:
            self._purge()
            if key in self.entries and not refresh:
                self.entries.move_to_end(key)
                _, value, fetched = self.entries[key]
                return deepcopy(value), True, fetched
            future = self.pending.get(key)
            owner = future is None
            if owner:
                future = self.pending[key] = Future()
        if not owner:
            value, fetched = future.result()
            return deepcopy(value), True, fetched
        try:
            value = loader()
            fetched = datetime.now(timezone.utc).isoformat()
            with self.lock:
                self.entries[key] = (self.clock() + ttl, deepcopy(value), fetched)
                self.entries.move_to_end(key)
                while len(self.entries) > self.capacity:
                    self.entries.popitem(last=False)
            future.set_result((value, fetched))
            return value, False, fetched
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)

    def series(self, scope, start, end, loader, ttl=300, refresh=False):
        key = ("series", scope, start, end)
        # Daily and finer bucket boundaries are independent of the requested
        # date span. Weekly/monthly edge buckets can change: never slice them.
        with self.lock:
            self._purge()
            if not refresh and scope[-1] in {"minute", "dekaminute", "hour", "day"}:
                for existing, (_, value, fetched) in reversed(self.entries.items()):
                    if (existing[0] == "series" and existing[1] == scope
                            and existing[2] <= start and existing[3] >= end
                            and not value.get("sampled") and not value.get("contains_sensitive_data")):
                        sliced = deepcopy(value)
                        sliced["series"] = [row for row in sliced["series"]
                                            if start <= row["date"][:10] <= end]
                        return sliced, True, fetched
        return self.fetch(key, loader, ttl, refresh)
