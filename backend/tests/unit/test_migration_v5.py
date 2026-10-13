"""Migration 5 (QR codes) and the seeding at startup: a database from before
the codes gets code 1 from VB_PARTY_TOKEN, and every guest and visitor from
before belongs to it (services/codes.py `ensure_seeded`)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from virtubooth.app import create_app
from virtubooth.core.security import sha256_hex
from virtubooth.db import migrations as dbmod
from virtubooth.db.database import Database
from virtubooth.domain.codes import ANIMALS, token_hash
from virtubooth.runtime import Core
from virtubooth.services.codes import ENV_TOKEN_CHANGED, SEED_KEY

from ..conftest import PARTY_TOKEN, make_settings
from .test_core_db_migration import make_v1_db

TS = "2026-10-10T20:00:00.000+00:00"
LATER = "2026-10-10T21:30:00.000+00:00"


def make_v4_db(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The v1 party (2 guests, 3 photos) upgraded by the v4 code, plus three
    browsers that scanned the one party token (two of them joined)."""
    data_dir.mkdir(parents=True)
    path = data_dir / "virtubooth.db"
    make_v1_db(path)
    with monkeypatch.context() as m:
        m.setattr(dbmod, "MIGRATIONS", dbmod.MIGRATIONS[:4])
        m.setattr(dbmod, "SCHEMA_VERSION", 4)
        db = Database(path)
        try:
            assert db.one("PRAGMA user_version")[0] == 4
            with db.tx() as c:
                c.executemany(
                    "INSERT INTO visitors VALUES (?,?,?,?)",
                    [
                        ("vid-anna", TS, LATER, 1),
                        ("vid-ben", TS, TS, 2),
                        ("vid-lurker", TS, TS, None),
                    ],
                )
        finally:
            db.close()
    return path


@contextmanager
def started(data_dir: Path, web_dir: Path, **changes: Any) -> Iterator[Core]:
    settings = make_settings(data_dir, web_dir).replace(**changes)
    app: FastAPI = create_app(settings, extensions=[])
    try:
        yield app.state.core
    finally:
        app.state.core.db.close()


def rows(core: Core, sql: str) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in core.db.all(sql)]


def test_v4_database_upgrades_and_seeds_code_1(tmp_path, web_dir, monkeypatch):
    data_dir = tmp_path / "data"
    make_v4_db(data_dir, monkeypatch)
    with started(data_dir, web_dir) as core:
        assert core.db.one("PRAGMA user_version")[0] == dbmod.SCHEMA_VERSION
        [code] = core.repos.codes.list()
        assert (code.id, code.token, code.token_gen, code.created_by) == (
            1,
            PARTY_TOKEN,
            1,
            "system",
        )
        assert code.animal in ANIMALS and code.active and code.target == "" == code.note
        assert rows(core, "SELECT token_hash, code_id, retired_at FROM party_code_tokens") == [
            (token_hash(PARTY_TOKEN), 1, None)
        ]
        # every guest and every browser from before came through code 1
        assert rows(core, "SELECT id, code_id FROM users ORDER BY id") == [(1, 1), (2, 1)]
        assert rows(core, "SELECT * FROM code_visitors ORDER BY visitor_id") == [
            (1, "vid-anna", TS, LATER, 1),
            (1, "vid-ben", TS, TS, 1),
            (1, "vid-lurker", TS, TS, 1),
        ]
        seed = core.repos.app_settings.get(SEED_KEY)
        assert seed == {"token_sha256": sha256_hex(PARTY_TOKEN), "at": seed["at"], "source": "env"}
        [entry] = core.repos.audit.list(limit=1)
        assert (entry.actor, entry.action, entry.target) == ("system", "code.create", "code:1")
        assert entry.details == {
            "name": f"{code.animal} 1", "target": "", "note": "",
            "token": "VB_PARTY_TOKEN", "token_end": PARTY_TOKEN[-4:],
        }  # fmt: skip
        assert PARTY_TOKEN not in str(entry.details)
        # the statistics include the party so far (photo 3 is deleted)
        stats = core.repos.codes.stats()[1]
        assert (stats.scans, stats.people, stats.guests, stats.not_joined, stats.photos) == (
            3, 3, 2, 1, 2,
        )  # fmt: skip
        assert (stats.first_scan_at, stats.last_scan_at) == (TS, LATER)
        first_seed = seed

    # a second start changes nothing
    with started(data_dir, web_dir) as core:
        assert [c.id for c in core.repos.codes.list()] == [1]
        assert core.repos.app_settings.get(SEED_KEY) == first_seed
        assert [e.action for e in core.repos.audit.list()].count("code.create") == 1
        assert core.db.one("SELECT COUNT(*) FROM code_visitors")[0] == 3


def test_fresh_database_seeds_code_1(tmp_path, web_dir):
    with started(tmp_path / "data", web_dir) as core:
        [code] = core.repos.codes.list()
        assert code.id == 1 and code.token == PARTY_TOKEN
        assert core.db.one("SELECT COUNT(*) FROM code_visitors")[0] == 0


def test_without_a_token_a_random_one_is_generated(tmp_path, web_dir, caplog):
    with (
        caplog.at_level(logging.WARNING),
        started(tmp_path / "data", web_dir, party_token=None) as core,
    ):
        [code] = core.repos.codes.list()
        assert len(code.token) == 24 and code.token != PARTY_TOKEN
        seed = core.repos.app_settings.get(SEED_KEY)
        assert seed["source"] == "generated" and seed["token_sha256"] == sha256_hex(code.token)
        [entry] = core.repos.audit.list(limit=1)
        assert entry.details["token"] == "erzeugt" and entry.details["token_end"] == code.token[-4:]
    assert ENV_TOKEN_CHANGED not in caplog.text


def test_a_changed_env_token_only_logs_a_warning(tmp_path, web_dir, caplog):
    data_dir = tmp_path / "data"
    with caplog.at_level(logging.WARNING, logger="virtubooth.codes"):
        with started(data_dir, web_dir):
            pass
        assert ENV_TOKEN_CHANGED not in caplog.text
        with started(data_dir, web_dir, party_token="a-completely-new-token-xyz") as core:
            [code] = core.repos.codes.list()
            assert code.token == PARTY_TOKEN  # the database decides
            assert core.services.codes.entry("a-completely-new-token-xyz") is None
    warnings = [r for r in caplog.records if r.getMessage() == ENV_TOKEN_CHANGED]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert "a-completely-new-token-xyz" not in caplog.text and PARTY_TOKEN not in caplog.text


def test_a_token_set_after_a_generated_seed_warns_too(tmp_path, web_dir, caplog):
    data_dir = tmp_path / "data"
    with started(data_dir, web_dir, party_token=None):
        pass
    with caplog.at_level(logging.WARNING, logger="virtubooth.codes"), started(data_dir, web_dir):
        pass
    assert ENV_TOKEN_CHANGED in caplog.text


def test_all_codes_revoked_is_never_seeded_again(tmp_path, web_dir):
    data_dir = tmp_path / "data"
    with started(data_dir, web_dir) as core:
        core.services.codes.revoke(1, actor="pytest")
    with started(data_dir, web_dir) as core:
        [code] = core.repos.codes.list()
        assert code.id == 1 and not code.active
        assert core.services.codes.entry(PARTY_TOKEN) is None
        # the next code still gets the next number
        assert core.services.codes.create(token=None, target="", note="", actor="pytest").id == 2
