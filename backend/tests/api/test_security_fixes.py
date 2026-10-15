"""Regression tests for the security review (docs/overhaul/SECURITY_REVIEW.md,
section "Resolution"), one section per finding (SEC-xx)."""

from __future__ import annotations

import io
import logging
import socket
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from starlette.requests import Request

from virtubooth.__main__ import check_forwarded_allow_ips
from virtubooth.__main__ import main as cli_main
from virtubooth.api.routers.admin import events as events_router
from virtubooth.app import create_app_from_env
from virtubooth.core import errors
from virtubooth.core import ratelimit as ratelimit_module
from virtubooth.core.logs import AccessLogFilter, mask_token
from virtubooth.core.ratelimit import (
    LOGIN_LOCK_SECONDS,
    IpRateLimiter,
    Limits,
    Lockout,
    RateLimiter,
    ip_bucket,
)
from virtubooth.core.security import is_direct_loopback, origin_allowed, sha256_hex
from virtubooth.db.database import Database
from virtubooth.repositories.users import MAX_FINGERPRINTS
from virtubooth.services.images import MAX_SCANS, process_jpeg
from virtubooth.settings import ConfigError, Settings, admin_password_warnings
from virtubooth.tools.export import SCRUBBED_TABLES, snapshot_db, take_snapshot

from ..conftest import ADMIN_PASSWORD, JPEG, ORIGIN, PARTY_TOKEN, SECRET_KEY, scan
from .test_admin_events import Live, Stream, admin_client

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


# =================================================== SEC-02 image metadata

MARKERS = (b"COMMENT-MARKER", b"EXIF-MARKER", b"XMP-MARKER", b"ICC-MARKER", b"TRAILING-MARKER")


def tagged_jpeg(width: int = 1080, height: int = 1440) -> bytes:
    """A JPEG carrying a COM segment, EXIF (with GPS), XMP, ICC and trailing bytes."""
    img = Image.new("RGB", (width, height), (90, 140, 200))
    exif = Image.Exif()
    exif[0x010F] = "EXIF-MARKER"  # Make
    exif[0x8825] = {1: "N", 2: (52.0, 31.0, 12.0)}  # GPS
    buf = io.BytesIO()
    img.save(
        buf,
        "JPEG",
        quality=90,
        comment=b"<script>alert(1)</script> COMMENT-MARKER" + b"A" * 2000,
        exif=exif.tobytes(),
        xmp=b'<x:xmpmeta xmlns:x="adobe:ns:meta/">XMP-MARKER</x:xmpmeta>',
        icc_profile=b"ICC-MARKER" + b"\0" * 200,
    )
    raw = buf.getvalue() + b"TRAILING-MARKER"
    assert all(m in raw for m in MARKERS)  # the precondition
    return raw


def assert_clean(data: bytes) -> None:
    for marker in MARKERS:
        assert marker not in data, marker
    with Image.open(io.BytesIO(data)) as img:
        assert not {"comment", "exif", "xmp", "icc_profile"} & set(img.info), img.info


def test_reencoding_drops_every_metadata_segment():
    out = process_jpeg(tagged_jpeg(), max_side=2000, quality=88, thumb_side=480)
    assert_clean(out.data)
    assert_clean(out.thumb)


def test_stored_photo_and_thumbnail_carry_no_metadata(guest):
    g = guest()
    r = g.post("/api/x/demo/upload", content=tagged_jpeg(), headers=JPEG)
    assert r.status_code == 201, r.text
    photo = r.json()["photo"]
    for url in (photo["url"], photo["thumb_url"]):
        stored = g.get(url)
        assert stored.status_code == 200 and stored.headers["content-type"] == "image/jpeg"
        assert_clean(stored.content)


# ================================================== SEC-14 decode work


def test_too_many_scans_are_refused_before_decoding():
    img = Image.new("RGB", (1080, 1440), (10, 20, 30))
    buf = io.BytesIO()
    # SOS marker bytes are counted as an upper bound, so a comment full of
    # them stands in for a crafted progressive file with thousands of scans
    img.save(buf, "JPEG", comment=b"\xff\xda" * (MAX_SCANS + 1))
    with pytest.raises(errors.ApiError) as exc:
        process_jpeg(buf.getvalue(), max_side=2000, quality=88, thumb_side=480)
    assert exc.value.code == "invalid_image"
    # a normal progressive JPEG has about 10 scans and passes
    progressive = io.BytesIO()
    img.save(progressive, "JPEG", progressive=True, quality=90)
    assert 1 < progressive.getvalue().count(b"\xff\xda") <= MAX_SCANS
    out = process_jpeg(progressive.getvalue(), max_side=2000, quality=88, thumb_side=480)
    assert (out.width, out.height) == (1080, 1440)


def test_the_header_size_is_checked_before_decoding(monkeypatch):
    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000)).save(buf, "JPEG")
    loaded: list[bool] = []
    monkeypatch.setattr(Image.Image, "load", lambda self: loaded.append(True))
    with pytest.raises(errors.ApiError) as exc:
        process_jpeg(buf.getvalue(), max_side=2000, quality=88, thumb_side=480)
    assert exc.value.code == "invalid_image" and not loaded  # refused from the header
    assert Image.MAX_IMAGE_PIXELS == 25_000_000


# ======================================== SEC-03 the archive's database copy


def test_snapshot_drops_admin_secrets_and_free_pages(tmp_path):
    data = tmp_path / "data"
    db = Database(data / "virtubooth.db")
    with db.tx() as c:
        c.execute(
            "INSERT INTO admin_sessions VALUES (?,?,?,?,?,?)",
            ("TOKENHASH-MARKER", "2026", "2099", "PWTAG-MARKER", "203.0.113.9", "UA-MARKER"),
        )
        c.execute(
            "INSERT INTO export_jobs (id, kind, status, created_at) "
            "VALUES ('JOB-MARKER', 'qr', 'done', '2026')"
        )
        c.execute("INSERT INTO settings VALUES ('gone', ?, '2026')", ("DELETED-MARKER" * 300,))
    # SQLite builds with SQLITE_SECURE_DELETE zero deleted rows; others leave
    # them on free pages, which the backup API copies: simulate that
    db.all("PRAGMA secure_delete=OFF")
    with db.tx() as c:
        c.execute("DELETE FROM settings WHERE key='gone'")
    raw_copy = tmp_path / "raw.db"
    snapshot_db(data / "virtubooth.db", raw_copy)
    # precondition: the plain backup copy still holds the deleted row's bytes
    assert b"DELETED-MARKER" in raw_copy.read_bytes()

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    snap = take_snapshot(data, scratch, include_hidden=True)
    db.close()
    content = snap.db_file.read_bytes()
    for marker in (b"TOKENHASH", b"PWTAG", b"UA-MARKER", b"JOB-MARKER", b"DELETED-MARKER"):
        assert marker not in content, marker
    conn = sqlite3.connect(snap.db_file)
    try:
        for table in SCRUBBED_TABLES:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    assert not list(scratch.glob("*-wal")) and not list(scratch.glob("*-shm"))
    # the copy still opens as a virtubooth database (e.g. to restore a backup)
    Database(snap.db_file).close()


def test_snapshot_drops_password_hashes(tmp_path):
    """Review 2, ARCH-01: the admin password set in the admin and the wall
    password are scrypt hashes in `settings`; the archive's copy must not
    carry them (offline cracking). Other settings stay."""
    data = tmp_path / "data"
    db = Database(data / "virtubooth.db")
    with db.tx() as c:
        for key, marker in (
            ("admin.password", "ADMINHASH-MARKER"),
            ("x.wall.password", "WALLHASH-MARKER"),
            ("x.llm.key", "LLMKEY-MARKER"),
            ("ai.other.secret", "SECRET-MARKER"),
            ("x.llm.config", "LLMCONFIG-MARKER"),
            ("x.wall.config", "CONFIG-MARKER"),
            ("event", "EVENT-MARKER"),
        ):
            c.execute("INSERT INTO settings VALUES (?, ?, '2026')", (key, f'{{"v": "{marker}"}}'))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    snap = take_snapshot(data, scratch, include_hidden=True)
    db.close()
    content = snap.db_file.read_bytes()
    for marker in (b"ADMINHASH-MARKER", b"WALLHASH-MARKER", b"LLMKEY-MARKER", b"SECRET-MARKER"):
        assert marker not in content, marker
    conn = sqlite3.connect(snap.db_file)
    try:
        keys = {r[0] for r in conn.execute("SELECT key FROM settings")}
    finally:
        conn.close()
    assert {"x.wall.config", "event", "x.llm.config"} <= keys
    assert not keys & {"admin.password", "x.wall.password", "x.llm.key", "ai.other.secret"}


# ============================================================ SEC-04 CSRF


def csrf_settings(**changes: Any) -> Settings:
    return Settings(
        _env_file=None,
        party_token=PARTY_TOKEN,
        admin_password=ADMIN_PASSWORD,
        secret_key=SECRET_KEY,
        data_dir=Path("/tmp"),
        **changes,
    )


def csrf_request(
    host: str, origin: str, *, scheme: str = "http", header: str = "origin", **headers: str
) -> Request:
    raw = [(b"host", host.encode()), (header.encode(), origin.encode())]
    raw += [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]
    return Request(
        {"type": "http", "method": "POST", "scheme": scheme, "path": "/", "headers": raw}
    )


LOCAL = csrf_settings()
PUBLIC_HTTPS = csrf_settings(public_base_url="https://party.example")
# a .env made by gen-env and never edited: the public URL points at localhost
GEN_ENV_DEFAULT = csrf_settings(public_base_url="http://localhost:8000")
COOKIE_SECURE = csrf_settings(cookie_secure="true")
COOLIFY = csrf_settings(public_base_url="https://vb.example.org")
ALIAS = csrf_settings(allowed_origins=("https://alias.example", "http://kiosk.lan:8080"))

XFP = {"x_forwarded_proto": "https"}


@pytest.mark.parametrize(
    ("settings", "request_", "allowed"),
    [
        # plain http on a laptop or in the LAN (no proxy)
        (LOCAL, csrf_request("localhost:8000", "http://localhost:8000"), True),
        (LOCAL, csrf_request("127.0.0.1:8210", "http://127.0.0.1:8210"), True),
        # the review's PoC: an https origin for an http server
        (LOCAL, csrf_request("127.0.0.1:8210", "https://127.0.0.1:8210"), False),
        (LOCAL, csrf_request("localhost:8000", "http://localhost:9000"), False),
        (LOCAL, csrf_request("localhost:8000", "https://evil.example"), False),
        (LOCAL, csrf_request("localhost:8000", "http://localhost:8000.evil.example"), False),
        (LOCAL, csrf_request("localhost:8000", "null"), False),
        (LOCAL, csrf_request("localhost:8000", "ftp://localhost:8000"), False),
        (LOCAL, csrf_request("localhost:8000", "http://user@localhost:8000"), False),
        # compose + Caddy/Traefik/nginx, VB_FORWARDED_ALLOW_IPS covers the proxy:
        # uvicorn applied X-Forwarded-Proto, the app sees https
        (
            PUBLIC_HTTPS,
            csrf_request("party.example", "https://party.example", scheme="https"),
            True,
        ),
        (LOCAL, csrf_request("party.example", "https://party.example", scheme="https"), True),
        (LOCAL, csrf_request("party.example", "http://party.example", scheme="https"), False),
        (
            PUBLIC_HTTPS,
            csrf_request("party.example", "http://party.example", scheme="https"),
            False,
        ),
        # ... the same proxy NOT trusted: the app sees http, the proxy's header is there
        (PUBLIC_HTTPS, csrf_request("party.example", "https://party.example", **XFP), True),
        (GEN_ENV_DEFAULT, csrf_request("party.example", "https://party.example", **XFP), True),
        (LOCAL, csrf_request("party.example", "https://party.example", **XFP), True),
        (LOCAL, csrf_request("party.example", "http://party.example", **XFP), False),
        (GEN_ENV_DEFAULT, csrf_request("party.example", "http://party.example", **XFP), False),
        (LOCAL, csrf_request("party.example", "https://evil.example", **XFP), False),
        # ... and a proxy that sends no X-Forwarded-Proto at all
        (PUBLIC_HTTPS, csrf_request("party.example", "https://party.example"), True),
        (COOKIE_SECURE, csrf_request("party.example", "https://party.example"), True),
        (PUBLIC_HTTPS, csrf_request("party.example", "http://party.example"), False),
        (PUBLIC_HTTPS, csrf_request("party.example:8080", "http://party.example:8080"), False),
        (GEN_ENV_DEFAULT, csrf_request("party.example", "https://party.example"), False),
        # Coolify: Traefik in the trusted RFC 1918 range, public URL = SERVICE_URL_APP
        (COOLIFY, csrf_request("vb.example.org", "https://vb.example.org", scheme="https"), True),
        (COOLIFY, csrf_request("vb.example.org", "http://vb.example.org", scheme="https"), False),
        (COOLIFY, csrf_request("vb.example.org", "https://evil.example", scheme="https"), False),
        # a proxy that rewrites Host: the public URL still matches exactly
        (PUBLIC_HTTPS, csrf_request("app:8000", "https://party.example", scheme="https"), True),
        (PUBLIC_HTTPS, csrf_request("app:8000", "https://party.example"), True),
        # the host on the server (ssh tunnel) while the public URL is https
        (PUBLIC_HTTPS, csrf_request("localhost:8000", "http://localhost:8000"), True),
        (COOLIFY, csrf_request("127.0.0.1:8000", "http://127.0.0.1:8000"), True),
        # VB_ALLOWED_ORIGINS: exact, and the only way to allow an http origin over TLS
        (ALIAS, csrf_request("internal:8000", "https://alias.example"), True),
        (ALIAS, csrf_request("internal:8000", "http://alias.example"), False),
        (ALIAS, csrf_request("x.example", "http://kiosk.lan:8080", scheme="https"), True),
        # Referer instead of Origin: only its origin counts, the scheme too
        (
            LOCAL,
            csrf_request("localhost:8000", "http://localhost:8000/x/beer/", header="referer"),
            True,
        ),
        (LOCAL, csrf_request("localhost:8000", "https://localhost:8000/", header="referer"), False),
        (
            PUBLIC_HTTPS,
            csrf_request("party.example", "http://party.example/", header="referer", **XFP),
            False,
        ),
    ],
)
def test_origin_rules(settings, request_, allowed):
    assert origin_allowed(request_, settings) is allowed


def test_an_https_origin_is_refused_on_a_plain_http_server(admin, guest):
    g = guest()
    r = g.patch("/api/me", json={"instagram": "anna"}, headers={"Origin": "https://testserver"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    r = admin.post(
        "/api/admin/exports", json={"kind": "archive"}, headers={"Origin": "https://testserver"}
    )
    assert r.status_code == 403
    assert g.patch("/api/me", json={"instagram": "anna"}, headers=ORIGIN).status_code == 200


def test_an_http_origin_is_refused_over_tls(app, admin):
    with TestClient(app, base_url="https://party.example", follow_redirects=False) as tls:
        tls.cookies.set("vb_admin", admin.cookies.get("vb_admin"))
        r = tls.post("/api/admin/logout", headers={"Origin": "http://party.example"})
        assert r.status_code == 403 and r.json()["error"] == "bad_origin"
        assert tls.get("/api/admin/session").json()["authenticated"]
        r = tls.post("/api/admin/logout", headers={"Origin": "https://party.example"})
        assert r.status_code == 200
        assert not tls.get("/api/admin/session").json()["authenticated"]


# ===================================================== SEC-05 root files


def test_only_allow_listed_root_files_are_served(client, web_dir):
    (web_dir / "gate-hint.js").write_text("void 0;\n")
    (web_dir / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (web_dir / "notes.txt").write_text("not for guests\n")
    for name in ("index.html", "admin.html", "gate.html", "boot-check.js"):
        for suffix in (".br", ".gz"):
            (web_dir / f"{name}{suffix}").write_bytes(b"\x1f\x8b compressed copy")
    public = ("/boot-check.js", "/gate-hint.js", "/icon.svg", "/robots.txt")
    hidden = (
        "/index.html.gz",
        "/index.html.br",
        "/admin.html.gz",
        "/admin.html.br",
        "/gate.html.br",
        "/gate.html.gz",
        "/boot-check.js.br",
        "/notes.txt",
        "/index.html",
    )
    for anonymous in (True, False):
        if not anonymous:
            scan(client)  # with the party cookie: still not found
        for path in public:
            r = client.get(path)
            assert r.status_code == 200 and r.headers["cache-control"] == "public, max-age=300"
        for path in hidden:
            r = client.get(path)
            assert r.status_code == 404, path
            assert r.headers["x-vb-page"] == ("gate" if anonymous else "notfound"), path
            assert b"compressed copy" not in r.content and "not for guests" not in r.text


# ================================================== SEC-06 event streams


@pytest.fixture
def live(app: FastAPI, unused_port: int) -> Iterator[Live]:
    """A real server (TestClient can't stream SSE), as in test_admin_events."""
    config = uvicorn.Config(
        app, host="127.0.0.1", port=unused_port, log_level="warning", timeout_graceful_shutdown=1
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.02)
    yield Live(f"http://127.0.0.1:{unused_port}", app.state.core)
    server.should_exit = True
    thread.join(5)


@pytest.fixture
def unused_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def test_logout_ends_the_sessions_streams_at_once(live: Live):
    admin, other = admin_client(live), admin_client(live)
    mine = [Stream(admin, "/api/admin/events") for _ in range(2)]
    theirs = Stream(other, "/api/admin/events")
    try:
        for s in (*mine, theirs):
            assert s.wait_for(lambda line: line.startswith("retry:"))
        started = time.monotonic()
        r = admin.post("/api/admin/logout", headers={"Origin": live.base_url})
        assert r.status_code == 200
        for s in mine:
            # no event needed and no 30 s session check: the stream ends now
            assert s.wait_for(lambda line: False, timeout=3) is None
        assert time.monotonic() - started < 3
        # the browser's reconnect gets 401 and goes to the login page
        assert admin.get("/api/admin/events").status_code == 401
        # another session's stream is untouched
        assert live.core.bus.subscriber_count == 1
        live.core.bus.publish("photo.hidden", {"probe": 1})
        assert theirs.wait_for(lambda line: line == "event: photo.hidden")
    finally:
        for s in (*mine, theirs):
            s.close()
        admin.close()
        other.close()


def test_a_session_keeps_at_most_four_streams(live: Live):
    admin = admin_client(live)
    streams: list[Stream] = []
    try:
        for _ in range(5):
            s = Stream(admin, "/api/admin/events")
            assert s.wait_for(lambda line: line.startswith("retry:"))
            streams.append(s)
        # the fifth closed the oldest; its tab reconnects and replays what it missed
        assert streams[0].wait_for(lambda line: False, timeout=3) is None
        session = sha256_hex(admin.cookies["vb_admin"])
        assert live.core.bus.session_count(session) == 4
        live.core.bus.publish("photo.hidden", {"probe": 1})
        for s in streams[1:]:  # still open
            assert s.wait_for(lambda line: line == "event: photo.hidden")
    finally:
        for s in streams:
            s.close()
        admin.close()


def test_a_logout_between_auth_and_subscribe_still_ends_the_stream(core):
    import asyncio

    token = core.services.admin_auth.login(ADMIN_PASSWORD, ip="10.0.0.1", user_agent="pytest")
    admin = core.services.admin_auth.session(token)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/admin/events",
            "headers": [(b"cookie", f"vb_admin={token}".encode())],
        }
    )

    async def scenario() -> list[Any]:
        core.bus.bind_loop(asyncio.get_running_loop())
        core.services.admin_auth.logout(admin)  # end_session() runs before subscribe
        await asyncio.sleep(0.01)
        stream = events_router.admin_event_stream(request, core, None, session=admin.session_hash)
        return [m async for m in stream]

    assert asyncio.run(scenario()) == []
    assert core.bus.subscriber_count == 0


def test_end_session_wakes_a_waiting_stream_from_another_thread():
    import asyncio

    from virtubooth.core.events import Closed, EventBus

    async def scenario() -> float:
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        sub = bus.subscribe(None, session="abc")
        other = bus.subscribe(None, session="def")
        started = time.monotonic()
        threading.Timer(0.1, bus.end_session, args=("abc",)).start()
        with pytest.raises(Closed):
            await asyncio.wait_for(sub.get(), 5)
        assert bus.subscriber_count == 1 and not other.closed
        return time.monotonic() - started

    assert asyncio.run(scenario()) < 1


# ================================================== SEC-07 the access log


@pytest.mark.parametrize(
    "query",
    [
        f"t={PARTY_TOKEN}",
        f"%74={PARTY_TOKEN}",
        f"%74={PARTY_TOKEN}&debug=1",
        f"debug=1&%74={PARTY_TOKEN}",
        f"a=1&t={PARTY_TOKEN}&%74={PARTY_TOKEN}",
        f"t=x&t={PARTY_TOKEN}",
        "t=",
        "T=abc",
        "%2574=abc",
        "+t=abc",
        "debug=1",
    ],
)
def test_access_log_masks_every_spelling_starlette_reads_as_t(query):
    from starlette.datastructures import QueryParams

    masked = mask_token(f"/x/beer/?{query}").partition("?")[2]
    values = QueryParams(query).getlist("t")
    for value in filter(None, values):
        assert f"={value}" not in masked
    # whatever the app treats as the token entry is masked, nothing else
    assert ("=***" in masked) == bool(values)
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", f"/?{query}", "1.1", 303),
        None,
    )
    assert AccessLogFilter().filter(record)
    if PARTY_TOKEN in query:
        assert PARTY_TOKEN not in record.getMessage()


def test_percent_encoded_entry_is_still_an_entry_and_is_masked(client):
    r = client.get(f"/?%74={PARTY_TOKEN}")
    assert r.status_code == 303  # Starlette decodes the key: this is `t`
    assert mask_token(f"/?%74={PARTY_TOKEN}") == "/?%74=***"


# ================================================== SEC-09 cache headers


def test_cookie_dependent_html_is_private(client, make_client):
    gate = client.get("/")
    assert gate.status_code == 404 and gate.headers["cache-control"] == "private, no-cache"
    entry = client.get(f"/?t={PARTY_TOKEN}")
    assert entry.status_code == 303 and entry.headers["cache-control"] == "no-store"
    assert "vb_access=" in entry.headers["set-cookie"]
    app_page = client.get("/")
    assert app_page.status_code == 200
    assert app_page.headers["cache-control"] == "private, no-cache"
    not_found = client.get("/nope")
    assert not_found.status_code == 404
    assert not_found.headers["cache-control"] == "private, no-cache"
    redirect = make_client().get("/admin/live")
    assert redirect.status_code == 303
    assert redirect.headers["cache-control"] == "private, no-cache"
    assert make_client().get("/admin/login").headers["cache-control"] == "private, no-cache"


# =============================================== SEC-10 fingerprint rows


def test_fingerprint_rows_per_guest_are_capped(guest, core):
    g = guest()
    user_id = core.repos.users.get_by_public_id(
        core.signer.unsign("uid", g.cookies.get("vb_uid"))
    ).id
    first = f"{1:064x}"  # from the join
    core.repos.bans.add(first, at="2026-01-01T00:00:00Z", reason="pytest")
    for i in range(2, 40):
        core.repos.users.touch(
            user_id,
            at=f"2099-01-01T00:{i:02d}:00.000+00:00",
            ip="10.0.0.1",
            user_agent="pytest",
            fp_hash=f"{i:064x}",
            fp_components={},
        )
    hashes = [f.fp_hash for f in core.repos.users.fingerprints(user_id)]
    # the newest MAX_FINGERPRINTS, plus the banned one (kept for unban/auto-ban)
    assert len(hashes) == MAX_FINGERPRINTS + 1
    assert hashes[:MAX_FINGERPRINTS] == [f"{i:064x}" for i in range(39, 39 - MAX_FINGERPRINTS, -1)]
    assert first in hashes


# ====================================== SEC-15 VB_FORWARDED_ALLOW_IPS


@pytest.mark.parametrize("value", ["*", " * ", "127.0.0.1,*", "10.0.0.0/8, *"])
def test_trusting_every_proxy_is_refused(value):
    with pytest.raises(ConfigError, match=r"must not be '\*'.*proxy's address"):
        check_forwarded_allow_ips(value)


@pytest.mark.parametrize("value", ["127.0.0.1", "172.16.0.0/12", "10.0.0.0/8,172.16.0.0/12"])
def test_proxy_addresses_are_accepted(value):
    assert check_forwarded_allow_ips(value) == value


def test_serve_refuses_a_wildcard_before_starting(monkeypatch, capsys):
    def no_server(*_a: Any, **_k: Any) -> None:
        raise AssertionError("uvicorn must not start")

    monkeypatch.setattr("uvicorn.run", no_server)
    with pytest.raises(SystemExit) as exc:
        cli_main(["serve", "--forwarded-allow-ips", "*"])
    assert exc.value.code == 2
    assert "VB_FORWARDED_ALLOW_IPS must not be '*'" in capsys.readouterr().err
    monkeypatch.setenv("VB_FORWARDED_ALLOW_IPS", "*")
    with pytest.raises(SystemExit):
        cli_main(["serve"])
