"""Category verdicts: after the property scores, one call per enabled category
whose spec has a `verdict` prompt. The top 5 winners (only photos the poll may
send) go out with the author's shown name, their labels and the scores of the
properties the spec refers to; the answer `{text, emoji, photo, object_index}`
is checked (refs must be sent ones, the index must exist in that photo, text
cleaned and ≤ 160 chars) and stored as the category's latest verdict.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ....core.clock import now_iso
from ....db.database import Database
from . import ports
from .poller import PolledPhoto, still_allowed
from .prompts import MAX_VERDICT, clean_text
from .providers.base import PhotoLine, Provider, ProviderError, TokenUsage, VerdictOut

if TYPE_CHECKING:
    from .config import LlmConfig
    from .service import LlmService

log = logging.getLogger("virtubooth.llm")

TOP = 5
_PROP_REF = re.compile(r"prop\.([a-z][a-z0-9_]{1,30})\.")
_ASCII_WORD = re.compile(r"[A-Za-z0-9]")


def referenced_properties(spec: Mapping[str, Any]) -> list[str]:
    """Property names the spec uses (`prop.<name>.…` anywhere), in order."""
    return list(dict.fromkeys(_PROP_REF.findall(json.dumps(spec, ensure_ascii=False))))


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


def clean_verdict(
    out: VerdictOut, sent: Mapping[str, PolledPhoto]
) -> tuple[str, str | None, int | None, int | None] | None:
    """(text, emoji, photo id, object idx) or None when the text is empty."""
    text = clean_text(out.text, MAX_VERDICT)
    if not text:
        return None
    emoji = clean_text(out.emoji, 16) if out.emoji else None
    if emoji is not None and (not emoji or _ASCII_WORD.search(emoji)):
        emoji = None
    photo = sent.get(out.photo.strip()) if out.photo else None
    idx = out.object_index
    if photo is None or idx is None or not 0 <= idx < len(photo.labels):
        idx = None
    return text, emoji, (photo.id if photo else None), idx


def _verdict_call(
    prompt: str, lines: list[PhotoLine]
) -> Callable[[Provider, str], tuple[VerdictOut, TokenUsage]]:
    def run(provider: Provider, model: str) -> tuple[VerdictOut, TokenUsage]:
        return provider.verdict(prompt, lines, model=model)

    return run


def _store(
    db: Database,
    category_id: str,
    poll_id: int,
    value: tuple[str, str | None, int | None, int | None],
) -> None:
    text, emoji, photo_id, idx = value
    with db.tx() as c:
        c.execute(
            "INSERT INTO wall_category_verdicts (category_id, text, emoji, photo_id, object_idx, "
            "poll_id, created_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(category_id) DO UPDATE SET "
            "text=excluded.text, emoji=excluded.emoji, photo_id=excluded.photo_id, "
            "object_idx=excluded.object_idx, poll_id=excluded.poll_id, "
            "created_at=excluded.created_at",
            (category_id, text, emoji, photo_id, idx, poll_id, now_iso()),
        )


def _drop(db: Database, category_id: str) -> None:
    with db.tx() as c:
        c.execute("DELETE FROM wall_category_verdicts WHERE category_id=?", (category_id,))


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
        prompt = str(verdict.get("prompt", "")).strip() if isinstance(verdict, dict) else ""
        if not prompt:
            continue
        try:
            winners = ports.evaluate(svc.core, spec, limit=TOP)
        except Exception:
            log.exception("llm verdict: evaluating %s failed", cid)
            errors.append(f"{cid}: Auswertung fehlgeschlagen")
            continue
        # only photos the poll may send; the live flags once more right before it
        allowed = still_allowed(db, [w.photo_id for w in winners if w.photo_id in by_id])
        chosen = [by_id[w.photo_id] for w in winners if w.photo_id in allowed][:TOP]
        if not chosen:
            _drop(db, cid)
            continue
        names = referenced_properties(spec)
        scores = scores_of(db, names, [p.id for p in chosen])
        lines = [
            PhotoLine(
                ref=p.ref,
                author=p.author,
                labels=p.labels,
                scores={
                    n: scores[p.id][n]
                    for n in names
                    if n in scores.get(p.id, {}) and len(scores[p.id][n]) == len(p.labels)
                },
            )
            for p in chosen
        ]
        sent = {p.ref: p for p in chosen}
        calls += 1
        try:
            out, _ = svc.call(
                "verdict",
                cid,
                _verdict_call(prompt, lines),
                config=cfg,
            )
        except Unavailable as exc:
            return calls, ok, errors, exc.message
        except ProviderError as exc:
            errors.append(f"{cid}: {exc.message}")
            continue
        value = clean_verdict(out, sent)
        if value is None:
            errors.append(f"{cid}: leere Antwort")
            continue
        ok += 1
        _store(db, cid, poll_id, value)
    return calls, ok, errors, None
