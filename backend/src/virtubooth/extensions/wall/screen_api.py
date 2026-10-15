"""The wall screen's routes, all under `/livewall` (PLAN-WALL §4.2, D3): outside
`/api/`, so the TV never shares the venue Wi-Fi's per-IP guest budget, and the
wall cookie can be scoped to this one prefix.

| Path                                | Answer                                         |
|-------------------------------------|------------------------------------------------|
| `GET /livewall`                     | wall.html (public; 404 page without it)        |
| `GET/POST/DELETE /livewall/api/session` | state / login / logout of this screen      |
| `GET /livewall/api/feed`            | config + the newest visible photos             |
| `GET /livewall/api/categories`      | the fun categories with their winners          |
| `GET /livewall/api/stream`          | Server-Sent Events (see `wall_event_stream`)   |
| `GET /livewall/media/{public_id}`   | JPEG `?s=s|m|l` of a photo visible on the wall |

Everything but the page and `session` needs the wall cookie or an admin session
(401 `wall_login_required`). JSON answers are `Cache-Control: no-store`.

The GET routes are rate limited per wall cookie, else per address (429
`rate_limited` with `Retry-After`): 120 a minute for session, feed, categories
and stream together, 1200 a minute (bursts of 600) for media.

One wall cookie (or admin session) keeps at most `EventBus.per_session` (4)
streams open; a fifth closes its oldest, whose screen reconnects and replays
what it missed (WALL-03, like the admin stream's SEC-06).
"""

# no `from __future__ import annotations`: FastAPI must resolve the routes'
# annotations, and some name dependencies local to build_router()

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from anyio import to_thread
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent

from ...api.deps import CoreDep, admin_from_cookie
from ...core import errors
from ...core.clock import now_iso
from ...core.errors import error_responses, json_error_responses
from ...core.events import Closed, Event, EventBus, Resync
from ...core.ratelimit import RateLimiter
from ...domain.constants import PHOTO_ID_RE
from ...runtime import Core
from . import auth
from .auth import NO_STORE, WallDep, wall_auth
from .config import load_config
from .enrichment import board
from .feed import (
    MAX_FEED,
    WALL_PATH,
    event_name,
    photo_filter,
    screen_config,
    visible_by_ids,
    visible_photo,
    visible_photos,
    wall_photos,
    wall_qr,
)
from .hub import Wall, WallHub
from .media import photo_file
from .schemas import (
    WallCategoriesOut,
    WallCategory,
    WallEvent,
    WallFeed,
    WallLoginIn,
    WallOk,
    WallSessionOut,
    WallVerdict,
    WallWinner,
)

# an open stream re-checks its cookie this often (logout, password change)
RECHECK_SECONDS = 30.0
RETRY_MS = 3000
_MAX_WAIT = 15.0
MEDIA_CACHE = "private, max-age=86400"


def no_store(response: Response) -> None:
    response.headers.update(NO_STORE)


NoStore = Depends(no_store)


def _sse(bus: EventBus, event: Event) -> ServerSentEvent:
    return ServerSentEvent(
        raw_data=json.dumps(event["data"]), event=event["type"], id=bus.wire_id(event)
    )


def stream_owner(request: Request, core: Core) -> str | None:
    """Whose stream this is, for the cap on open streams: the wall cookie, else
    the admin session (hashed: the bus keeps it in memory)."""
    cookie = request.cookies.get(auth.COOKIE)
    state = auth.password_state(core.repos.app_settings)
    if cookie and auth.cookie_valid(core, request, state):
        return "wall:" + hashlib.sha256(cookie.encode()).hexdigest()[:32]
    admin = admin_from_cookie(request, core)
    return f"admin:{admin.session_hash}" if admin is not None else None


async def wall_event_stream(
    request: Request,
    core: Core,
    hub: WallHub,
    cursor: int | Resync | None,
    *,
    owner: str | None = None,
) -> AsyncIterator[ServerSentEvent]:
    """`retry: 3000`, `hello`, then (after a `stream.resync` when the missed events
    are gone) every wall event. Ends when the screen is logged out (`bye`, or
    the cookie check every RECHECK_SECONDS) or falls behind (the browser
    reconnects and catches up), or when `owner` opens one stream too many."""
    bus = hub.bus
    sub = bus.subscribe(cursor, session=owner)

    async def authorized() -> bool:
        return await to_thread.run_sync(wall_auth, request, core) is not None

    try:
        if not await authorized():
            # logged out between the auth check and subscribe(): the bye was missed
            return
        yield ServerSentEvent(retry=RETRY_MS)
        config = await to_thread.run_sync(load_config, core.repos.app_settings)
        hello = {"config_rev": config.rev, "server_time": now_iso()}
        yield ServerSentEvent(raw_data=json.dumps(hello), event="hello")
        if sub.resync is not None:
            yield ServerSentEvent(raw_data="{}", event="stream.resync")
        for event in sub.replay:
            if event["type"] == "bye" and await authorized():
                continue  # an admin session still watches
            yield _sse(bus, event)
            if event["type"] == "bye":
                return
        checked = time.monotonic()
        while True:
            try:
                item: Event | None = await asyncio.wait_for(
                    sub.get(), timeout=min(max(RECHECK_SECONDS, 1.0), _MAX_WAIT)
                )
            except TimeoutError:
                item = None
            except Closed:
                return
            now = time.monotonic()
            if now - checked >= RECHECK_SECONDS:
                checked = now
                if not await authorized():
                    return
            if item is None:
                continue
            if item["type"] == "bye":
                if await authorized():
                    continue
                yield _sse(bus, item)
                return
            yield _sse(bus, item)
    finally:
        bus.unsubscribe(sub)


def limit(limiter: RateLimiter, request: Request, core: Core) -> None:
    key = auth.screen_key(core, request)
    if not limiter.hit(key):
        raise errors.rate_limited(limiter.retry_after(key))


def build_router(wall: Wall) -> APIRouter:
    router = APIRouter(tags=["wall"])

    def get_hub(core: CoreDep) -> WallHub:
        return wall.hub(core)

    HubDep = Annotated[WallHub, Depends(get_hub)]

    def screen_budget(request: Request, core: CoreDep, hub: HubDep) -> None:
        limit(hub.screen_limits.api, request, core)

    def media_budget(request: Request, core: CoreDep, hub: HubDep) -> None:
        limit(hub.screen_limits.media, request, core)

    ScreenBudget = Depends(screen_budget)
    MediaBudget = Depends(media_budget)

    @router.get(WALL_PATH, include_in_schema=False)
    def page(core: CoreDep) -> Response:
        html = core.web.extra_page("wall.html")
        return html if html is not None else core.web.not_found()

    @router.get(WALL_PATH + "/", include_in_schema=False)
    def page_slash() -> Response:
        return RedirectResponse(WALL_PATH, status_code=308)

    @router.get(
        WALL_PATH + "/api/session",
        dependencies=[NoStore, ScreenBudget],
        responses=error_responses(401, 409, 429),
    )
    def session(request: Request, core: CoreDep) -> WallSessionOut:
        """Whether this screen may watch: 401 log in, 409 no wall password yet."""
        via = wall_auth(request, core)
        if via is not None:
            return WallSessionOut(ok=True, via=via)
        if not auth.password_state(core.repos.app_settings).is_set:
            raise auth.no_password()
        raise auth.login_required()

    @router.post(
        WALL_PATH + "/api/session",
        dependencies=[NoStore],
        responses=error_responses(403, 409, 422, 429),
    )
    def login(
        body: WallLoginIn, request: Request, response: Response, core: CoreDep, hub: HubDep
    ) -> WallSessionOut:
        """Log this screen in with the wall password (sets the `vb_wall` cookie)."""
        state = auth.login(core, hub.login_limits, request, body.password)
        auth.set_wall_cookie(response, request, core, state.gen)
        return WallSessionOut(ok=True, via="password")

    @router.delete(
        WALL_PATH + "/api/session", dependencies=[NoStore], responses=error_responses(403)
    )
    def logout(request: Request, response: Response, core: CoreDep) -> WallOk:
        """Log this screen out (only this one)."""
        auth.clear_wall_cookie(response, request, core)
        return WallOk(ok=True)

    @router.get(
        WALL_PATH + "/api/feed",
        dependencies=[NoStore, ScreenBudget],
        responses=error_responses(401, 422, 429),
    )
    def feed(
        request: Request,
        core: CoreDep,
        hub: HubDep,
        _via: WallDep,
        limit: Annotated[int, Query(ge=1, le=MAX_FEED)] = 500,
    ) -> WallFeed:
        """The config and the newest visible photos. `cursor` resumes the stream
        right after this answer (`?since=`)."""
        # taken before reading: events after it are not in the answer
        cursor = hub.bus.cursor()
        config = load_config(core.repos.app_settings)
        total, photos = visible_photos(core, config, limit)
        return WallFeed(
            config=screen_config(core, config),
            event_name=event_name(core),
            qr=wall_qr(core, config, str(request.base_url)),
            total=total,
            photos=wall_photos(core, config, hub.enrichment, photos),
            cursor=cursor,
            server_time=now_iso(),
        )

    @router.get(
        WALL_PATH + "/api/categories",
        dependencies=[NoStore, ScreenBudget],
        responses=error_responses(401, 429),
    )
    def categories(core: CoreDep, hub: HubDep, _via: WallDep) -> WallCategoriesOut:
        """The enabled categories that have winners, in the admin's order (1–10 winners
        each, plus the LLM verdict when there is one)."""
        return WallCategoriesOut(categories=screen_categories(core, hub))

    @router.get(
        WALL_PATH + "/api/stream",
        response_class=EventSourceResponse,
        response_description="Server-Sent Events; each message's `data` is the event's `data`.",
        dependencies=[ScreenBudget],
        responses=json_error_responses(401, 422, 429),
    )
    async def stream(
        request: Request,
        core: CoreDep,
        hub: HubDep,
        _via: WallDep,
        last_event_id: Annotated[str | None, Header(max_length=64)] = None,
        since: Annotated[
            str | None, Query(max_length=64, description="Resume after this event id.")
        ] = None,
    ) -> AsyncIterator[WallEvent]:
        """The wall's live events (resume with `Last-Event-ID` or `?since=<feed cursor>`)."""
        cursor = hub.bus.parse_cursor(last_event_id if last_event_id else since)
        owner = await to_thread.run_sync(stream_owner, request, core)
        async for message in wall_event_stream(request, core, hub, cursor, owner=owner):
            # FastAPI writes ServerSentEvent items as they are; `WallEvent` only
            # documents the messages in the OpenAPI schema
            yield message  # type: ignore[misc]

    @router.get(
        WALL_PATH + "/media/{public_id}", include_in_schema=False, dependencies=[MediaBudget]
    )
    def media(
        public_id: str, core: CoreDep, _via: WallDep, s: Literal["s", "m", "l"] = "m"
    ) -> FileResponse:
        """A photo visible on the wall; 404 for anything else."""
        if not PHOTO_ID_RE.match(public_id):
            raise errors.not_found()
        config = load_config(core.repos.app_settings)
        photo = visible_photo(core, config, public_id)
        path = photo_file(core, photo, s) if photo is not None else None
        if path is None:
            raise errors.not_found()
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": MEDIA_CACHE})

    return router


def screen_categories(core: Core, hub: WallHub) -> list[WallCategory]:
    """The enabled categories that have winners (rule specs, PLAN-NIGHT N13),
    in the admin's order, each with its LLM verdict when there is one."""
    config = load_config(core.repos.app_settings)
    entries = board(core, hub.enrichment.active_analyzers(), photo_filter(core, config),
                    enabled_only=True)  # fmt: skip
    wanted = [w.photo_id for e in entries for w in e.winners]
    wanted += [e.verdict.photo_id for e in entries if e.verdict and e.verdict.photo_id]
    photos = visible_by_ids(core, config, list(dict.fromkeys(wanted)))
    built = wall_photos(core, config, hub.enrichment, list(photos.values()))
    by_id = dict(zip(photos, built, strict=True))
    out: list[WallCategory] = []
    for e in entries:
        winners = [
            WallWinner(
                photo=by_id[w.photo_id], value=w.value, label=w.label, object_idx=w.object_idx
            )
            for w in e.winners
            if w.photo_id in by_id
        ]
        if not winners:
            continue
        verdict = None
        if e.verdict is not None:
            shown = photos.get(e.verdict.photo_id) if e.verdict.photo_id else None
            verdict = WallVerdict(text=e.verdict.text, emoji=e.verdict.emoji,
                                  photo_id=shown.public_id if shown else None)  # fmt: skip
        spec = e.category.spec
        out.append(
            WallCategory(
                id=e.category.id,
                emoji=spec["emoji"],
                title=spec["title"],
                line=spec["line"],
                winners=winners,
                verdict=verdict,
            )
        )
    return out
