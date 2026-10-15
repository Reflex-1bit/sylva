"""
Sylva-wild: protect a small free API key.

- AnswerCache: answers are kept in memory for an hour, keyed by the onboarding
  answers, so a repeated question makes no model call.
- RateLimiter: each client gets a number of model-backed answers per window;
  past it they still get search results, without the model.

Both live in process memory, so they reset on restart and are per instance.
"""

import threading
import time
from collections import OrderedDict, deque
from typing import Callable, Optional

CACHE_TTL_S = 3600
CACHE_MAX = 500
RATE_LIMIT = 10
RATE_WINDOW_S = 600


def cache_key(intent: str, sector: Optional[str], problem: str) -> tuple:
    return (intent, sector or "", " ".join(problem.lower().split()))


class AnswerCache:
    def __init__(self, ttl_s: float = CACHE_TTL_S, max_items: int = CACHE_MAX,
                 clock: Callable[[], float] = time.monotonic):
        self.ttl_s, self.max_items, self.clock = ttl_s, max_items, clock
        self._items: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> Optional[dict]:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            stored, value = item
            if self.clock() - stored > self.ttl_s:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return value

    def put(self, key: tuple, value: dict) -> None:
        with self._lock:
            self._items[key] = (self.clock(), value)
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class RateLimiter:
    def __init__(self, limit: int = RATE_LIMIT, window_s: float = RATE_WINDOW_S,
                 clock: Callable[[], float] = time.monotonic, max_clients: int = 10_000):
        self.limit, self.window_s, self.clock, self.max_clients = limit, window_s, clock, max_clients
        self._hits: OrderedDict[str, deque] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, client: str) -> bool:
        """Record one model-backed answer for `client` if it is under the limit."""
        now = self.clock()
        with self._lock:
            q = self._hits.setdefault(client, deque())
            self._hits.move_to_end(client)
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            while len(self._hits) > self.max_clients:
                self._hits.popitem(last=False)
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()
