"""The wall's live side (PLAN-WALL D6): its own event bus, fed by

- a translator task subscribed to the app's bus: `photo.created` arms a timer
  for `created_at + delay_s`, then (visibility re-checked) `photo.add`;
  `photo.unhidden` / `user.unbanned` add photos past the delay (or arm a timer);
  `photo.hidden` / `photo.deleted` / `user.banned` → `photo.remove` at once;
  `user.instagram` (in-process only) → `photo.update` for the guest's photos
  while the wall shows handles; when it misses app events (fell behind,
  restart gap) → `stream.resync`, so every open wall refetches its feed;
- a poller: every POLL_SECONDS the analysis' changes → `photo.update` for
  visible photos, and `categories.changed` CATEGORIES_DEBOUNCE_SECONDS after
  the first change (more changes in between are folded in); a newly finished
  LLM poll (`MAX(llm_polls.id)` grew: new scores and verdicts) counts as a
  change too;
- the admin API: `config` after a save, `bye` when every wall is logged out;
- a media sweep (`media.sweep_cache`): at start, after missed events, hourly.

Each open wall stream is a plain subscriber of `WallHub.bus`, so a reconnect
with `Last-Event-ID` replays what it missed.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from anyio import to_thread

from ...core.events import Closed, Event, EventBus
from .auth import LoginLimits, ScreenLimits
from .config import WallConfig, load_config
from .enrich import engine, jobs, presets
from .enrich.pipeline import SourceLabels
from .enrichment import Enrichment, load_enrichment
from .feed import (
    Visibility,
    config_payload,
    visibility,
    visible_by_ids,
    visible_of_user,
    wall_photos,
)
from .media import SWEEP_SECONDS, drop_cached, sweep_cache
from .schemas import WallPhoto

if TYPE_CHECKING:
    from ...runtime import Core

log = logging.getLogger("virtubooth.wall")

POLL_SECONDS = 2.0
CATEGORIES_DEBOUNCE_SECONDS = 10.0
# a timer fires this much after the due moment, so the DB check sees it as due
_TIMER_SLACK = 0.05


def _timestamp(created_at: str) -> float:
    try:
        return datetime.fromisoformat(created_at).timestamp()
    except (TypeError, ValueError):
        return time.time()


class WallHub:
    """Everything the wall keeps per app (per `Core`)."""

    def __init__(self, core: Core, enrichment: Enrichment) -> None:
        self.core = core
        self.enrichment = enrichment
        self.bus = EventBus()
        self.login_limits = LoginLimits.create()
        self.screen_limits = ScreenLimits.create()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        # photos waiting for their delay: public id -> (created timestamp, timer)
        self._timers: dict[str, tuple[float, asyncio.TimerHandle]] = {}
        self._delay_s = 0
        self._categories_timer: asyncio.TimerHandle | None = None
        self._has_categories = False
        self.rev = 0
        self.llm_poll = 0
        # (enabled count, latest off_at) of the categories: a change by the app
        # (lifecycle switched one off) is announced like a new poll
        self._auto_off: tuple[int, str] | None = None
        self._categories_force = False

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """On the running loop (the app's lifespan)."""
        loop = asyncio.get_running_loop()
        self._loop = loop
        self.bus.bind_loop(loop)
        self._delay_s = load_config(self.core.repos.app_settings).delay_s
        try:
            # names for the analysis details, read by the worker (no imports there)
            jobs.save_source_labels(
                self.core.repos.app_settings,
                {
                    e.id: SourceLabels(title=e.title, labels=e.meta_labels, values=e.meta_values)
                    for e in self.core.extensions.values()
                    if e.upload is not None
                },
            )
        except Exception:
            log.exception("wall: storing the source names failed")
        try:
            # the preset categories, once (taking over the old disabled list)
            presets.ensure_seeded(self.core.db, self.core.repos.app_settings)
            self._has_categories = engine.has_enabled(self.core.db)
        except Exception:
            log.exception("wall: seeding the categories failed")
        self._spawn(self._translate())
        self._spawn(self._poll())
        self._spawn(self._sweep_media())
        try:
            self.enrichment.start()
        except Exception:
            log.exception("wall: the photo analysis did not start")

    def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        for _, handle in self._timers.values():
            handle.cancel()
        self._timers.clear()
        if self._categories_timer is not None:
            self._categories_timer.cancel()
            self._categories_timer = None
        try:
            self.enrichment.stop()
        except Exception:
            log.exception("wall: stopping the photo analysis failed")

    def _spawn(self, coro: Any) -> None:
        assert self._loop is not None
        task: asyncio.Task[None] = self._loop.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --------------------------------------------------------- from threads

    def publish_photo(self, type_: str, photo: WallPhoto) -> None:
        self.bus.publish(type_, {"photo": photo.model_dump(mode="json")})

    def config_changed(self, config: WallConfig) -> None:
        """After a config save (any thread): re-arm waiting photos for a new delay."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._set_delay, config.delay_s)

    # ------------------------------------------------------------ translator

    async def _translate(self) -> None:
        bus = self.core.bus
        after: int | None = None
        while True:
            sub = bus.subscribe(after)
            try:
                if sub.resync is not None:
                    log.warning("wall: missed app events (%s); walls resync", sub.resync)
                    self._missed()
                for event in sub.replay:
                    after = event["id"]
                    await self._handle(event)
                while True:
                    event = await sub.get()
                    after = event["id"]
                    await self._handle(event)
            except Closed:
                # overflowed: catch up from the bus history
                # (the next subscribe replays what it missed, or reports a resync)
                log.warning("wall: the translator fell behind; resubscribing")
            finally:
                bus.unsubscribe(sub)

    async def _handle(self, event: Event) -> None:
        type_, data = event["type"], event["data"]
        try:
            if type_ in ("photo.created", "photo.unhidden"):
                photo = data["photo"]
                self._arm(photo["id"], _timestamp(photo["created_at"]))
            elif type_ == "user.unbanned":
                for photo in data.get("photos", []):
                    if not photo.get("hidden") and not photo.get("deleted"):
                        self._arm(photo["id"], _timestamp(photo["created_at"]))
            elif type_ == "photo.hidden":
                self._remove([data["photo"]["id"]])
            elif type_ == "photo.deleted":
                self._remove([data["id"]])
                await to_thread.run_sync(drop_cached, self.core, data["id"])
            elif type_ == "user.banned":
                self._remove([p["id"] for p in data.get("photos", [])])
            elif type_ == "user.instagram":
                photos = await to_thread.run_sync(self._user_photos, int(data["id"]))
                for photo in photos:
                    self.publish_photo("photo.update", photo)
            elif type_ in ("settings.event", "code.changed", "theme.changed"):
                # the event name, the corner QR code or the theme may have changed
                payload = await to_thread.run_sync(self._config_payload)
                self.bus.publish("config", payload)
        except Exception:
            # never let one odd event stop the translator
            log.exception("wall: handling a %s event failed", type_)

    def _missed(self) -> None:
        """Events the translator never saw: every open wall refetches its feed
        (`stream.resync`, the same as a reconnect whose events are gone), and
        the media cache is swept (a `photo.deleted` may be among them)."""
        self.bus.publish("stream.resync", {})
        self._sweep_soon()

    def _user_photos(self, user_id: int) -> list[WallPhoto]:
        """A guest's visible photos as the wall shows them; none while the wall
        hides Instagram handles (nothing it shows changed)."""
        config = load_config(self.core.repos.app_settings)
        if not config.show_instagram:
            return []
        photos = visible_of_user(self.core, config, user_id)
        return wall_photos(self.core, config, self.enrichment, photos)

    def _remove(self, ids: Iterable[str]) -> None:
        ids = list(dict.fromkeys(ids))
        if not ids:
            return
        for public_id in ids:
            pending = self._timers.pop(public_id, None)
            if pending is not None:
                pending[1].cancel()
        self.bus.publish("photo.remove", {"ids": ids})
        self._categories_soon()

    def _arm(self, public_id: str, created: float) -> None:
        """photo.add once `created + delay` has passed (checked again then)."""
        assert self._loop is not None
        old = self._timers.pop(public_id, None)
        if old is not None:
            old[1].cancel()
        wait = max(0.0, created + self._delay_s - time.time()) + _TIMER_SLACK
        handle = self._loop.call_later(wait, self._due, public_id)
        self._timers[public_id] = (created, handle)

    def _set_delay(self, delay_s: int) -> None:
        if delay_s == self._delay_s:
            return
        self._delay_s = delay_s
        for public_id, (created, _) in list(self._timers.items()):
            self._arm(public_id, created)

    def _due(self, public_id: str) -> None:
        self._timers.pop(public_id, None)
        self._spawn(self._check(public_id))

    async def _check(self, public_id: str) -> None:
        try:
            state, photo, created = await to_thread.run_sync(self._check_sync, public_id)
        except Exception:
            log.exception("wall: checking photo %s failed", public_id)
            return
        if state == "visible" and photo is not None:
            self.publish_photo("photo.add", photo)
            self._categories_soon()
        elif state == "later" and public_id not in self._timers:
            # the delay grew since the timer was armed
            self._arm(public_id, created)

    def _check_sync(self, public_id: str) -> tuple[Visibility, WallPhoto | None, float]:
        config = load_config(self.core.repos.app_settings)
        state, photo = visibility(self.core, config, public_id)
        if photo is None:
            return state, None, 0.0
        created = _timestamp(photo.created_at)
        if state != "visible":
            return state, None, created
        (wall_photo,) = wall_photos(self.core, config, self.enrichment, [photo])
        return state, wall_photo, created

    def _config_payload(self) -> dict[str, Any]:
        return config_payload(self.core, load_config(self.core.repos.app_settings))

    # ---------------------------------------------------------- media cache

    async def _sweep_media(self) -> None:
        """The cached copies of deleted or hidden photos (WALL-02): at start,
        then every SWEEP_SECONDS."""
        while True:
            await self._sweep_once()
            await asyncio.sleep(SWEEP_SECONDS)

    async def _sweep_once(self) -> None:
        try:
            await to_thread.run_sync(sweep_cache, self.core)
        except Exception:
            log.exception("wall: sweeping the media cache failed")

    def _sweep_soon(self) -> None:
        """After missed events: a `photo.deleted` may be among them."""
        if self._loop is not None:
            self._spawn(self._sweep_once())

    # ---------------------------------------------------------------- poller

    async def _poll(self) -> None:
        try:
            # what was analysed before this start needs no update
            self.rev = await to_thread.run_sync(self._catch_up)
        except Exception:
            log.exception("wall: reading the analysis state failed")
        while True:
            await asyncio.sleep(POLL_SECONDS)
            try:
                changed = await to_thread.run_sync(self._poll_once)
            except Exception:
                log.exception("wall: polling the analysis failed")
                continue
            if changed:
                self._categories_soon()

    def _catch_up(self) -> int:
        self.llm_poll = engine.last_poll(self.core.db)
        rev = self.rev
        for _ in range(10_000):
            new, ids = self.enrichment.changes_since(rev)
            if not ids or new == rev:
                return new
            rev = new
        return rev

    def _announce_analyzed(self, ids: list[int]) -> None:
        """Tell the admin screens (Live) which photos have a new analysis."""
        try:
            marks = ", ".join("?" for _ in ids)
            rows = self.core.db.all(
                f"SELECT public_id FROM photos WHERE id IN ({marks}) AND deleted_at IS NULL", ids
            )
            self.core.services.events.photo_analyzed([r["public_id"] for r in rows])
        except Exception:
            log.exception("wall: announcing analysed photos failed")

    def _poll_once(self) -> bool:
        db = self.core.db
        self._has_categories = engine.has_enabled(db)
        polled = engine.last_poll(db)
        new_poll = polled > self.llm_poll
        self.llm_poll = max(self.llm_poll, polled)
        # a category switched off by the app (lifecycle: AI off, property trashed)
        switched = engine.auto_off_state(db)
        if switched != self._auto_off:
            if self._auto_off is not None:
                new_poll = True
                self._categories_force = True
            self._auto_off = switched
        new, ids = self.enrichment.changes_since(self.rev)
        self.rev = new
        if not ids:
            return new_poll
        self._announce_analyzed(ids)
        config = load_config(self.core.repos.app_settings)
        photos = visible_by_ids(self.core, config, ids)
        for photo in wall_photos(self.core, config, self.enrichment, list(photos.values())):
            self.publish_photo("photo.update", photo)
        return True

    def _categories_soon(self) -> None:
        """`categories.changed` in CATEGORIES_DEBOUNCE_SECONDS (once for a burst of
        changes: analysis results, photos coming and going). Never without categories."""
        if not self._has_categories and not self._categories_force:
            return
        if self._categories_timer is not None or self._loop is None:
            return
        self._categories_timer = self._loop.call_later(
            CATEGORIES_DEBOUNCE_SECONDS, self._categories_fire
        )

    def _categories_fire(self) -> None:
        self._categories_timer = None
        self._categories_force = False
        self.bus.publish("categories.changed", {})


class Wall:
    """The wall's hubs, one per app (`Core`). An extension object can serve
    several apps (tests, the OpenAPI export), so nothing lives on it directly."""

    def __init__(self, enrichment: Enrichment | None = None) -> None:
        self._enrichment = enrichment
        self._hubs: dict[int, WallHub] = {}
        self._lock = threading.Lock()

    def hub(self, core: Core) -> WallHub:
        with self._lock:
            hub = self._hubs.get(id(core))
            if hub is None or hub.core is not core:
                enrichment = self._enrichment or load_enrichment(core)
                hub = WallHub(core, enrichment)
                self._hubs[id(core)] = hub
            return hub

    def on_start(self, core: Core) -> None:
        self.hub(core).start()

    def on_stop(self, core: Core) -> None:
        with self._lock:
            hub = self._hubs.pop(id(core), None)
        if hub is not None:
            hub.stop()
