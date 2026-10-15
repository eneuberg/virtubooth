"""The wall's admin routes (PLAN-WALL §4.3, PLAN-NIGHT §4.3), mounted with the
extension router at `/api/x/wall/admin/...`. Admin session required; every
change is audited in the same transaction and reaches the open walls through
the wall bus. Categories are rule specs in `wall_categories` (enrich/engine.py):
list, create, change, delete, reorder, restore the presets, preview.
"""

# no `from __future__ import annotations`: FastAPI must resolve the routes'
# annotations, and some name dependencies local to build_router()

import re
from collections.abc import Collection
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from ...api.deps import AdminDep, CoreDep, require_admin
from ...core import errors
from ...core.clock import now_iso
from ...core.errors import error_responses
from ...core.passwords import hash_password
from ...runtime import Core
from . import auth
from .config import (
    CATEGORY_ID_PATTERN,
    WallConfig,
    changed_keys,
    load_config,
    parse_settings,
    store_config,
)
from .enrich import engine, presets, values
from .enrich.engine import InvalidCategory, PhotoFilter, Winner
from .enrich.schemas import (
    CategoriesOut,
    CategoryItem,
    CategoryOrderIn,
    CategoryPreviewOut,
    CategorySpec,
    CategoryVerdictOut,
    CategoryWinnerOut,
    OkOut,
    RestoreOut,
)
from .enrich.values import ValuesOut
from .enrichment import BoardEntry, board
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
    WallAdminOut,
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


_CATEGORY_ID = re.compile(CATEGORY_ID_PATTERN)
_SPEC_REF = {"$ref": "#/components/schemas/CategorySpec"}


def _body(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    """`openapi_extra` for a hand-validated JSON body (a bad field is a 400)."""
    schema = {"type": "object", "required": required, "properties": properties}
    return {"requestBody": {"required": True, "content": {"application/json": {"schema": schema}}}}


_CREATE_BODY = _body(
    {"id": {"type": "string", "pattern": CATEGORY_ID_PATTERN}, "spec": _SPEC_REF,
     "enabled": {"type": "boolean", "default": True}},
    ["id", "spec"],
)  # fmt: skip
_PUT_BODY = _body({"spec": _SPEC_REF, "enabled": {"type": "boolean"}}, ["spec", "enabled"])
_PREVIEW_BODY = _body({"spec": _SPEC_REF}, ["spec"])


# the category editor's input for a field the engine names in German (the
# others, e.g. "Beschriftung: Stil", have no input of their own: form error)
_FORM_FIELDS = (
    ("Kennung", "id"),
    ("Emoji", "emoji"),
    ("Untertitel", "line"),
    ("Titel", "title"),
    ("Bedingung", "where"),
    ("Auswahl: danach", "then_by"),
    ("Auswahl", "by"),
    ("Anzahl", "count"),
    ("Beschriftung: Wert", "label.value"),
    ("Beschriftung: Einzahl", "one"),
    ("Beschriftung: Mehrzahl", "many"),
    ("Urteil", "verdict"),
)


def invalid_category(field: str) -> errors.ApiError:
    """400 naming the field in German, plus its form key in `field`."""
    key = next((k for prefix, k in _FORM_FIELDS if field.startswith(prefix)), None)
    return errors.ApiError(400, "invalid_category", f"Ungültige Kategorie: {field}.", field=key)


def parse_spec(raw: Any) -> dict[str, Any]:
    try:
        return engine.validate(raw)
    except InvalidCategory as exc:
        raise invalid_category(exc.field) from None


def category_infos(core: Core, hub: WallHub, config: WallConfig) -> list[WallCategoryInfo]:
    """The categories as the wall settings page lists them (no winners)."""
    db = core.db
    presets.ensure_seeded(db, core.repos.app_settings)
    active = hub.enrichment.active_analyzers()
    props, external = engine.availability_context(db)
    out: list[WallCategoryInfo] = []
    for cat in engine.stored(db):
        reason = engine.spec_availability(cat.spec, active, props, external)
        out.append(
            WallCategoryInfo(
                id=cat.id,
                emoji=cat.spec["emoji"],
                title=cat.spec["title"],
                line=cat.spec["line"],
                enabled=cat.enabled,
                available=reason is None,
                reason=reason,
            )
        )
    return out


def winners_out(
    core: Core, config: WallConfig, winners: list[Winner], photos: dict[int, Any] | None = None
) -> list[CategoryWinnerOut]:
    photos = photos if photos is not None else visible_by_ids(
        core, config, [w.photo_id for w in winners]
    )  # fmt: skip
    return [
        CategoryWinnerOut(
            photo_id=photos[w.photo_id].public_id,
            thumb_url=photos[w.photo_id].thumb_url,
            value=w.value,
            label=w.label,
            object_idx=w.object_idx,
        )
        for w in winners
        if w.photo_id in photos
    ]


def category_items(core: Core, hub: WallHub, config: WallConfig,
                   ids: Collection[str] | None = None) -> list[CategoryItem]:  # fmt: skip
    entries = board(core, hub.enrichment.active_analyzers(), photo_filter(core, config),
                    enabled_only=False, ids=ids)  # fmt: skip
    wanted = [w.photo_id for e in entries for w in e.winners]
    wanted += [e.verdict.photo_id for e in entries if e.verdict and e.verdict.photo_id]
    photos = visible_by_ids(core, config, list(dict.fromkeys(wanted)))
    return [_item(core, config, e, photos) for e in entries]


def _item(core: Core, config: WallConfig, e: BoardEntry, photos: dict[int, Any]) -> CategoryItem:
    cat = e.category
    verdict = None
    if e.verdict is not None:
        shown = photos.get(e.verdict.photo_id) if e.verdict.photo_id else None
        verdict = CategoryVerdictOut(text=e.verdict.text, emoji=e.verdict.emoji,
                                     photo_id=shown.public_id if shown else None)  # fmt: skip
    return CategoryItem(
        id=cat.id, enabled=cat.enabled, preset=cat.preset, position=cat.position,
        spec=CategorySpec.model_validate(cat.spec), available=e.reason is None, reason=e.reason,
        verdict=verdict, winners=winners_out(core, config, e.winners, photos),
    )  # fmt: skip


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
        # the old `categories.disabled` is taken over before a save drops it
        presets.ensure_seeded(core.db, repo)
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

    def announce_categories(hub: WallHub) -> None:
        """After a category change: open walls refetch their categories."""
        bus = hub.bus
        hub.core.db.on_commit(lambda: bus.publish("categories.changed", {}))

    def audit(core: Core, actor: str, cid: str | None, action: str) -> None:
        core.repos.audit.log(actor, "wall.category", cid or "", {"id": cid, "action": action},
                             at=now_iso())  # fmt: skip

    def one_item(core: Core, hub: WallHub, cid: str) -> CategoryItem:
        items = category_items(core, hub, load_config(core.repos.app_settings), ids={cid})
        if not items:
            raise errors.not_found("Kategorie nicht gefunden.")
        return items[0]

    @router.get("/values")
    def analysis_values(core: CoreDep, hub: HubDep) -> ValuesOut:
        """The values categories can use (PLAN-NIGHT §4.2) and the object
        labels seen so far."""
        return values.catalogue(core.db, hub.enrichment.active_analyzers())

    @router.get("/categories")
    def categories(core: CoreDep, hub: HubDep) -> CategoriesOut:
        """Every category (disabled ones too), position order, with its spec,
        availability, the latest verdict and what would win right now."""
        config = load_config(core.repos.app_settings)
        return CategoriesOut(categories=category_items(core, hub, config))

    @router.post("/categories", status_code=201, openapi_extra=_CREATE_BODY,
                 responses=error_responses(409))  # fmt: skip
    def create_category(
        core: CoreDep, hub: HubDep, admin: AdminDep, body: Annotated[Any, Depends(json_body)]
    ) -> CategoryItem:
        """A new category (at the end). 409 `category_exists`, 400 `invalid_category`."""
        if not isinstance(body, dict):
            raise invalid_category("Kategorie")
        cid = body.get("id")
        if not isinstance(cid, str) or not _CATEGORY_ID.match(cid) or cid in engine.RESERVED_IDS:
            raise invalid_category("Kennung")
        enabled = body.get("enabled", True)
        if not isinstance(enabled, bool):
            raise invalid_category("Eingeschaltet")
        spec = parse_spec(body.get("spec"))
        presets.ensure_seeded(core.db, core.repos.app_settings)
        with core.db.tx():
            if engine.get(core.db, cid) is not None:
                raise errors.ApiError(409, "category_exists", "Diese Kennung gibt es schon.")
            engine.insert(core.db, cid, spec, enabled=enabled, preset=None, by=admin.actor)
            audit(core, admin.actor, cid, "create")
            announce_categories(hub)
        return one_item(core, hub, cid)

    @router.put("/categories/order")
    def order_categories(
        body: CategoryOrderIn, core: CoreDep, hub: HubDep, admin: AdminDep
    ) -> CategoriesOut:
        """The wall's order: `ids` first, in this order; the others after them."""
        known = {c.id for c in engine.stored(core.db)}
        if any(i not in known for i in body.ids):
            raise invalid_category("Reihenfolge")
        with core.db.tx():
            engine.reorder(core.db, body.ids, by=admin.actor)
            audit(core, admin.actor, None, "order")
            announce_categories(hub)
        config = load_config(core.repos.app_settings)
        return CategoriesOut(categories=category_items(core, hub, config))

    @router.post("/categories/restore-presets")
    def restore_presets(core: CoreDep, hub: HubDep, admin: AdminDep) -> RestoreOut:
        """„Vorlagen wiederherstellen“: add the presets that were deleted."""
        presets.ensure_seeded(core.db, core.repos.app_settings)
        with core.db.tx():
            added = presets.restore(core.db, by=admin.actor)
            if added:
                audit(core, admin.actor, None, "restore")
                announce_categories(hub)
        return RestoreOut(added=added)

    @router.post("/categories/preview", openapi_extra=_PREVIEW_BODY)
    def preview_category(
        core: CoreDep, hub: HubDep, body: Annotated[Any, Depends(json_body)]
    ) -> CategoryPreviewOut:
        """What a spec would pick right now (nothing is stored)."""
        if not isinstance(body, dict):
            raise invalid_category("Kategorie")
        spec = parse_spec(body.get("spec"))
        config = load_config(core.repos.app_settings)
        flt: PhotoFilter = photo_filter(core, config)
        result = engine.run(core, spec, flt)
        props, external = engine.availability_context(core.db)
        reason = engine.spec_availability(spec, hub.enrichment.active_analyzers(), props, external)
        return CategoryPreviewOut(winners=winners_out(core, config, result.winners),
                                  matched=result.matched, reason=reason)  # fmt: skip

    @router.put("/categories/{cid}", openapi_extra=_PUT_BODY)
    def put_category(
        cid: str, core: CoreDep, hub: HubDep, admin: AdminDep,
        body: Annotated[Any, Depends(json_body)],
    ) -> CategoryItem:  # fmt: skip
        """Change a category's spec and on/off switch (presets too)."""
        if engine.get(core.db, cid) is None:
            raise errors.not_found("Kategorie nicht gefunden.")
        if not isinstance(body, dict):
            raise invalid_category("Kategorie")
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            raise invalid_category("Eingeschaltet")
        spec = parse_spec(body.get("spec"))
        with core.db.tx():
            if not engine.update(core.db, cid, spec, enabled=enabled, by=admin.actor):
                raise errors.not_found("Kategorie nicht gefunden.")
            audit(core, admin.actor, cid, "update")
            announce_categories(hub)
        return one_item(core, hub, cid)

    @router.delete("/categories/{cid}")
    def delete_category(cid: str, core: CoreDep, hub: HubDep, admin: AdminDep) -> OkOut:
        """Delete a category (a preset comes back with „Vorlagen wiederherstellen“)."""
        with core.db.tx():
            if not engine.delete(core.db, cid):
                raise errors.not_found("Kategorie nicht gefunden.")
            audit(core, admin.actor, cid, "delete")
            announce_categories(hub)
        return OkOut(ok=True)

    return router
