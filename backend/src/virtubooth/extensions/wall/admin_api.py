"""The wall's admin routes (PLAN-WALL §4.3), mounted with the extension router
at `/api/x/wall/admin/...`. Admin session required; every change is audited in
the same transaction and reaches the open walls through the wall bus.
"""

# no `from __future__ import annotations`: FastAPI must resolve the routes'
# annotations, and some name dependencies local to build_router()

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from ...api.deps import AdminDep, CoreDep, require_admin
from ...core import errors
from ...core.clock import now_iso
from ...core.errors import error_responses
from ...core.passwords import hash_password
from ...runtime import Core
from . import auth
from .config import WallConfig, changed_keys, load_config, parse_settings, store_config
from .feed import (
    WALL_PATH,
    config_payload,
    event_name,
    photo_filter,
    screen_config,
    upload_ids,
    visible_by_ids,
)
from .hub import Wall, WallHub
from .schemas import (
    WallAdminCategoriesOut,
    WallAdminCategory,
    WallAdminOut,
    WallAdminWinner,
    WallCategoryInfo,
    WallOk,
    WallPasswordIn,
    WallPasswordState,
    WallSource,
)

_CONFIG_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/WallConfig"}}},
    }
}


async def json_body(request: Request) -> Any:
    """The raw JSON body: validated by hand, so a bad field is a 400 naming it."""
    try:
        return await request.json()
    except ValueError:
        raise errors.invalid_request() from None


def category_infos(core: Core, hub: WallHub, config: WallConfig) -> list[WallCategoryInfo]:
    enabled = hub.enrichment.active_analyzers()
    disabled = set(config.categories.disabled)
    out: list[WallCategoryInfo] = []
    for cat in hub.enrichment.catalogue():
        reason = cat.available(enabled)
        out.append(
            WallCategoryInfo(
                id=cat.id,
                emoji=cat.emoji,
                title=cat.title,
                line=cat.line,
                enabled=cat.id not in disabled,
                available=reason is None,
                reason=reason,
            )
        )
    return out


def admin_out(core: Core, hub: WallHub, config: WallConfig) -> WallAdminOut:
    state = auth.password_state(core.repos.app_settings)
    return WallAdminOut(
        config=screen_config(core, config),
        defaults=WallConfig(),
        password=WallPasswordState(set=state.is_set, changed_at=state.changed_at),
        wall_path=WALL_PATH,
        sources=[
            WallSource(id=e.id, title=e.title, emoji=e.emoji)
            for e in core.extensions.values()
            if e.upload is not None
        ],
        categories=category_infos(core, hub, config),
        open_walls=hub.bus.subscriber_count,
        event_name=event_name(core),
    )


def _new_generation(
    core: Core,
    hub: WallHub,
    *,
    actor: str,
    hash_: str | None,
    keep_hash: bool,
    action: str,
    details: dict[str, Any] | None,
    reason: str,
) -> auth.PasswordState:
    """Store a new password generation (every wall logged out), audit it and say
    `bye` to the open walls once committed."""
    now = now_iso()
    repo = core.repos.app_settings
    with core.db.tx():
        old = auth.password_state(repo)
        state = auth.PasswordState(
            hash=old.hash if keep_hash else hash_,
            gen=old.gen + 1,
            changed_at=old.changed_at if keep_hash else (now if hash_ else None),
            by=actor,
        )
        auth.store_password_state(repo, state, at=now)
        core.repos.audit.log(actor, action, "", details, at=now)
        bus = hub.bus
        core.db.on_commit(lambda: bus.publish("bye", {"reason": reason}))
    return state


def build_router(wall: Wall) -> APIRouter:
    router = APIRouter(
        prefix="/admin",
        dependencies=[Depends(require_admin)],
        responses=error_responses(400, 401, 403, 404, 422, 429),
    )

    def get_hub(core: CoreDep) -> WallHub:
        return wall.hub(core)

    HubDep = Annotated[WallHub, Depends(get_hub)]

    @router.get("/config")
    def get_config(core: CoreDep, hub: HubDep) -> WallAdminOut:
        """The wall's settings, password state, sources, categories, open walls."""
        return admin_out(core, hub, load_config(core.repos.app_settings))

    @router.put("/config", openapi_extra=_CONFIG_BODY)
    def put_config(
        core: CoreDep, hub: HubDep, admin: AdminDep, body: Annotated[Any, Depends(json_body)]
    ) -> WallAdminOut:
        """Save the settings (body: WallConfig; `rev`, `updated_at`, `by` are
        ignored). Open walls get a `config` event."""
        repo = core.repos.app_settings
        settings = parse_settings(body, upload_ids(core), load_config(repo).sources)
        now = now_iso()
        with core.db.tx():
            old = load_config(repo)
            new = WallConfig.model_validate(
                settings.model_dump(mode="json")
                | {"rev": old.rev + 1, "updated_at": now, "by": admin.actor}
            )
            store_config(repo, new, at=now)
            core.repos.audit.log(
                admin.actor, "wall.config", "", {"changed": changed_keys(old, new)}, at=now
            )
            payload = config_payload(core, new)

            def announce() -> None:
                hub.bus.publish("config", payload)
                hub.config_changed(new)

            core.db.on_commit(announce)
        return admin_out(core, hub, new)

    @router.put("/password")
    def set_password(
        body: WallPasswordIn, core: CoreDep, hub: HubDep, admin: AdminDep
    ) -> WallPasswordState:
        """Set or change the wall password: every wall is logged out."""
        if len(body.password) < auth.MIN_PASSWORD:
            raise auth.password_too_short()
        state = _new_generation(
            core,
            hub,
            actor=admin.actor,
            hash_=hash_password(body.password),
            keep_hash=False,
            action="wall.password",
            details={"mode": "set"},
            reason="password",
        )
        return WallPasswordState(set=True, changed_at=state.changed_at)

    @router.delete("/password")
    def clear_password(core: CoreDep, hub: HubDep, admin: AdminDep) -> WallPasswordState:
        """Remove the wall password: every wall is logged out, none can log in."""
        _new_generation(
            core,
            hub,
            actor=admin.actor,
            hash_=None,
            keep_hash=False,
            action="wall.password",
            details={"mode": "clear"},
            reason="password",
        )
        return WallPasswordState(set=False, changed_at=None)

    @router.post("/logout")
    def logout_walls(core: CoreDep, hub: HubDep, admin: AdminDep) -> WallOk:
        """Log every wall out (the password stays)."""
        _new_generation(
            core,
            hub,
            actor=admin.actor,
            hash_=None,
            keep_hash=True,
            action="wall.logout",
            details=None,
            reason="logout",
        )
        return WallOk(ok=True)

    @router.get("/categories")
    def categories(core: CoreDep, hub: HubDep) -> WallAdminCategoriesOut:
        """Every category (disabled ones too) with what would win right now."""
        config = load_config(core.repos.app_settings)
        infos = category_infos(core, hub, config)
        if not infos:
            return WallAdminCategoriesOut(categories=[])
        results = {
            r.category.id: r
            for r in hub.enrichment.winners([i.id for i in infos], photo_filter(core, config))
        }
        ids = list(dict.fromkeys(pid for r in results.values() for pid, _ in r.winners))
        photos = visible_by_ids(core, config, ids)
        out: list[WallAdminCategory] = []
        for info in infos:
            result = results.get(info.id)
            winners = []
            if result is not None:
                winners = [
                    WallAdminWinner(
                        photo_id=photos[pid].public_id,
                        thumb_url=photos[pid].thumb_url,
                        value=float(value),
                        label=result.category.label(value),
                    )
                    for pid, value in result.winners
                    if pid in photos
                ][:3]
            out.append(WallAdminCategory(**info.model_dump(), winners=winners))
        return WallAdminCategoriesOut(categories=out)

    return router
