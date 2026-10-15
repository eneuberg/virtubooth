"""The cost brake (PLAN-NIGHT N12): every call metered, every call kind stops
at the party or daily limit (USD or calls)."""

from __future__ import annotations

import pytest

from virtubooth.extensions.wall.llm import budget, pricing
from virtubooth.extensions.wall.llm.config import BudgetConfig
from virtubooth.extensions.wall.llm.detect import DetectionRunner
from virtubooth.extensions.wall.llm.poller import poll_once
from virtubooth.extensions.wall.llm.providers.base import ProviderError, TokenUsage
from virtubooth.extensions.wall.llm.service import Unavailable

from ..llm_fakes import FakeProvider, add_guest, add_photo, add_property, setup_llm

TZ = "Europe/Berlin"


def usage_rows(core):
    return core.db.all(
        "SELECT kind, ref, ok, input_tokens, output_tokens, cost_micro_usd FROM llm_usage"
    )


def test_prices():
    # Haiku 5.5: $0.10 in / $0.50 out per million tokens
    assert pricing.cost_micro_usd("claude-haiku-5-5", 100_000, 0) == 10_000
    assert pricing.cost_micro_usd("claude-haiku-5-5", 0, 1_000_000) == 500_000
    assert pricing.cost_micro_usd("claude-haiku-5-5", 1000, 200) == 200
    # above 100K input tokens in one request: $0.50 / $2.50
    assert pricing.cost_micro_usd("claude-haiku-5-5", 200_000, 0) == 100_000
    assert pricing.cost_micro_usd("claude-sonnet-5-5", 1000, 1000) == 12_000
    assert pricing.cost_micro_usd("claude-opus-5-5", 1000, 1000) == 24_000
    assert pricing.cost_micro_usd("unknown", 1000, 1000) == 0
    # a paid call never rounds to free
    assert pricing.cost_micro_usd("claude-haiku-5-5", 1, 0) == 1


def _spend(core, n: int, *, day: str | None = None) -> None:
    """n calls of $0.10 each (200K output tokens of Haiku 5.5)."""
    for _ in range(n):
        budget.record(
            core.db,
            kind="property",
            ref="coolness",
            provider="anthropic",
            model="claude-haiku-5-5",
            usage=TokenUsage(0, 200_000),
            ok=True,
            timezone=TZ,
        )
    if day:
        with core.db.tx() as c:
            c.execute("UPDATE llm_usage SET day=?", (day,))


@pytest.mark.parametrize(
    ("limits", "spent", "blocked"),
    [
        (BudgetConfig(party_usd=0.25, daily_usd=None), 2, False),  # $0.20
        (BudgetConfig(party_usd=0.2, daily_usd=None), 2, True),  # $0.20 reached
        (BudgetConfig(party_usd=None, party_calls=3, daily_usd=None), 2, False),
        (BudgetConfig(party_usd=None, party_calls=2, daily_usd=None), 2, True),
        (BudgetConfig(party_usd=None, daily_usd=0.1), 1, True),
        (BudgetConfig(party_usd=None, daily_usd=None, daily_calls=1), 1, True),
        (BudgetConfig(party_usd=None, daily_usd=None), 50, False),
    ],
)
def test_limits(core, limits, spent, blocked):
    _spend(core, spent)
    reason = budget.blocked(core.db, limits, TZ)
    assert (reason is not None) is blocked
    if blocked:
        assert reason.startswith("Budget erreicht – externe KI pausiert")


def test_daily_limit_only_counts_today(core):
    _spend(core, 3, day="2020-01-01")
    limits = BudgetConfig(party_usd=None, daily_usd=0.1, daily_calls=1)
    assert budget.blocked(core.db, limits, TZ) is None
    assert budget.totals(core.db).calls == 3
    assert budget.totals(core.db, budget.party_day(TZ)).calls == 0
    # the party limit still sees them
    assert budget.blocked(core.db, BudgetConfig(party_calls=3, daily_usd=None), TZ)


def test_every_call_kind_stops_at_the_limit(core):
    fake = FakeProvider()
    svc = setup_llm(
        core,
        fake,
        detect={"external": True},
        budget={"party_usd": None, "party_calls": 1, "daily_usd": None, "daily_calls": None},
    )
    uid = add_guest(core)
    add_photo(core, uid, ai_detect=True)
    add_property(core)
    _spend(core, 1)
    for kind in ("detect", "property", "verdict", "test"):
        with pytest.raises(Unavailable) as exc:
            svc.call(kind, None, lambda p, m: (None, TokenUsage()))
        assert exc.value.code == "llm_budget_exhausted"
    runner = DetectionRunner(svc)
    assert runner.run_once() == "blocked" and runner.blocked
    result = poll_once(svc, force=True)
    assert result is not None and result.state == "skipped" and "Budget erreicht" in result.reason
    svc.poller.run(force=True)
    assert svc.poller.state() == "blocked"
    assert fake.detected == [] and fake.scored == [] and fake.verdicts == []
    # nothing was metered for the refused calls
    assert len(usage_rows(core)) == 1


def test_failed_calls_are_metered(core):
    fake = FakeProvider()
    svc = setup_llm(core, fake)

    def fail(provider, model):
        raise ProviderError("kaputt", kind="bad_output", usage=TokenUsage(500, 50))

    with pytest.raises(ProviderError):
        svc.call("verdict", "coolstes_objekt", fail)
    with pytest.raises(ProviderError) as exc:
        svc.call("verdict", "x", lambda p, m: 1 / 0)
    assert exc.value.kind == "other"
    rows = usage_rows(core)
    assert [(r["kind"], r["ref"], r["ok"], r["input_tokens"]) for r in rows] == [
        ("verdict", "coolstes_objekt", 0, 500),
        ("verdict", "x", 0, 0),
    ]
    assert rows[0]["cost_micro_usd"] == pricing.cost_micro_usd("claude-haiku-5-5", 500, 50)


def test_usage_route(admin, core, app):
    from virtubooth.extensions.wall.llm import admin_api

    app.include_router(admin_api.router, prefix="/api/x/wall")
    _spend(core, 2)
    body = admin.get("/api/x/wall/admin/llm/usage").json()
    assert body["party"] == {
        "calls": 2, "input_tokens": 0, "output_tokens": 400_000, "cost_usd": 0.2,
    }  # fmt: skip
    assert body["today"]["calls"] == 2
    assert body["by_kind"] == [
        {"kind": "property", "ref": "coolness", "calls": 2, "tokens": 400_000, "cost_usd": 0.2}
    ]
    assert body["blocked"] is False and body["budget"]["party_usd"] == 5.0


def test_detection_usage_is_one_row_not_one_per_photo(core):
    for ref in ("photo1", "photo2", None):
        budget.record(
            core.db, kind="detect" if ref else "test", ref=ref, provider="anthropic",
            model="claude-haiku-5-5", usage=TokenUsage(100, 10), ok=True, timezone=TZ,
        )  # fmt: skip
    budget.record(
        core.db, kind="detect", ref="photo3", provider="anthropic",
        model="claude-haiku-5-5", usage=TokenUsage(100, 10), ok=True, timezone=TZ,
    )  # fmt: skip
    rows = [(r.kind, r.ref, r.calls) for r in budget.by_kind(core.db)]
    assert rows == [("detect", None, 3), ("test", None, 1)]
