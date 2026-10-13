"""In-memory token buckets. Single process only (we run one uvicorn worker).

Per-IP buckets (`IpRateLimiter`) key IPv6 clients on their /64: one host
usually gets a whole /64, so per-address buckets would hand an attacker
2^64 fresh budgets. IPv4 stays per address.
"""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from dataclasses import dataclass, fields

from ..settings import Settings

# The admin login (services/admin_auth.py). After LOGIN_FAILURES_GLOBAL wrong
# passwords within LOGIN_FAILURES_WINDOW seconds, from anywhere, every login is
# refused for LOGIN_LOCK_SECONDS, the right password included (direct loopback
# requests excepted). Admins who are logged in already are not affected.
LOGIN_FAILURES_GLOBAL = 20
LOGIN_FAILURES_WINDOW = 15 * 60
LOGIN_LOCK_SECONDS = 5 * 60
# wrong QR tokens per address and minute (middleware.py); valid scans are free
TOKEN_FAILURES_PER_MIN = 60


def ip_bucket(ip: str) -> str:
    """The rate-limit key of a client address: IPv4 as is, IPv6 as its /64
    (IPv4-mapped IPv6 as the IPv4 address). Anything else stays unchanged."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if isinstance(addr, ipaddress.IPv6Address):
        if addr.ipv4_mapped is not None:
            return str(addr.ipv4_mapped)
        return str(ipaddress.IPv6Network((addr, 64), strict=False))
    return str(addr)


class RateLimiter:
    """`rate` events per `per` seconds, bursting up to `burst` (default: rate)."""

    def __init__(self, rate: int, per: float, burst: int | None = None) -> None:
        self.capacity = float(burst if burst is not None else rate)
        self.refill = rate / per
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def _key(self, key: str) -> str:
        return key

    def hit(self, key: str, cost: float = 1.0) -> bool:
        """Take `cost` tokens. False means the caller is over the limit."""
        key = self._key(key)
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
        key = self._key(key)
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            return min(self.capacity, tokens + (now - last) * self.refill) >= cost

    def retry_after(self, key: str, cost: float = 1.0) -> int:
        key = self._key(key)
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


class IpRateLimiter(RateLimiter):
    """A RateLimiter keyed by client address: IPv6 clients share their /64."""

    def _key(self, key: str) -> str:
        return ip_bucket(key)


class Lockout:
    """A switch that stays on for `seconds` after `trip()`."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self._until = 0.0
        self._lock = threading.Lock()

    def trip(self) -> None:
        with self._lock:
            self._until = time.monotonic() + self.seconds

    def remaining(self) -> int:
        """Whole seconds until the lock opens; 0 when it is open."""
        with self._lock:
            left = self._until - time.monotonic()
        return math.ceil(left) if left > 0 else 0

    def reset(self) -> None:
        with self._lock:
            self._until = 0.0


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
    login_lock: Lockout
    token_fail_ip: RateLimiter

    @classmethod
    def from_settings(cls, s: Settings) -> Limits:
        return cls(
            upload_user=RateLimiter(s.uploads_per_user_per_min, 60),
            upload_ip=IpRateLimiter(s.uploads_per_ip_per_min, 60),
            upload_global=RateLimiter(s.uploads_global_per_min, 60),
            new_user_ip=IpRateLimiter(s.new_users_per_ip_per_10min, 600),
            api_ip=IpRateLimiter(s.api_requests_per_ip_per_min, 60),
            api_guest=RateLimiter(s.api_requests_per_guest_per_min, 60),
            login_ip=IpRateLimiter(5, 60),
            login_ip_hourly=IpRateLimiter(20, 3600),
            # wrong passwords from anywhere; running out trips `login_lock`
            login_failures_global=RateLimiter(LOGIN_FAILURES_GLOBAL, LOGIN_FAILURES_WINDOW),
            login_lock=Lockout(LOGIN_LOCK_SECONDS),
            # wrong QR tokens (?t=) per address; while it is empty, every
            # token is answered with the gate unchecked (no guessing oracle)
            token_fail_ip=IpRateLimiter(TOKEN_FAILURES_PER_MIN, 60),
        )

    def reset(self) -> None:
        for f in fields(self):
            limiter: RateLimiter | Lockout = getattr(self, f.name)
            limiter.reset()
