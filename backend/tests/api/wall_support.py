"""Helpers for the Live Wall tests (test_wall_*.py): a fake photo analysis, the
wall page in the stub build, and small API helpers.

Each test module loads the wall with

    @pytest.fixture
    def fake() -> FakeEnrichment: ...
    @pytest.fixture
    def extensions(demo_extension, fake): return [demo_extension, make_extension(enrichment=fake)]
    @pytest.fixture
    def web_dir(web_dir): return with_wall_page(web_dir)
"""

from __future__ import annotations

import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from virtubooth.core.clock import iso
from virtubooth.domain.models import User
from virtubooth.extensions.wall.enrichment import PhotoFilter
from virtubooth.runtime import Core

from ..conftest import JPEG, ORIGIN, jpeg

WALL_HTML = (
    '<!doctype html>\n<html lang="de"><head><meta charset="utf-8"><title>Live-Wall</title>'
    '</head><body><div id="root" data-testid="stub-wall"></div></body></html>\n'
)
WALL_PASSWORD = "geheim-123"


def with_wall_page(web_dir: Path) -> Path:
    (web_dir / "wall.html").write_text(WALL_HTML, encoding="utf-8")
    return web_dir


# ---------------------------------------------------------- fake analysis


@dataclass(frozen=True)
class FakeSummary:
    state: str
    facts: Mapping[str, float]


@dataclass(frozen=True)
class FakeCategory:
    id: str
    emoji: str
    title: str
    line: str
    needs: tuple[str, ...] = ()

    def label(self, value: float) -> str:
        return f"{value:g} Stück"

    def available(self, enabled_analyzers: Collection[str]) -> str | None:
        missing = [n for n in self.needs if n not in enabled_analyzers]
        return f"Braucht die Analyse „{missing[0]}“." if missing else None


@dataclass(frozen=True)
class FakeWinners:
    category: FakeCategory
    winners: list[tuple[int, float]]


CATEGORIES = (
    FakeCategory("volles_haus", "👥", "Volles Haus", "Die meisten Leute", ("objects",)),
    FakeCategory("generationen", "🎂", "Generationen-Foto", "Altersspanne", ("tags", "age")),
    FakeCategory("farbexplosion", "🌈", "Farbexplosion", "Das bunteste Foto", ("basic",)),
)


@dataclass
class FakeEnrichment:
    """Records calls; `values[category id] = {internal photo id: value}` decide
    the winners (unfiltered: the wall must drop what it can't show)."""

    started: int = 0
    stopped: int = 0
    states: dict[int, FakeSummary] = field(default_factory=dict)
    rev: int = 0
    changes: list[tuple[int, int]] = field(default_factory=list)
    values: dict[str, dict[int, float]] = field(default_factory=dict)
    filters: list[PhotoFilter] = field(default_factory=list)
    asked: list[list[str]] = field(default_factory=list)

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def analysed(self, photo_id: int, facts: Mapping[str, float], state: str = "done") -> None:
        self.rev += 1
        self.states[photo_id] = FakeSummary(state, dict(facts))
        self.changes.append((self.rev, photo_id))

    def summaries(self, photo_ids: Sequence[int]) -> dict[int, FakeSummary]:
        return {i: self.states[i] for i in photo_ids if i in self.states}

    def changes_since(self, rev: int, limit: int = 500) -> tuple[int, list[int]]:
        newer = [(r, pid) for r, pid in self.changes if r > rev][:limit]
        return (newer[-1][0] if newer else rev), [pid for _, pid in newer]

    def catalogue(self) -> list[FakeCategory]:
        return list(CATEGORIES)

    def winners(
        self, ids: Sequence[str], flt: PhotoFilter, per_category: int = 3
    ) -> list[FakeWinners]:
        self.filters.append(flt)
        self.asked.append(list(ids))
        out = []
        for cat in CATEGORIES:
            if cat.id in ids and self.values.get(cat.id):
                best = sorted(self.values[cat.id].items(), key=lambda kv: -kv[1])
                out.append(FakeWinners(cat, best[: per_category + 2]))
        return out


# ------------------------------------------------------------ API helpers


def upload(client: TestClient, ext: str = "demo") -> str:
    r = client.post(f"/api/x/{ext}/upload", content=jpeg(), headers=JPEG)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id


def user_of(core: Core, client: TestClient) -> User:
    """The users row behind a guest client (via its signed uid cookie)."""
    public_id = core.signer.unsign("uid", client.cookies.get("vb_uid"))
    user = core.repos.users.get_by_public_id(public_id) if public_id else None
    assert user is not None
    return user


def internal_id(core: Core, public_id: str) -> int:
    pid = core.repos.photos.internal_id(public_id)
    assert pid is not None
    return pid


def age_photos(core: Core, seconds: int = 3600) -> None:
    """Every photo was taken `seconds` ago (past any wall delay)."""
    at = iso(datetime.now(UTC) - timedelta(seconds=seconds))
    with core.db.tx() as c:
        c.execute("UPDATE photos SET created_at=?", (at,))


def set_wall_password(admin: TestClient, password: str = WALL_PASSWORD) -> dict[str, Any]:
    r = admin.put("/api/x/wall/admin/password", json={"password": password}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def wall_login(client: TestClient, password: str = WALL_PASSWORD) -> Any:
    return client.post("/livewall/api/session", json={"password": password}, headers=ORIGIN)


def put_config(admin: TestClient, **changes: Any) -> dict[str, Any]:
    config = admin.get("/api/x/wall/admin/config").json()["config"]
    config.update(changes)
    r = admin.put("/api/x/wall/admin/config", json=config, headers=ORIGIN)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def audit_actions(core: Core) -> list[tuple[str, str, dict[str, Any]]]:
    """(action, target, details) of the audit log, newest first."""
    return [(e.action, e.target, e.details) for e in core.repos.audit.list()]


def wait_until(check: Callable[[], Any], timeout: float = 5.0) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.02)
