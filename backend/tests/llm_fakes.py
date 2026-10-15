"""Helpers for the LLM tests (test_llm_*.py): a fake provider that records what
it was sent, and quick ways to make guests and analysed photos straight in the
database (no worker, no network)."""

from __future__ import annotations

import io
import itertools
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from PIL import Image

from virtubooth.core.clock import iso
from virtubooth.extensions.wall.llm import config as llm_config
from virtubooth.extensions.wall.llm import ports
from virtubooth.extensions.wall.llm.providers.base import (
    PhotoLine,
    ProviderError,
    TokenUsage,
    VerdictOut,
)
from virtubooth.extensions.wall.llm.service import LlmService
from virtubooth.runtime import Core

API_KEY = "sk-ant-api03-SECRETSECRETSECRET-0123456789abcdef"
_n = itertools.count(1)


@dataclass
class FakeProvider:
    """Answers like a provider; `fail` raises instead (once per call)."""

    id: str = "anthropic"
    objects: list[ports.DetectedObject] = field(
        default_factory=lambda: [ports.DetectedObject("hat", "Hut", 0.9, (0.1, 0.1, 0.2, 0.2))]
    )
    usage: TokenUsage = field(default_factory=lambda: TokenUsage(1000, 200))
    fail: ProviderError | None = None
    # score answer per call: default = 0.5 for every object of every line
    score_fn: Callable[[Sequence[PhotoLine]], dict[str, list[float | None]]] | None = None
    verdict_out: VerdictOut | None = None
    detected: list[bytes] = field(default_factory=list)
    scored: list[tuple[str, list[PhotoLine], bool]] = field(default_factory=list)
    verdicts: list[tuple[str, list[PhotoLine]]] = field(default_factory=list)
    pings: int = 0

    def _maybe_fail(self) -> None:
        if self.fail is not None:
            raise self.fail

    def detect(
        self, image_jpeg: bytes, *, model: str
    ) -> tuple[list[ports.DetectedObject], TokenUsage]:
        self.detected.append(image_jpeg)
        self._maybe_fail()
        return list(self.objects), self.usage

    def score(
        self, prompt: str, lines: Sequence[PhotoLine], *, model: str, relative: bool = False
    ) -> tuple[dict[str, list[float | None]], TokenUsage]:
        self.scored.append((prompt, list(lines), relative))
        self._maybe_fail()
        if self.score_fn is not None:
            return self.score_fn(lines), self.usage
        return {x.ref: [0.5] * len(x.labels) for x in lines}, self.usage

    def verdict(
        self, prompt: str, lines: Sequence[PhotoLine], *, model: str
    ) -> tuple[VerdictOut, TokenUsage]:
        self.verdicts.append((prompt, list(lines)))
        self._maybe_fail()
        out = self.verdict_out or VerdictOut(
            text=f"{lines[0].author} hat den coolsten {lines[0].labels[0]}!",
            emoji="🏆",
            photo=lines[0].ref,
            object_index=0,
        )
        return out, self.usage

    def ping(self, model: str) -> TokenUsage:
        self.pings += 1
        self._maybe_fail()
        return TokenUsage()


def jpeg_bytes(width: int = 1600, height: int = 1200, *, exif: bool = False) -> bytes:
    img = Image.new("RGB", (width, height), (90, 140, 200))
    buf = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010F] = "SecretCam"  # Make
        img.save(buf, "JPEG", quality=85, exif=data.tobytes())
    else:
        img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def add_guest(
    core: Core,
    *,
    name: str | None = None,
    instagram: str | None = None,
    display_name: str | None = None,
    ai_opt_out: bool = False,
    analysis_opt_out: bool = False,
) -> int:
    n = next(_n)
    at = iso(datetime.now(UTC))
    with core.db.tx() as c:
        cur = c.execute(
            "INSERT INTO users (public_id, name, created_at, last_seen_at, consent_at, "
            "consent_version, instagram, display_name, ai_opt_out, analysis_opt_out) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"u{n:08d}",
                name or f"Gast {n}",
                at,
                at,
                at,
                "1",
                instagram,
                display_name,
                int(ai_opt_out),
                int(analysis_opt_out),
            ),
        )
        return int(cur.lastrowid or 0)


def add_photo(
    core: Core,
    user_id: int,
    *,
    labels: Sequence[str] = ("person", "wine glass"),
    state: str = "done",
    age_s: float = 3600,
    image: bytes | None = None,
    hidden: bool = False,
) -> tuple[int, str]:
    """A photo with its file, its analysis row and local objects; (id, public id)."""
    n = next(_n)
    public_id = f"ph{n:06d}"
    filename = f"{public_id}.jpg"
    path = core.repos.photos.path("demo", filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image or jpeg_bytes())
    created = iso(datetime.now(UTC) - timedelta(seconds=age_s))
    core.repos.photos.insert(
        public_id=public_id,
        extension="demo",
        user_id=user_id,
        filename=filename,
        thumb_filename=filename,
        width=1600,
        height=1200,
        size=path.stat().st_size,
        meta={},
        created_at=created,
    )
    pid = core.repos.photos.internal_id(public_id)
    assert pid is not None
    with core.db.tx() as c:
        c.execute(
            "INSERT INTO wall_analysis (photo_id, state, rev, finished_at) VALUES (?,?,?,?)",
            (pid, state, n, created),
        )
        if hidden:
            c.execute("UPDATE photos SET hidden_at=? WHERE id=?", (created, pid))
    if labels:
        ports.append(
            core.db,
            pid,
            "local",
            "test-detector@1",
            [ports.DetectedObject(lb, lb.title(), 0.8, None) for lb in labels],
        )
    return pid, public_id


def set_flags(
    core: Core, user_id: int, *, ai: bool | None = None, analysis: bool | None = None
) -> None:
    with core.db.tx() as c:
        if ai is not None:
            c.execute("UPDATE users SET ai_opt_out=? WHERE id=?", (int(ai), user_id))
        if analysis is not None:
            c.execute("UPDATE users SET analysis_opt_out=? WHERE id=?", (int(analysis), user_id))


def add_category(core: Core, cid: str, spec: dict[str, Any], *, enabled: bool = True) -> None:
    with core.db.tx() as c:
        pos = c.execute("SELECT COALESCE(MAX(position) + 1, 0) FROM wall_categories").fetchone()[0]
        c.execute(
            "INSERT INTO wall_categories (id, position, enabled, preset, spec, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (cid, pos, int(enabled), None, json.dumps(spec), iso(datetime.now(UTC))),
        )


COOLEST_SPEC: dict[str, Any] = {
    "emoji": "🏆",
    "title": "Das coolste Objekt",
    "line": "Was die KI am coolsten findet",
    "where": [{"value": "prop.coolness.max", "op": "exists"}],
    "select": {
        "by": "prop.coolness.max",
        "order": "top",
        "count": 1,
        "then_by": [],
        "one_per_guest": True,
    },
    "label": {"value": None, "style": "object", "one": "", "many": ""},
    "verdict": {
        "prompt": "Werte das coolste Objekt aus den Ergebnissen raus und sag mir, von wem und was."
    },
}


def setup_llm(core: Core, fake: FakeProvider | None = None, **changes: Any) -> LlmService:
    """Key stored, external AI on (plus `changes`), the fake as provider.
    Hold on to the returned service: the app finds it while it is alive."""
    svc = LlmService.of(core)
    if fake is not None:
        svc.provider_factory = lambda _pid, _key: fake
    svc.keys.put("anthropic", API_KEY, by="test", at=iso(datetime.now(UTC)))
    cfg = llm_config.load_config(core.repos.app_settings)
    data = cfg.model_dump()
    data.update({"enabled": True, **changes})
    llm_config.save_config(
        core.repos.app_settings, llm_config.LlmConfig.model_validate(data), by="test"
    )
    svc.forget_provider()
    return svc


def add_property(core: Core, name: str = "coolness", prompt: str = "Wie cool ist das?") -> int:
    from virtubooth.extensions.wall.llm import properties

    return properties.create(core.db, core.repos.audit, name, prompt, actor="test").id
