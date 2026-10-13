"""In-memory token buckets. Single process only (we run one uvicorn worker)."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, fields

from ..settings import Settings


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


@dataclass
class Limits:
    upload_user: RateLimiter
    upload_ip: RateLimiter
    upload_global: RateLimiter
    new_user_ip: RateLimiter
    api_ip: RateLimiter
    api_guest: RateLimiter
    login_ip: RateLimiter
    login_ip_hourly: RateLimiter
    login_failures_global: RateLimiter

    @classmethod
    def from_settings(cls, s: Settings) -> Limits:
        return cls(
            upload_user=RateLimiter(s.uploads_per_user_per_min, 60),
            upload_ip=RateLimiter(s.uploads_per_ip_per_min, 60),
            upload_global=RateLimiter(s.uploads_global_per_min, 60),
            new_user_ip=RateLimiter(s.new_users_per_ip_per_10min, 600),
            api_ip=RateLimiter(s.api_requests_per_ip_per_min, 60),
            api_guest=RateLimiter(s.api_requests_per_guest_per_min, 60),
            login_ip=RateLimiter(5, 60),
            login_ip_hourly=RateLimiter(20, 3600),
            # after 50 wrong passwords per hour from anywhere, wrong guesses get 429
            login_failures_global=RateLimiter(50, 3600),
        )

    def reset(self) -> None:
        for f in fields(self):
            limiter: RateLimiter = getattr(self, f.name)
            limiter.reset()
