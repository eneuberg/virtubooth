"""In-memory token buckets. Single process only (we run one uvicorn worker)."""

from __future__ import annotations

import math
import threading
import time


class RateLimiter:
    """`rate` events per `per` seconds, bursting up to `burst` (default: rate)."""

    def __init__(self, rate: int, per: float, burst: int | None = None) -> None:
        self.capacity = float(burst if burst is not None else rate)
        self.refill = rate / per
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def hit(self, key: str, cost: float = 1.0) -> bool:
        """Take `cost` tokens. False means the caller is over the limit."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            allowed = tokens >= cost
            if allowed:
                tokens -= cost
            self._buckets[key] = (tokens, now)
            if now - self._last_sweep > 300:
                self._sweep(now)
            return allowed

    def available(self, key: str, cost: float = 1.0) -> bool:
        """Whether `cost` tokens are there, without taking them."""
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            return min(self.capacity, tokens + (now - last) * self.refill) >= cost

    def retry_after(self, key: str, cost: float = 1.0) -> int:
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, time.monotonic()))
        missing = cost - min(self.capacity, tokens + (time.monotonic() - last) * self.refill)
        return max(1, math.ceil(missing / self.refill)) if missing > 0 else 0

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def _sweep(self, now: float) -> None:
        # drop buckets that have refilled completely; they carry no state
        full_after = self.capacity / self.refill
        self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < full_after}
        self._last_sweep = now
