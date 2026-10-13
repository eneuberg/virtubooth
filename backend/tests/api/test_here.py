"""The guest page's heartbeat (`POST /api/here`): online time and visits of
joined guests, "online now", the visitor's last seen for browsers that have not
joined, "Aktiv jetzt" for idle open pages, one write per beat."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from virtubooth.core.clock import iso
from virtubooth.domain.overview import ONLINE_GAP_SECONDS, beat, is_online
from virtubooth.services.presence import THROTTLE_SECONDS

from ..conftest import ORIGIN, scan
from .test_admin_dashboard import _age_everyone, identify, overview, user_id_of, visitor_of

SENTENCE = (
    "Die Gastgeber sehen zu jedem Gast eine kleine Statistik: wie viele Fotos du gemacht "
    "hast, wie lange die Seite bei dir offen war und über welchen QR-Code du gekommen bist."
)
T0 = datetime(2026, 10, 13, 21, 0, tzinfo=UTC)


def here(client, visible=True, status=200):
    r = client.post("/api/here", json={"visible": visible}, headers=ORIGIN)
    assert r.status_code == status, r.text
    return r.json()


def online(core, client) -> tuple[int, int, str | None]:
    user = core.repos.users.get(user_id_of(core, client))
    assert user is not None
    return user.online_seconds, user.online_sessions, user.online_at


@pytest.fixture
def at(core):
    """The beat's wall clock: set `at[0]`."""
    moment = [T0]
    core.services.presence.now = lambda: moment[0]
    return moment


def test_needs_party_access(client):
    r = client.post("/api/here", json={"visible": True}, headers=ORIGIN)
    assert r.status_code == 404 and r.json()["error"] == "scan_qr"


def test_csrf_origin_is_enforced(guest, core):
    g = guest()
    assert g.post("/api/here", json={"visible": True}).status_code == 403
    r = g.post("/api/here", json={"visible": True}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    assert online(core, g) == (0, 0, None)


def test_a_browser_that_did_not_join_refreshes_its_visitor(client, core):
    clock = [1000.0]
    core.services.presence.clock = lambda: clock[0]
    scan(client)
    vid = visitor_of(core, client)
    old = _age_everyone(core)
    clock[0] += THROTTLE_SECONDS + 1
    assert here(client) == {"ok": True}
    seen = core.db.one("SELECT last_seen_at FROM visitors WHERE id=?", (vid,))[0]
    assert seen > old
    assert core.repos.users.list() == []

    # throttled like any other request
    old = _age_everyone(core)
    clock[0] += 1
    here(client)
    assert core.db.one("SELECT last_seen_at FROM visitors WHERE id=?", (vid,))[0] == old


def test_online_time_adds_up_beat_by_beat(guest, core, at):
    g = guest()
    assert here(g) == {"ok": True}
    assert online(core, g) == (0, 1, iso(T0))  # a visit starts, nothing added yet

    at[0] = T0 + timedelta(seconds=60)
    here(g)
    assert online(core, g) == (60, 1, iso(at[0]))

    at[0] += timedelta(seconds=59.7)  # whole seconds
    here(g)
    assert online(core, g)[:2] == (119, 1)

    # more than the gap without a beat: a new visit, the gap is not counted
    at[0] += timedelta(seconds=200)
    here(g)
    assert online(core, g) == (119, 2, iso(at[0]))

    # hidden: the time since the last beat counts, the visit closes
    at[0] += timedelta(seconds=45)
    here(g, visible=False)
    assert online(core, g) == (164, 2, None)
    user = core.repos.users.get(user_id_of(core, g))
    assert user is not None and user.last_seen_at == iso(at[0])

    # a second hidden beat (pagehide after visibilitychange) adds nothing
    at[0] += timedelta(seconds=5)
    here(g, visible=False)
    assert online(core, g) == (164, 2, None)

    # visible again: the next visit
    at[0] += timedelta(seconds=30)
    here(g)
    assert online(core, g) == (164, 3, iso(at[0]))


def test_a_hidden_beat_after_the_gap_adds_nothing(guest, core, at):
    g = guest()
    here(g)
    at[0] = T0 + timedelta(seconds=ONLINE_GAP_SECONDS + 1)
    here(g, visible=False)
    assert online(core, g) == (0, 1, None)


def test_the_beat_rules():
    t = iso(T0)
    assert beat(None, T0, visible=True) == beat(t, T0 + timedelta(seconds=151), visible=True)
    assert beat(None, T0, visible=True).new_visit
    assert not beat(None, T0, visible=False).new_visit
    assert beat(t, T0 + timedelta(seconds=150), visible=False).add_seconds == 150
    assert beat(t, T0 + timedelta(seconds=150.9), visible=True).add_seconds == 0  # past the gap
    assert beat(t, T0 - timedelta(seconds=3), visible=True).add_seconds == 0  # never negative
    assert is_online(t, T0 + timedelta(seconds=150))
    assert not is_online(t, T0 + timedelta(seconds=151))
    assert not is_online(None, T0)


def test_online_now_around_the_gap(guest, admin, core):
    g = guest()
    user_id = user_id_of(core, g)

    def admin_user() -> dict:
        r = admin.get(f"/api/admin/users/{user_id}")
        assert r.status_code == 200, r.text
        return r.json()["user"]

    assert admin_user()["online_now"] is False
    now = datetime.now(UTC)
    core.services.presence.now = lambda: now - timedelta(seconds=ONLINE_GAP_SECONDS - 10)
    here(g)
    assert admin_user()["online_now"] is True
    with core.db.tx() as c:
        c.execute(
            "UPDATE users SET online_at=? WHERE id=?",
            (iso(now - timedelta(seconds=ONLINE_GAP_SECONDS + 10)), user_id),
        )
    assert admin_user()["online_now"] is False
    del core.services.presence.now  # the real clock again
    here(g)
    assert admin_user()["online_now"] is True
    here(g, visible=False)
    assert admin_user()["online_now"] is False


def test_active_now_counts_a_guest_who_only_beats(admin, guest, core):
    g = guest()
    _age_everyone(core)
    assert overview(admin)["guests"]["active_now"] == 0
    here(g)
    assert overview(admin)["guests"]["active_now"] == 1


def test_one_write_per_beat(guest, core, at):
    clock = [1000.0]
    core.services.presence.clock = lambda: clock[0]
    g = guest()
    statements: list[str] = []
    core.db._conn.set_trace_callback(statements.append)
    try:
        for _ in range(3):
            # a minute apart: the throttled refresh of other requests would be due
            clock[0] += THROTTLE_SECONDS + 1
            at[0] += timedelta(seconds=60)
            statements.clear()
            here(g)
            writes = [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
            assert len(writes) == 1, statements
        # right after a beat, other requests do not write last seen again
        statements.clear()
        clock[0] += 1
        assert g.get("/api/extensions").status_code == 200
        assert not [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
    finally:
        core.db._conn.set_trace_callback(None)
    assert online(core, g)[:2] == (120, 1)


def test_join_texts_say_what_the_hosts_see(client):
    scan(client)
    consent = identify(client)["consent"]
    assert SENTENCE in consent["paragraphs"]
    # between the device paragraph and the last one (under „Mehr dazu“)
    assert consent["paragraphs"].index(SENTENCE) == len(consent["paragraphs"]) - 2
