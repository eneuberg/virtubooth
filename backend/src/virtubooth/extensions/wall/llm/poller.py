"""The poll (PLAN-NIGHT N8): text only, every `poll_interval_s`.

Per active property one call (chunks of ≤ 400 objects) rates every object of
every eligible photo (visible, analysis done, guest opted out of neither);
answers whose array length differs from the photo's object count at send time
are dropped. `property_scores` keeps only the latest values. Then one verdict
call per enabled category with a `verdict` (verdicts.py). One `llm_polls` row
per run; a run whose input (photos, objects, names, properties, categories,
model) hashes like the last finished one is skipped unless forced.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from ....core.clock import now_iso
from ....db.database import Database
from ....repositories.app_settings import AppSettingsRepo
from . import ports, properties
from .providers.base import PhotoLine, Provider, ProviderError, TokenUsage

if TYPE_CHECKING:
    from .service import LlmService

log = logging.getLogger("virtubooth.llm")

POLL_KEY = "x.llm.poll"
MAX_OBJECTS_PER_CALL = 400
# how often an idle poller looks at the config again
RECHECK_S = 30.0

PollerState = Literal["off", "idle", "running", "blocked"]


@dataclass(frozen=True)
class PolledPhoto:
    id: int
    public_id: str
    user_id: int
    author: str
    labels: tuple[str, ...]

    @property
    def ref(self) -> str:
        return f"P{self.public_id}"


@dataclass(frozen=True)
class PollResult:
    state: Literal["done", "failed", "skipped"]
    poll_id: int | None
    reason: str | None = None


# the name the wall shows (PLAN-NIGHT N15, feed.py): the display name, else
# „@instagram“ while the wall shows Instagram names, else the pseudonym. The
# verdict text lands on the wall, so it must not name a handle the wall hides.
SHOWN_NAME_SQL = "COALESCE(NULLIF(TRIM(u.display_name), ''), '@' || u.instagram, u.name)"
WALL_NAME_SQL = "COALESCE(NULLIF(TRIM(u.display_name), ''), u.name)"
_ALLOWED_SQL = (
    "p.deleted_at IS NULL AND p.hidden_at IS NULL AND u.analysis_opt_out = 0 "
    "AND u.ai_opt_out = 0 AND u.banned_at IS NULL"
)


def eligible_photos(db: Database) -> list[PolledPhoto]:
    """Photos the poll may send, oldest first, with their MERGED object list
    (local and AI objects, deduplicated; property scores index into it).
    Photos without objects have nothing to rate and are left out."""
    from .. import config as wall_config

    show_instagram = wall_config.load_config(AppSettingsRepo(db)).show_instagram
    name_sql = SHOWN_NAME_SQL if show_instagram else WALL_NAME_SQL
    rows = db.all(
        f"SELECT p.id, p.public_id, p.user_id, {name_sql} AS author FROM photos p "
        "JOIN users u ON u.id = p.user_id "
        "JOIN wall_analysis a ON a.photo_id = p.id AND a.state = 'done' "
        f"WHERE {_ALLOWED_SQL} ORDER BY p.created_at, p.id"
    )
    objs = ports.objects_of(db, [r["id"] for r in rows])
    return [
        PolledPhoto(
            r["id"],
            r["public_id"],
            r["user_id"],
            r["author"],
            tuple(o.label for o in objs[r["id"]]),
        )
        for r in rows
        if objs.get(r["id"])
    ]


def still_allowed(db: Database, photo_ids: Sequence[int]) -> set[int]:
    """The ids whose guest still allows sending (read right before each send)."""
    if not photo_ids:
        return set()
    marks = ",".join("?" for _ in photo_ids)
    rows = db.all(
        f"SELECT p.id FROM photos p JOIN users u ON u.id = p.user_id "
        f"WHERE p.id IN ({marks}) AND {_ALLOWED_SQL}",
        list(photo_ids),
    )
    return {r["id"] for r in rows}


def chunks(
    photos: Sequence[PolledPhoto], limit: int = MAX_OBJECTS_PER_CALL
) -> list[list[PolledPhoto]]:
    out: list[list[PolledPhoto]] = []
    current: list[PolledPhoto] = []
    size = 0
    for p in photos:
        if current and size + len(p.labels) > limit:
            out.append(current)
            current, size = [], 0
        current.append(p)
        size += len(p.labels)
    if current:
        out.append(current)
    return out


def line(p: PolledPhoto) -> PhotoLine:
    return PhotoLine(ref=p.ref, author=p.author, labels=p.labels)


def verdict_categories(db: Database) -> list[tuple[str, dict[str, object]]]:
    return [
        (cid, spec)
        for cid, enabled, spec in ports.category_specs(db)
        if enabled and isinstance(spec.get("verdict"), dict)
    ]


def input_hash(
    model: str,
    props: Sequence[properties.Property],
    cats: Sequence[tuple[str, dict[str, object]]],
    photos: Sequence[PolledPhoto],
) -> str:
    data = {
        "model": model,
        "props": [(p.id, p.name, p.prompt) for p in props],
        "cats": [(cid, spec) for cid, spec in cats],
        "photos": [(p.public_id, p.author, list(p.labels)) for p in photos],
    }
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _start_row(db: Database, model: str, photos: int) -> int:
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO llm_polls (started_at, state, model, photos) VALUES (?,?,?,?)",
            (now_iso(), "running", model, photos),
        )
        return int(cur.lastrowid or 0)


def _finish_row(db: Database, poll_id: int, state: str, error: str | None) -> None:
    with db.tx() as c:
        c.execute(
            "UPDATE llm_polls SET state=?, finished_at=?, error=? WHERE id=?",
            (state, now_iso(), error[:500] if error else None, poll_id),
        )


def poll_once(svc: LlmService, *, force: bool = False) -> PollResult | None:
    """One poll. None when there is nothing to do (external AI or the poll
    switched off, no key, neither properties nor verdict categories): no row
    is written then."""
    from .service import Unavailable
    from .verdicts import run_verdicts

    db = svc.core.db
    cfg = svc.config()
    if not (cfg.enabled and cfg.poll) or svc.keys.load(cfg.provider) is None:
        return None
    props = properties.active(db)
    cats = verdict_categories(db)
    if not props and not cats:
        return None
    photos = eligible_photos(db)
    digest = input_hash(cfg.model, props, cats, photos)
    last = svc.core.repos.app_settings.get(POLL_KEY)
    if not force and last.get("hash") == digest:
        poll_id = _start_row(db, cfg.model, len(photos))
        _finish_row(db, poll_id, "skipped", "unverändert")
        return PollResult("skipped", poll_id, "Nichts geändert seit der letzten Abfrage.")
    blocked = svc.blocked_reason(cfg)
    poll_id = _start_row(db, cfg.model, len(photos))
    if blocked is not None:
        _finish_row(db, poll_id, "skipped", blocked)
        return PollResult("skipped", poll_id, blocked)

    errors: list[str] = []
    calls = ok_calls = 0
    stop: str | None = None
    for prop in props:
        parts = chunks(photos)
        for part in parts:
            allowed = still_allowed(db, [p.id for p in part])
            part = [p for p in part if p.id in allowed]
            if not part:
                continue
            calls += 1
            sent = {p.ref: p for p in part}
            lines = [line(p) for p in part]
            try:
                result, _ = svc.call(
                    "property",
                    prop.name,
                    _score_call(prop.prompt, lines, relative=len(parts) > 1),
                    config=cfg,
                )
            except Unavailable as exc:
                stop = exc.message
                break
            except ProviderError as exc:
                errors.append(f"{prop.name}: {exc.message}")
                continue
            ok_calls += 1
            store_scores(db, prop.id, poll_id, sent, result)
        if stop:
            break

    if stop is None:
        v_calls, v_ok, v_errors, stop = run_verdicts(svc, cfg, cats, photos, poll_id)
        calls, ok_calls = calls + v_calls, ok_calls + v_ok
        errors.extend(v_errors)

    if stop is not None:
        state: Literal["done", "failed", "skipped"] = "failed"
        reason: str | None = stop
    elif calls and not ok_calls:
        state, reason = "failed", "; ".join(errors)
    else:
        state, reason = "done", ("; ".join(errors) or None)
    _finish_row(db, poll_id, state, reason)
    if state == "done":
        svc.core.repos.app_settings.put(
            POLL_KEY, {"hash": digest, "poll_id": poll_id}, at=now_iso()
        )
    return PollResult(state, poll_id, reason)


def _score_call(
    prompt: str, lines: list[PhotoLine], *, relative: bool
) -> Callable[[Provider, str], tuple[dict[str, list[float | None]], TokenUsage]]:
    def run(provider: Provider, model: str) -> tuple[dict[str, list[float | None]], TokenUsage]:
        return provider.score(prompt, lines, model=model, relative=relative)

    return run


def store_scores(
    db: Database,
    property_id: int,
    poll_id: int,
    sent: dict[str, PolledPhoto],
    result: dict[str, list[float | None]],
) -> int:
    """Upsert the answers that fit; returns how many were stored. An id the
    poll did not send or an array of the wrong length is dropped (logged)."""
    at = now_iso()
    stored = 0
    with db.tx() as c:
        for ref, scores in result.items():
            photo = sent.get(ref)
            if photo is None:
                log.info("llm poll: answer for unknown photo %r dropped", ref[:40])
                continue
            if len(scores) != len(photo.labels):
                log.info(
                    "llm poll: %s has %d objects, answer has %d scores: dropped",
                    ref,
                    len(photo.labels),
                    len(scores),
                )
                continue
            c.execute(
                "INSERT INTO property_scores (property_id, photo_id, scores, poll_id, updated_at) "
                "VALUES (?,?,?,?,?) ON CONFLICT(property_id, photo_id) DO UPDATE SET "
                "scores=excluded.scores, poll_id=excluded.poll_id, updated_at=excluded.updated_at",
                (property_id, photo.id, json.dumps(scores), poll_id, at),
            )
            stored += 1
    return stored


class Poller:
    """The poll loop (a thread; the poll itself is blocking I/O) and its state
    for `GET /llm`."""

    def __init__(self, service: LlmService) -> None:
        from .service import Ticker

        self.service = service
        self.running = False
        self.last_poll_at: str | None = None
        self.next_poll_at: str | None = None
        self.last_error: str | None = None
        self.blocked: str | None = None
        self._force = False
        self._run_lock = threading.Lock()
        self._ticker = Ticker("llm-poll", self.step)

    def start(self) -> None:
        self._ticker.start()

    def stop(self) -> None:
        self._ticker.stop()

    def poke(self) -> None:
        self._ticker.poke()

    def state(self) -> PollerState:
        if self.running:
            return "running"
        svc = self.service
        cfg = svc.config()
        if not (cfg.enabled and cfg.poll) or svc.keys.load(cfg.provider) is None:
            return "off"
        if not properties.active(svc.core.db) and not verdict_categories(svc.core.db):
            return "off"
        if self.blocked or svc.blocked_reason(cfg):
            return "blocked"
        return "idle"

    def trigger(self) -> tuple[bool, str | None]:
        """`POST /llm/poll`: poll now (forced: also when nothing changed)."""
        if self.running:
            return False, "Eine Abfrage läuft gerade."
        svc = self.service
        cfg = svc.config()
        if not cfg.enabled:
            return False, "Externe KI ist ausgeschaltet."
        if not cfg.poll:
            return False, "„Eigenschaften abfragen“ ist ausgeschaltet."
        if svc.keys.load(cfg.provider) is None:
            return False, "Kein gültiger API-Schlüssel gespeichert."
        if not properties.active(svc.core.db) and not verdict_categories(svc.core.db):
            return False, "Keine Eigenschaft und keine Kategorie mit KI-Urteil."
        reason = svc.blocked_reason(cfg)
        if reason is not None:
            return False, reason
        self._force = True
        if self._ticker.alive:
            self._ticker.poke()
        else:
            # no lifecycle (admin API without the wall's start, tests): a one-off thread
            threading.Thread(target=self.run, kwargs={"force": True}, daemon=True).start()
        return True, None

    def run(self, *, force: bool = False) -> PollResult | None:
        if not self._run_lock.acquire(blocking=False):
            return None
        self.running = True
        try:
            result = poll_once(self.service, force=force)
        except Exception as exc:
            log.exception("llm poll failed")
            self.last_error = type(exc).__name__
            result = None
        finally:
            self.running = False
            self._run_lock.release()
        if result is not None:
            self.last_poll_at = now_iso()
            self.blocked = result.reason if _budget(result) else None
            if result.state != "skipped":
                self.last_error = result.reason
        return result

    def step(self) -> float:
        cfg = self.service.config()
        interval = cfg.poll_interval_s
        now = datetime.now(UTC)
        due = (
            datetime.fromisoformat(self.last_poll_at) + timedelta(seconds=interval)
            if self.last_poll_at
            else now
        )
        if self._force or now >= due:
            force, self._force = self._force, False
            result = self.run(force=force)
            if result is None and not force:
                # nothing to do: look again soon, a change pokes us anyway
                self.next_poll_at = None
                return RECHECK_S
            due = datetime.now(UTC) + timedelta(seconds=interval)
        self.next_poll_at = due.isoformat(timespec="milliseconds")
        return min(RECHECK_S, max(0.05, (due - datetime.now(UTC)).total_seconds()))


def _budget(result: PollResult) -> bool:
    from .budget import BLOCKED

    return bool(result.reason and result.reason.startswith(BLOCKED))
