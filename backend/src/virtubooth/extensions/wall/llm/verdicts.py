"""The AI verdict (categories v2): comments under a category's winners.

The AI comments, it never ranks. Per enabled category with a `verdict`
(`{prompt|null, count 1–5, model, effort}`) the top `count` winners (only photos
the poll may send) each get exactly one comment, tied to that photo. Comments
are cached per (category, photo) with the hash of what wrote them (system
prompt, the host's task, the resolved model, the effort): a winner that already
has a comment with the current hash keeps it (no call); only new pairs go out,
in one call per category. A changed prompt, model or effort invalidates the
category's comments (they are rewritten when needed).

The call gets each photo's rank, author's shown name, objects with the scores of
the properties the spec reads, its focus object and the displayed value; the
answer's comments are checked (the photo must be one sent, the object index must
exist in it, text cleaned and ≤ 160 chars) and stored.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ....core.clock import now_iso
from ....db.database import Database
from ..enrich import engine
from . import ports, pricing, prompts
from .poller import PolledPhoto, still_allowed
from .prompts import MAX_VERDICT, clean_text
from .providers.base import PhotoLine, Provider, ProviderError, TokenUsage, VerdictOut

if TYPE_CHECKING:
    from .config import LlmConfig
    from .service import LlmService

log = logging.getLogger("virtubooth.llm")

_ASCII_WORD = re.compile(r"[A-Za-z0-9]")


def referenced_properties(spec: Mapping[str, Any]) -> list[str]:
    """Property names a (validated) spec reads, in order."""
    return engine.references(spec)


def scores_of(
    db: Database, names: Sequence[str], photo_ids: Sequence[int]
) -> dict[int, dict[str, list[float | None]]]:
    out: dict[int, dict[str, list[float | None]]] = {}
    if not names or not photo_ids:
        return out
    n_marks = ",".join("?" for _ in names)
    p_marks = ",".join("?" for _ in photo_ids)
    for r in db.all(
        "SELECT lp.name, s.photo_id, s.scores FROM property_scores s "
        "JOIN llm_properties lp ON lp.id = s.property_id "
        f"WHERE lp.name IN ({n_marks}) AND s.photo_id IN ({p_marks})",
        [*names, *photo_ids],
    ):
        out.setdefault(r["photo_id"], {})[r["name"]] = json.loads(r["scores"])
    return out


def verdict_model(cfg: LlmConfig, verdict: Mapping[str, Any]) -> str:
    return pricing.resolve_verdict_model(cfg.provider, verdict.get("model"))


def config_hash(spec: Mapping[str, Any], model: str) -> str:
    """What a category's comments depend on: the system prompt, the host's task
    (the default names the title), the model and the effort."""
    verdict = spec.get("verdict") or {}
    data = [
        prompts.VERDICT_SYSTEM,
        prompts.verdict_prompt(verdict.get("prompt"), str(spec.get("title", ""))),
        model,
        verdict.get("effort", "low"),
    ]
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()[:32]


def clean_comment(out: VerdictOut, photo: PolledPhoto) -> tuple[str, str | None, int | None] | None:
    """(text, emoji, object idx) or None when the text is empty."""
    text = clean_text(out.text, MAX_VERDICT)
    if not text:
        return None
    emoji = clean_text(out.emoji, 16) if out.emoji else None
    if emoji is not None and (not emoji or _ASCII_WORD.search(emoji)):
        emoji = None
    idx = out.object_index
    if idx is None or not 0 <= idx < len(photo.labels):
        idx = None
    return text, emoji, idx


def _verdict_call(
    prompt: str, lines: list[PhotoLine], effort: str = "low"
) -> Callable[[Provider, str], tuple[list[VerdictOut], TokenUsage]]:
    def run(provider: Provider, model: str) -> tuple[list[VerdictOut], TokenUsage]:
        return provider.verdict(prompt, lines, model=model, effort=effort)

    return run


def _cached(db: Database, cid: str) -> dict[int, str]:
    """photo id → config hash of the category's stored comments."""
    return {
        int(r["photo_id"]): r["config_hash"]
        for r in db.all(
            "SELECT photo_id, config_hash FROM wall_category_comments WHERE category_id=?",
            (cid,),
        )
    }


def _store(
    db: Database,
    cid: str,
    photo_id: int,
    digest: str,
    poll_id: int,
    value: tuple[str, str | None, int | None],
) -> None:
    text, emoji, idx = value
    with db.tx() as c:
        c.execute(
            "INSERT INTO wall_category_comments (category_id, photo_id, config_hash, text, emoji, "
            "object_idx, poll_id, created_at) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(category_id, photo_id) DO UPDATE SET config_hash=excluded.config_hash, "
            "text=excluded.text, emoji=excluded.emoji, object_idx=excluded.object_idx, "
            "poll_id=excluded.poll_id, created_at=excluded.created_at",
            (cid, photo_id, digest, text, emoji, idx, poll_id, now_iso()),
        )


def _invalidate(db: Database, cid: str, digest: str) -> None:
    with db.tx() as c:
        c.execute(
            "DELETE FROM wall_category_comments WHERE category_id=? AND config_hash != ?",
            (cid, digest),
        )


def _value_text(w: engine.Winner) -> str | None:
    return w.label or None


def run_verdicts(
    svc: LlmService,
    cfg: LlmConfig,
    cats: Sequence[tuple[str, dict[str, Any]]],
    photos: Sequence[PolledPhoto],
    poll_id: int,
) -> tuple[int, int, list[str], str | None]:
    """(calls, successful calls, error texts, stop reason when the budget or
    the key ended the run)."""
    from .service import Unavailable

    db = svc.core.db
    by_id = {p.id: p for p in photos}
    calls = ok = 0
    errors: list[str] = []
    for cid, spec in cats:
        verdict = spec.get("verdict")
        if not isinstance(verdict, dict):
            continue
        count = int(verdict.get("count") or 1)
        model = verdict_model(cfg, verdict)
        digest = config_hash(spec, model)
        _invalidate(db, cid, digest)
        try:
            winners = ports.evaluate(svc.core, spec, limit=count)
        except Exception:
            log.exception("llm verdict: evaluating %s failed", cid)
            errors.append(f"{cid}: Auswertung fehlgeschlagen")
            continue
        cached = _cached(db, cid)
        # only photos the poll may send; the live flags once more right before it
        allowed = still_allowed(db, [w.photo_id for w in winners if w.photo_id in by_id])
        todo = [
            (rank, w)
            for rank, w in enumerate(winners[:count], start=1)
            if w.photo_id in allowed and cached.get(w.photo_id) != digest
        ]
        if not todo:
            continue
        names = referenced_properties(spec)
        scores = scores_of(db, names, [w.photo_id for _, w in todo])
        lines: list[PhotoLine] = []
        for rank, w in todo:
            p = by_id[w.photo_id]
            mine = scores.get(p.id, {})
            lines.append(
                PhotoLine(
                    ref=p.ref,
                    author=p.author,
                    labels=p.labels,
                    scores={n: mine[n] for n in names if n in mine and len(mine[n]) == len(p.labels)},
                    rank=rank,
                    focus=w.object_idx if w.object_idx is not None and w.object_idx < len(p.labels) else None,
                    value=_value_text(w),
                )
            )  # fmt: skip
        sent = {line.ref: by_id[w.photo_id] for line, (_, w) in zip(lines, todo, strict=True)}
        prompt = prompts.verdict_prompt(verdict.get("prompt"), str(spec.get("title", "")))
        effort = str(verdict.get("effort") or "low")
        call_cfg = cfg.model_copy(update={"model": model, "effort": effort})
        calls += 1
        try:
            out, _ = svc.call("verdict", cid, _verdict_call(prompt, lines, effort), config=call_cfg)
        except Unavailable as exc:
            return calls, ok, errors, exc.message
        except ProviderError as exc:
            errors.append(f"{cid}: {exc.message}")
            continue
        stored = 0
        done: set[str] = set()
        for item in out:
            ref = (item.photo or "").strip()
            photo = sent.get(ref)
            if photo is None or ref in done:
                continue
            value = clean_comment(item, photo)
            if value is None:
                continue
            done.add(ref)
            _store(db, cid, photo.id, digest, poll_id, value)
            stored += 1
        if not stored:
            errors.append(f"{cid}: leere Antwort")
            continue
        if stored < len(sent):
            log.info("llm verdict %s: %d of %d comments", cid, stored, len(sent))
        ok += 1
    return calls, ok, errors, None
