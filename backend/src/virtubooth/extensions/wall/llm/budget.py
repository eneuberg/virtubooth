"""The cost brake (PLAN-NIGHT N12): one `llm_usage` row per provider call
(failed ones too, `ok = 0`), totals for the party and the party's day, and
`blocked()` before every call. Costs are estimates from pricing.py, in
micro-USD; the limits are in USD and/or calls, null = no limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ....core.clock import DEFAULT_TIMEZONE, now_iso
from ....db.database import Database
from . import pricing
from .config import BudgetConfig
from .providers.base import TokenUsage

Kind = Literal["detect", "property", "verdict", "test"]
BLOCKED = "Budget erreicht – externe KI pausiert"


@dataclass(frozen=True)
class Totals:
    calls: int
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int

    @property
    def cost_usd(self) -> float:
        return self.cost_micro_usd / 1_000_000


@dataclass(frozen=True)
class KindTotals:
    kind: str
    ref: str | None
    calls: int
    tokens: int
    cost_micro_usd: int


def party_day(timezone: str) -> str:
    """Today's date on the party's clock (the daily limit's day)."""
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(DEFAULT_TIMEZONE)
    return datetime.now(zone).date().isoformat()


def record(
    db: Database,
    *,
    kind: Kind,
    ref: str | None,
    provider: str,
    model: str,
    usage: TokenUsage,
    ok: bool,
    timezone: str,
    ms: int | None = None,
) -> int:
    """Store one call; returns its estimated cost in micro-USD. `ms`: how long it took."""
    cost = pricing.cost_micro_usd(model, usage.input_tokens, usage.output_tokens)
    with db.tx() as c:
        c.execute(
            "INSERT INTO llm_usage (at, day, kind, ref, provider, model, input_tokens, "
            "output_tokens, cost_micro_usd, ok, ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                now_iso(),
                party_day(timezone),
                kind,
                ref,
                provider,
                model,
                usage.input_tokens,
                usage.output_tokens,
                cost,
                1 if ok else 0,
                ms,
            ),
        )
    return cost


def totals(db: Database, day: str | None = None) -> Totals:
    sql = (
        "SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens), 0) AS i, "
        "COALESCE(SUM(output_tokens), 0) AS o, COALESCE(SUM(cost_micro_usd), 0) AS c "
        "FROM llm_usage"
    )
    row = db.one(sql + " WHERE day=?", (day,)) if day else db.one(sql)
    assert row is not None
    return Totals(row["calls"], row["i"], row["o"], row["c"])


def by_kind(db: Database) -> list[KindTotals]:
    """Per property / verdict category; detection and test images as one row
    each (ref None), not one per photo."""
    return [
        KindTotals(r["kind"], r["r"], r["calls"], r["tokens"], r["cost"])
        for r in db.all(
            "SELECT kind, CASE WHEN kind IN ('detect', 'test') THEN NULL ELSE ref END AS r, "
            "COUNT(*) AS calls, SUM(input_tokens + output_tokens) AS tokens, "
            "SUM(cost_micro_usd) AS cost FROM llm_usage GROUP BY kind, r "
            "ORDER BY cost DESC, calls DESC, kind, r"
        )
    ]


def _usd(micro: int) -> str:
    return f"{micro / 1_000_000:.2f} $".replace(".", ",")


def blocked(db: Database, budget: BudgetConfig, timezone: str) -> str | None:
    """Why no call may be made now (German), None while the budget allows it."""
    party = totals(db)
    today = totals(db, party_day(timezone))
    if budget.party_usd is not None and party.cost_micro_usd >= budget.party_usd * 1_000_000:
        return f"{BLOCKED} (Party: {_usd(party.cost_micro_usd)} von {_usd(round(budget.party_usd * 1_000_000))})."
    if budget.party_calls is not None and party.calls >= budget.party_calls:
        return f"{BLOCKED} (Party: {party.calls} von {budget.party_calls} Aufrufen)."
    if budget.daily_usd is not None and today.cost_micro_usd >= budget.daily_usd * 1_000_000:
        return f"{BLOCKED} (heute: {_usd(today.cost_micro_usd)} von {_usd(round(budget.daily_usd * 1_000_000))})."
    if budget.daily_calls is not None and today.calls >= budget.daily_calls:
        return f"{BLOCKED} (heute: {today.calls} von {budget.daily_calls} Aufrufen)."
    return None


@dataclass(frozen=True)
class DetectStats:
    """The AI detector's numbers for the Modelle row (all detection calls so far)."""

    processed: int
    errors: int
    avg_ms: float | None
    last_ms: float | None
    cost_micro_usd: int


def detect_stats(db: Database) -> DetectStats:
    row = db.one(
        "SELECT COALESCE(SUM(ok), 0) AS ok, COUNT(*) - COALESCE(SUM(ok), 0) AS bad, "
        "AVG(ms) AS avg_ms, COALESCE(SUM(cost_micro_usd), 0) AS cost "
        "FROM llm_usage WHERE kind = 'detect'"
    )
    last = db.one(
        "SELECT ms FROM llm_usage WHERE kind = 'detect' AND ms IS NOT NULL ORDER BY id DESC LIMIT 1"
    )
    assert row is not None
    avg = row["avg_ms"]
    return DetectStats(
        processed=int(row["ok"]),
        errors=int(row["bad"]),
        avg_ms=round(float(avg), 1) if avg is not None else None,
        last_ms=float(last["ms"]) if last is not None else None,
        cost_micro_usd=int(row["cost"]),
    )
