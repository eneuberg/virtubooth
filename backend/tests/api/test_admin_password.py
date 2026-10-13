"""Changing the admin password (POST /api/admin/settings/password) and resetting it
from the server (`virtubooth reset-admin-password`, tools/admin_password.py)."""

from __future__ import annotations

import io

import pytest

from virtubooth.core.passwords import verify_password
from virtubooth.core.ratelimit import RateLimiter
from virtubooth.repositories.app_settings import ADMIN_PASSWORD_KEY
from virtubooth.tools import admin_password

from ..conftest import ADMIN_PASSWORD, ORIGIN

NEW_PASSWORD = "a-much-better-password-2026"


def login(client, password=ADMIN_PASSWORD):
    return client.post("/api/admin/login", json={"password": password}, headers=ORIGIN)


def change(client, current=ADMIN_PASSWORD, new=NEW_PASSWORD):
    return client.post(
        "/api/admin/settings/password", json={"current": current, "new": new}, headers=ORIGIN
    )


def authenticated(client) -> bool:
    return bool(client.get("/api/admin/session").json()["authenticated"])


@pytest.fixture
def ended_streams(core, monkeypatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(core.bus, "end_session", seen.append)
    return seen


def test_change_keeps_this_session_and_ends_the_others(admin, make_client, core, ended_streams):
    other = make_client()
    assert login(other).status_code == 200
    other_hash = core.repos.audit.list()[0].actor.removeprefix("admin:")

    r = change(admin)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "sessions_ended": 1}
    assert authenticated(admin)
    assert admin.get("/api/admin/settings").status_code == 200
    assert not authenticated(other)
    assert other.get("/api/admin/settings").status_code == 401
    # the other session's event streams end at once
    assert len(ended_streams) == 1 and ended_streams[0].startswith(other_hash)

    stored = core.repos.app_settings.admin_password()
    assert stored is not None and stored.by is not None and stored.by.startswith("admin:")
    assert stored.hash.startswith("scrypt$15$8$1$") and NEW_PASSWORD not in stored.hash
    assert verify_password(NEW_PASSWORD, stored.hash)
    entry = core.repos.audit.list()[0]
    assert (entry.action, entry.details) == ("admin.password_change", {"sessions_ended": 1})

    assert login(make_client(), ADMIN_PASSWORD).status_code == 401
    assert login(make_client(), NEW_PASSWORD).status_code == 200
    state = admin.get("/api/admin/settings").json()["password"]
    assert state == {"source": "admin", "changed_at": stored.changed_at}


def test_change_again_from_the_stored_hash(admin, make_client, core):
    assert change(admin).status_code == 200
    # the env password is no longer the current one
    assert change(admin, current=ADMIN_PASSWORD, new="yet-another-password-1").status_code == 403
    core.limits.reset()
    r = change(admin, current=NEW_PASSWORD, new="yet-another-password-1")
    assert r.status_code == 200 and r.json()["sessions_ended"] == 0
    assert authenticated(admin)
    assert login(make_client(), "yet-another-password-1").status_code == 200


def test_wrong_current_password(admin, core):
    r = change(admin, current="not-the-password")
    assert r.status_code == 403
    assert r.json() == {
        "error": "wrong_password",
        "message": "Das aktuelle Passwort stimmt nicht.",
    }
    entry = core.repos.audit.list()[0]
    assert entry.action == "admin.password_change_failed"
    assert entry.actor.startswith("admin:") and entry.target == "ip:testclient"
    assert core.repos.app_settings.admin_password() is None
    assert authenticated(admin)


@pytest.mark.parametrize(
    ("new", "current", "code", "message"),
    [
        ("short-pw", ADMIN_PASSWORD, "password_too_short", "Das neue Passwort braucht mindestens 12 Zeichen."),
        ("x" * 11, ADMIN_PASSWORD, "password_too_short", "Das neue Passwort braucht mindestens 12 Zeichen."),
        (ADMIN_PASSWORD, ADMIN_PASSWORD, "password_unchanged", "Das neue Passwort ist dasselbe wie das alte."),
    ],
)  # fmt: skip
def test_new_password_rules(admin, core, new, current, code, message):
    r = change(admin, current=current, new=new)
    assert r.status_code == 400
    assert r.json() == {"error": code, "message": message}
    assert core.repos.app_settings.admin_password() is None


def test_body_limits(admin):
    assert change(admin, new="x" * 257).status_code == 422
    assert change(admin, current="x" * 257).status_code == 422


def test_rate_limited_like_the_login(admin, core):
    core.limits.login_ip.reset()
    codes = [change(admin, current=f"wrong-{i}-password").status_code for i in range(6)]
    assert codes == [403] * 5 + [429]
    r = change(admin)  # the right one waits too
    assert r.status_code == 429 and r.json()["error"] == "rate_limited"
    assert "Retry-After" in r.headers


def test_global_lock(admin, core):
    core.limits.login_failures_global = RateLimiter(2, 3600)
    assert change(admin, current="wrong-1-password").status_code == 403
    core.limits.login_ip.reset()
    r = change(admin, current="wrong-2-password")
    assert r.status_code == 429 and r.json()["error"] == "login_locked"
    # while locked: not even compared (and the login is locked as well)
    core.limits.login_ip.reset()
    r = change(admin)
    assert r.status_code == 429 and r.json()["error"] == "login_locked"
    assert core.repos.app_settings.admin_password() is None
    assert authenticated(admin)


def test_needs_an_admin_session_and_same_origin(client, admin):
    assert change(client).status_code == 401
    r = admin.post(
        "/api/admin/settings/password",
        json={"current": ADMIN_PASSWORD, "new": NEW_PASSWORD},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"


# ---------------------------------------------------------------- the CLI


def test_cli_from_env_restores_the_env_password(admin, make_client, core, capsys):
    assert change(admin).status_code == 200
    code = admin_password.main(["--data-dir", str(core.settings.data_dir), "--from-env"])
    assert code == 0
    out = capsys.readouterr().out
    assert "VB_ADMIN_PASSWORD applies again" in out and "admin sessions ended: 1" in out
    assert core.repos.app_settings.get(ADMIN_PASSWORD_KEY) == {}
    assert not authenticated(admin)  # at once: the session check reads the DB
    assert login(make_client(), NEW_PASSWORD).status_code == 401
    assert login(make_client(), ADMIN_PASSWORD).status_code == 200
    entry = next(e for e in core.repos.audit.list() if e.action == "admin.password_reset")
    assert entry.actor == "cli"
    assert entry.details == {"mode": "env", "sessions_ended": 1}


def test_cli_password_stdin_sets_a_new_one(admin, make_client, core, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("from-the-cli-password\n"))
    code = admin_password.main(["--data-dir", str(core.settings.data_dir), "--password-stdin"])
    assert code == 0
    assert "set (VB_ADMIN_PASSWORD no longer logs in)" in capsys.readouterr().out
    assert not authenticated(admin)
    assert login(make_client(), ADMIN_PASSWORD).status_code == 401
    fresh = make_client()
    assert login(fresh, "from-the-cli-password").status_code == 200
    assert fresh.get("/api/admin/settings").json()["password"]["source"] == "admin"
    entry = next(e for e in core.repos.audit.list() if e.action == "admin.password_reset")
    assert entry.details == {"mode": "new", "sessions_ended": 1}


def test_cli_prompts_twice(core, monkeypatch, capsys):
    answers = iter(["typed-twice-password", "typed-twice-password"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert admin_password.main(["--data-dir", str(core.settings.data_dir)]) == 0
    stored = core.repos.app_settings.admin_password()
    assert stored is not None and stored.by == "cli"
    assert verify_password("typed-twice-password", stored.hash)


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        (["typed-once-password", "typed-other-password"], "not the same"),
        (["too-short", "too-short"], "at least 12 characters"),
    ],
)
def test_cli_refuses_mismatch_and_short(core, monkeypatch, capsys, answers, message):
    it = iter(answers)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(it))
    assert admin_password.main(["--data-dir", str(core.settings.data_dir)]) == 1
    assert message in capsys.readouterr().err
    assert core.repos.app_settings.admin_password() is None


def test_cli_without_a_database(tmp_path, capsys):
    assert admin_password.main(["--data-dir", str(tmp_path / "nothing"), "--from-env"]) == 1
    assert "no virtubooth database" in capsys.readouterr().err
    assert not (tmp_path / "nothing").exists()


def test_cli_modes_exclude_each_other(core, capsys):
    with pytest.raises(SystemExit) as exc:
        admin_password.main(
            ["--data-dir", str(core.settings.data_dir), "--from-env", "--password-stdin"]
        )
    assert exc.value.code == 2
