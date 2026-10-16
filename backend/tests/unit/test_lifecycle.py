"""Category lifecycle (categories v2, PLAN §4a): every event's effect on the
categories and the poll, through `lifecycle.reconcile` (idempotent)."""

from __future__ import annotations

from virtubooth.extensions.wall.enrich import engine, lifecycle
from virtubooth.extensions.wall.llm import config as llm_config
from virtubooth.extensions.wall.llm import properties

from ..llm_fakes import add_property, property_spec, setup_llm, store_key

VERDICT = {"prompt": None, "count": 1, "model": None, "effort": "low"}


def state(core, cid: str) -> tuple[int, str | None, str | None]:
    r = core.db.one("SELECT enabled, off_reason, off_detail FROM wall_categories WHERE id=?",
                    (cid,))  # fmt: skip
    return (r["enabled"], r["off_reason"], r["off_detail"])


def add(core, cid: str, spec: dict, *, enabled: bool = True) -> None:
    engine.insert(core.db, cid, engine.validate(spec), enabled=enabled, preset=None, by="t")


def plain() -> dict:
    return {"version": 2, "emoji": "👥", "title": "Volles Haus",
            "rank": {"by": {"kind": "value", "key": "people"}}}  # fmt: skip


def test_lock_reasons_in_order(core):
    props = {"coolness": False, "weg": True}
    spec = engine.validate(property_spec("coolness"))
    assert lifecycle.lock_of(spec, props, ai_ready=True) is None
    assert lifecycle.lock_of(spec, props, ai_ready=False).reason == "ai_off"
    trashed = engine.validate(property_spec("weg"))
    assert lifecycle.lock_of(trashed, props, True) == lifecycle.Lock("property_trashed", "weg")
    unknown = engine.validate(property_spec("unbekannt"))
    assert lifecycle.lock_of(unknown, props, False) == lifecycle.Lock(
        "property_missing", "unbekannt"
    )
    # a preset property that does not exist yet is created when switched on: no lock
    assert lifecycle.lock_of(engine.validate(property_spec("goofiness")), {}, True) is None
    # no property: never locked (a verdict alone does not lock either)
    assert lifecycle.lock_of(engine.validate(plain() | {"verdict": VERDICT}), {}, False) is None


def test_host_switches_and_the_reason(core):
    add(core, "haus", plain())
    engine.switch_off(core.db, "haus", "ai_off", None)
    assert state(core, "haus") == (0, "ai_off", None)
    spec = engine.validate(plain())
    # the host saves it switched off: the automatic reason stays (the banner)
    engine.update(core.db, "haus", spec, enabled=False, by="t")
    assert state(core, "haus") == (0, "ai_off", None)
    # switched on and off by the host: no reason
    engine.update(core.db, "haus", spec, enabled=True, by="t")
    assert state(core, "haus") == (1, None, None)
    engine.update(core.db, "haus", spec, enabled=False, by="t")
    assert state(core, "haus") == (0, None, None)


def test_trash_and_restore(core):
    svc = setup_llm(core)
    add_property(core, used=False)
    add(core, "cool", property_spec("coolness"))
    add(core, "cool_aus", property_spec("coolness"), enabled=False)
    assert [p.name for p in properties.polled(core.db)] == ["coolness"]
    properties.set_trashed(core.db, core.repos.audit, "coolness", True, actor="t")
    assert state(core, "cool") == (0, "property_trashed", "coolness")
    assert state(core, "cool_aus") == (0, None, None)  # was off already: no reason
    assert properties.polled(core.db) == []
    # restored: stays off, but can be switched on again (no lock)
    properties.set_trashed(core.db, core.repos.audit, "coolness", False, actor="t")
    assert state(core, "cool") == (0, "property_trashed", "coolness")
    assert lifecycle.locks(core.db, svc.ai_ready()) == {}
    assert properties.polled(core.db) == []  # nothing polled until one is on
    del svc


def test_the_ai_off_switches_property_categories_off(core):
    svc = setup_llm(core)
    add_property(core, used=False)
    add(core, "cool", property_spec("coolness"))
    add(core, "haus", plain())
    add(core, "urteil", plain() | {"verdict": VERDICT})
    assert svc.ai_ready() and svc.reconcile() == []
    for change in ({"enabled": False}, {"poll": False}):
        cfg = svc.config().model_copy(update=change)
        llm_config.save_config(core.repos.app_settings, cfg, by="t")
        assert not svc.ai_ready()
        assert svc.reconcile() == [("cool", "ai_off", None)]
        assert state(core, "cool") == (0, "ai_off", None)
        # without a property it stays on; a verdict alone stays on too (paused)
        assert state(core, "haus")[0] == 1 and state(core, "urteil")[0] == 1
        llm_config.save_config(core.repos.app_settings, svc.config().model_copy(
            update={"enabled": True, "poll": True}), by="t")  # fmt: skip
        # the AI back: stays off (no automatic switching on), but unlocked
        assert svc.ai_ready() and svc.reconcile() == []
        assert state(core, "cool") == (0, "ai_off", None)
        assert lifecycle.locks(core.db, True) == {}
        engine.update(core.db, "cool", engine.validate(property_spec("coolness")), enabled=True,
                      by="t")  # fmt: skip
    # the key deleted
    svc.clear_key("anthropic", actor="t")
    assert state(core, "cool") == (0, "ai_off", None)
    store_key(core)
    assert svc.ai_ready()
    del svc


def test_a_budget_brake_switches_nothing_off(core):
    svc = setup_llm(core)
    add_property(core, used=False)
    add(core, "cool", property_spec("coolness"))
    cfg = svc.config().model_copy(update={"budget": llm_config.BudgetConfig(party_usd=0.0)})
    llm_config.save_config(core.repos.app_settings, cfg, by="t")
    assert svc.blocked_reason() is not None  # paused, not off
    assert svc.ai_ready() and svc.reconcile() == []
    assert state(core, "cool") == (1, None, None)
    del svc


def test_reconcile_is_idempotent_and_only_touches_enabled_ones(core):
    add_property(core, used=False)
    add(core, "a", property_spec("coolness"))
    add(core, "b", property_spec("unbekannt"))
    add(core, "c", property_spec("coolness"), enabled=False)
    first = lifecycle.reconcile(core.db, ai_ready=False)
    assert sorted(first) == [("a", "ai_off", None), ("b", "property_missing", "unbekannt")]
    at = core.db.one("SELECT off_at FROM wall_categories WHERE id='a'")[0]
    assert lifecycle.reconcile(core.db, ai_ready=False) == []
    assert core.db.one("SELECT off_at FROM wall_categories WHERE id='a'")[0] == at
    assert state(core, "c") == (0, None, None)


def test_polled_and_used_by(core):
    add_property(core, used=False)
    add_property(core, "lustig", "Wie lustig?", used=False)
    add(core, "a", property_spec("coolness"))
    add(core, "b", property_spec("lustig"), enabled=False)
    assert lifecycle.polled_names(core.db) == ["coolness"]
    assert lifecycle.polled_names(core.db, ai_ready=False) == []
    assert lifecycle.used_by(core.db) == {
        "coolness": [("a", "Bestes coolness", True)],
        "lustig": [("b", "Bestes lustig", False)],
    }
    assert [c.id for c in lifecycle.users_of(core.db, "lustig")] == ["b"]
