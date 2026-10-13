"""Regression tests for the security review (docs/overhaul/SECURITY_REVIEW.md,
section "Resolution"), one section per finding (SEC-xx)."""

from __future__ import annotations

import logging

import pytest
from starlette.requests import Request

from virtubooth.app import create_app_from_env
from virtubooth.core import errors
from virtubooth.core import ratelimit as ratelimit_module
from virtubooth.core.ratelimit import (
    LOGIN_LOCK_SECONDS,
    IpRateLimiter,
    Limits,
    Lockout,
    RateLimiter,
    ip_bucket,
)
from virtubooth.core.security import is_direct_loopback
from virtubooth.settings import admin_password_warnings

from ..conftest import ADMIN_PASSWORD, ORIGIN, PARTY_TOKEN, SECRET_KEY

# ===================================================== SEC-01 login guessing


def test_ipv6_keys_on_the_64_and_ipv4_on_the_address():
    assert ip_bucket("2001:db8:1:2::1") == ip_bucket("2001:db8:1:2:ffff:ffff:ffff:ffff")
    assert ip_bucket("2001:db8:1:2::1") == "2001:db8:1:2::/64"
    assert ip_bucket("2001:db8:1:3::1") != ip_bucket("2001:db8:1:2::1")
    assert ip_bucket("198.51.100.7") == "198.51.100.7" != ip_bucket("198.51.100.8")
    assert ip_bucket("::ffff:198.51.100.7") == "198.51.100.7"
    assert ip_bucket("testclient") == "testclient"  # not an address: unchanged


def test_every_per_ip_budget_uses_the_64(settings):
    limits = Limits.from_settings(settings)
    per_ip = ("login_ip", "login_ip_hourly", "api_ip", "upload_ip", "new_user_ip")
    for name in per_ip:
        assert isinstance(getattr(limits, name), IpRateLimiter), name
    for name in ("upload_user", "api_guest", "upload_global", "login_failures_global"):
        assert not isinstance(getattr(limits, name), IpRateLimiter), name
    limiter = IpRateLimiter(2, 60)
    assert limiter.hit("2001:db8::1") and limiter.hit("2001:db8::2")
    assert not limiter.hit("2001:db8::3")  # same /64, fresh address: no fresh budget
    assert limiter.retry_after("2001:db8::4") > 0
    assert limiter.hit("2001:db8:0:1::1")  # the next /64 is someone else


def _attempt(core, password: str, ip: str, *, local: bool = False) -> tuple[int, str | None]:
    try:
        core.services.admin_auth.login(password, ip=ip, user_agent="pytest", local=local)
    except errors.ApiError as exc:
        return exc.status, exc.code
    return 200, None


def test_one_ipv6_prefix_gets_one_login_budget(core):
    codes = [_attempt(core, "wrong-password-x", f"2001:db8:1:2::{i:x}") for i in range(1, 8)]
    assert codes == [(401, "wrong_password")] * 5 + [(429, "rate_limited")] * 2
    # the review's PoC: the right password from the same /64 waits as well
    assert _attempt(core, ADMIN_PASSWORD, "2001:db8:1:2::ffff") == (429, "rate_limited")
    assert _attempt(core, ADMIN_PASSWORD, "2001:db8:9:9::1") == (200, None)


def test_the_global_lock_refuses_the_right_password(core, admin, make_client):
    core.limits.login_failures_global = RateLimiter(3, 900)
    codes = [_attempt(core, f"wrong-{i}", f"203.0.113.{i}") for i in range(1, 5)]
    assert codes == [(401, "wrong_password")] * 2 + [(429, "login_locked")] * 2
    # distributed guessing gains nothing: the right password is not even compared
    c = make_client()
    r = c.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=ORIGIN)
    assert r.status_code == 429 and r.json()["error"] == "login_locked"
    assert LOGIN_LOCK_SECONDS - 5 <= int(r.headers["retry-after"]) <= LOGIN_LOCK_SECONDS
    assert not c.get("/api/admin/session").json()["authenticated"]
    # an admin who is logged in already keeps working
    assert admin.get("/api/admin/session").json()["authenticated"]
    assert admin.get("/api/admin/stats").status_code == 200
    core.limits.login_lock.reset()  # the window is over (a restart does the same)
    assert _attempt(core, ADMIN_PASSWORD, "203.0.113.50") == (200, None)


def test_the_lock_lasts_five_minutes(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(ratelimit_module.time, "monotonic", lambda: now[0])
    lock = Lockout(LOGIN_LOCK_SECONDS)
    assert LOGIN_LOCK_SECONDS == 300
    assert lock.remaining() == 0
    lock.trip()
    assert lock.remaining() == 300
    now[0] += 299.5
    assert lock.remaining() == 1
    now[0] += 0.5
    assert lock.remaining() == 0


def test_loopback_is_exempt_from_the_global_lock(core):
    core.limits.login_failures_global = RateLimiter(1, 900)
    assert _attempt(core, "wrong", "203.0.113.1") == (429, "login_locked")
    assert _attempt(core, ADMIN_PASSWORD, "203.0.113.2") == (429, "login_locked")
    # the host on the server itself: wrong guesses don't lock, the right one works
    assert _attempt(core, "wrong", "127.0.0.1", local=True) == (401, "wrong_password")
    assert _attempt(core, ADMIN_PASSWORD, "127.0.0.1", local=True) == (200, None)
    # per-IP limits still apply to loopback (5 per minute)
    for _ in range(3):
        _attempt(core, "wrong", "127.0.0.1", local=True)
    assert _attempt(core, ADMIN_PASSWORD, "127.0.0.1", local=True) == (429, "rate_limited")


def _request(client: str, headers: dict[str, str] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/admin/login",
            "client": (client, 50000),
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        }
    )


def test_only_direct_loopback_requests_count_as_local():
    assert is_direct_loopback(_request("127.0.0.1"))
    assert is_direct_loopback(_request("::1"))
    assert not is_direct_loopback(_request("10.0.0.5"))
    assert not is_direct_loopback(_request("testclient"))
    # via a proxy (or claiming to be): never local, even when uvicorn resolved
    # X-Forwarded-For to 127.0.0.1 for a client in the trusted range
    assert not is_direct_loopback(_request("127.0.0.1", {"X-Forwarded-For": "127.0.0.1"}))
    assert not is_direct_loopback(_request("127.0.0.1", {"Forwarded": "for=127.0.0.1"}))


@pytest.mark.parametrize(
    ("password", "warned"),
    [
        ("Sommerfest2026", True),  # 14 characters: the review's example
        ("aaaaaaaaaaaaaaaaaaaa", True),
        ("passwordpassword", True),
        ("abcdefghijklmnop", True),
        ("KMlnmWpsLZTNG-axuWI_e6", False),  # gen-env style
        ("correcthorsebatterystaple", False),
        ("test-admin-password-123", False),
    ],
)
def test_weak_password_warning(password, warned):
    warnings = admin_password_warnings(password)
    assert bool(warnings) == warned
    assert all(password not in w for w in warnings)


def test_startup_logs_the_password_warning(tmp_path, web_dir, monkeypatch, caplog):
    env = {
        "VB_PARTY_TOKEN": PARTY_TOKEN,
        "VB_ADMIN_PASSWORD": "Sommerfest2026",  # still starts: the minimum stays 12
        "VB_SECRET_KEY": SECRET_KEY,
        "VB_DATA_DIR": str(tmp_path / "data"),
        "VB_WEB_DIR": str(web_dir),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with caplog.at_level(logging.WARNING, logger="virtubooth"):
        app = create_app_from_env()
    app.state.core.db.close()
    text = caplog.text
    assert "VB_ADMIN_PASSWORD has only 14 characters" in text and "gen-env" in text
    assert "Sommerfest2026" not in text
