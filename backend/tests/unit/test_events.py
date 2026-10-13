"""The event bus: ids, history, replay after a reconnect, overflow, cursors."""

from __future__ import annotations

import asyncio

import pytest

from virtubooth.core.events import EventBus, Overflowed


def run(scenario):
    return asyncio.run(scenario())


async def settle() -> None:
    await asyncio.sleep(0.02)  # let call_soon_threadsafe fan out


def test_events_are_numbered_and_delivered_in_order():
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        sub = bus.subscribe()
        for i in range(3):
            bus.publish("x", {"i": i})
        await settle()
        return [await sub.get() for _ in range(3)], bus.last_id

    events, last = run(scenario)
    assert [e["id"] for e in events] == [1, 2, 3] and last == 3
    assert [e["data"]["i"] for e in events] == [0, 1, 2]


def test_overflow_drops_the_subscriber_and_get_raises():
    async def scenario():
        bus = EventBus(queue_size=2)
        bus.bind_loop(asyncio.get_running_loop())
        sub = bus.subscribe()
        for i in range(4):
            bus.publish("x", {"i": i})
        await settle()
        assert sub.overflowed and bus.subscriber_count == 0
        with pytest.raises(Overflowed):
            await sub.get()
        # the history still has everything: a reconnect catches up
        again = bus.subscribe(after=0)
        return [e["id"] for e in again.replay], again.resync

    replay, resync = run(scenario)
    assert replay == [1, 2, 3, 4] and resync is None


def test_replay_after_a_cursor_then_live():
    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        for i in range(5):
            bus.publish("x", {"i": i})
        await settle()
        sub = bus.subscribe(after=3)
        bus.publish("x", {"i": 5})
        await settle()
        return [e["id"] for e in sub.replay], (await sub.get())["id"]

    replayed, live = run(scenario)
    assert replayed == [4, 5] and live == 6


def test_cursor_older_than_the_history_asks_for_a_resync():
    async def scenario():
        bus = EventBus(history=3)
        bus.bind_loop(asyncio.get_running_loop())
        for i in range(6):
            bus.publish("x", {"i": i})
        await settle()
        gap = bus.subscribe(after=1)  # 2 and 3 are gone
        ok = bus.subscribe(after=3)  # 4.. are kept
        return gap.resync, gap.replay, ok.resync, [e["id"] for e in ok.replay]

    gap, gap_replay, ok, ok_replay = run(scenario)
    assert gap == "gap" and gap_replay == []
    assert ok is None and ok_replay == [4, 5, 6]


def test_cursor_from_another_process_or_garbage_asks_for_a_resync():
    bus = EventBus()
    assert bus.cursor() == f"{bus.epoch}-0"
    assert bus.parse_cursor(None) is None and bus.parse_cursor("  ") is None
    assert bus.parse_cursor(f"{bus.epoch}-0") == 0
    other = "0" * 8 if bus.epoch != "0" * 8 else "1" * 8
    assert bus.parse_cursor(f"{other}-0") == "restart"  # before a restart
    assert bus.parse_cursor("17") == "restart"  # an id from before the overhaul
    assert bus.parse_cursor(f"{bus.epoch}-99") == "restart"  # never published here
    sub = bus.subscribe("restart")
    assert sub.resync == "restart" and sub.replay == []


def test_events_published_before_the_cursor_are_not_delivered_twice():
    """A cursor may be newer than what has fanned out (the event was published
    from a worker thread but not delivered yet): the subscriber skips it live."""

    async def scenario():
        bus = EventBus()
        bus.bind_loop(asyncio.get_running_loop())
        bus.publish("x", {"i": 0})  # numbered 1, not fanned out yet
        sub = bus.subscribe(after=bus.last_id)
        bus.publish("x", {"i": 1})
        await settle()
        return (await sub.get())["id"], sub.qsize()

    first, left = run(scenario)
    assert first == 2 and left == 0
