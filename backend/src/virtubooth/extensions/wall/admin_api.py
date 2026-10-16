"""The wall's admin routes (PLAN-WALL §4.3, PLAN-NIGHT §4.3), mounted with the
extension router at `/api/x/wall/admin/...`. Admin session required; every
change is audited in the same transaction and reaches the open walls through
the wall bus. Categories are rule specs in `wall_categories` (enrich/engine.py):
list, create, change, delete, reorder, restore the presets, preview.
"""

# no `from __future__ import annotations`: FastAPI must resolve the routes'
# annotations, and some name dependencies local to build_router()

import re
from collections.abc import Collection, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

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
from .enrich import engine, jobs, lifecycle, objects, presets, spec_v1, values
from .enrich.engine import Comment, InvalidCategory, PhotoFilter, Winner
from .enrich.schemas import (
    AnalysisSummariesOut,
    CategoriesOut,
    CategoryCommentOut,
    CategoryItem,
    CategoryLockOut,
    CategoryOrderIn,
    CategoryPreviewOut,
    CategorySpec,
    CategorySpecV1,
    CategoryVerdictOut,
    CategoryWin,
    CategoryWinnerOut,
    ObjectBox,
    OkOut,
    OptOutState,
    PhotoAnalysisSummary,
    RestoreOut,
    SummaryBox,
    SummaryObject,
    WinnerObject,
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
# a v2 spec, or a v1 spec (deprecated: converted)
_SPEC_REF = {
    "oneOf": [
        {"$ref": "#/components/schemas/CategorySpec"},
        {"$ref": "#/components/schemas/CategorySpecV1"},
    ]
}


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
    ("Bedingung", "pool"),
    ("Rang: danach", "rank.then"),
    ("Rang: Schwelle", "rank.threshold"),
    ("Rang", "rank.by"),
    ("Anzahl", "count"),
    ("Ein Foto pro Gast", "one_per_guest"),
    ("Beschriftung: Wert", "caption.value"),
    ("Beschriftung: Einzahl", "one"),
    ("Beschriftung: Mehrzahl", "many"),
    ("Beschriftung: Objekt", "caption.show_object"),
    ("Beschriftung", "caption"),
    ("KI-Urteil", "verdict"),
)
# v1 field names (a v1 spec is validated as v1 first): the v1 editor's form keys
_FORM_FIELDS_V1 = (
    ("Bedingung", "where"),
    ("Auswahl: danach", "then_by"),
    ("Auswahl", "by"),
    ("Beschriftung: Wert", "label.value"),
    ("Urteil", "verdict"),
)


def invalid_category(field: str, version: int = 2) -> errors.ApiError:
    """400 naming the field in German, plus its form key in `field` (the v1
    editor's keys for a v1 spec)."""
    fields = (*_FORM_FIELDS_V1, *_FORM_FIELDS) if version == 1 else _FORM_FIELDS
    key = next((k for prefix, k in fields if field.startswith(prefix)), None)
    return errors.ApiError(400, "invalid_category", f"Ungültige Kategorie: {field}.", field=key)


def parse_spec(raw: Any) -> dict[str, Any]:
    try:
        return engine.validate(raw)
    except InvalidCategory as exc:
        raise invalid_category(exc.field, exc.version) from None


def ai_ready(core: Core) -> bool:
    from .llm.service import LlmService

    return LlmService.of(core).ai_ready()


def lock_out(lock: lifecycle.Lock | None) -> CategoryLockOut | None:
    if lock is None:
        return None
    return CategoryLockOut(reason=lock.reason, property=lock.detail, message=lock.text)


def category_locked(lock: lifecycle.Lock) -> errors.ApiError:
    return errors.ApiError(
        409, "category_locked", f"Diese Kategorie lässt sich gerade nicht einschalten: {lock.text}"
    )


def after_change(core: Core) -> None:
    """After a category change: switch off what is locked, and the poll looks
    again (a newly read property is polled from its next run)."""
    from .llm.service import LlmService

    svc = LlmService.of(core)
    lifecycle.reconcile(core.db, svc.ai_ready())
    svc.changed()


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


def _winner_object(w: Winner) -> WinnerObject | None:
    o = w.object
    if o is None:
        return None
    return WinnerObject(idx=o.idx, label=o.label, label_de=o.label_de, value=o.value,
                        box=_object_box(o.box))  # fmt: skip


def winners_out(
    core: Core, config: WallConfig, winners: list[Winner], photos: dict[int, Any] | None = None,
    comments: Mapping[int, Comment] | None = None,
) -> list[CategoryWinnerOut]:  # fmt: skip
    photos = photos if photos is not None else visible_by_ids(
        core, config, [w.photo_id for w in winners]
    )  # fmt: skip
    comments = comments or {}
    out: list[CategoryWinnerOut] = []
    for w in winners:
        if w.photo_id not in photos:
            continue
        c = comments.get(w.photo_id)
        out.append(CategoryWinnerOut(
            photo_id=photos[w.photo_id].public_id, thumb_url=photos[w.photo_id].thumb_url,
            value=w.value, label=w.label, headline=w.headline, detail=w.detail,
            object_idx=w.object_idx, object=_winner_object(w),
            comment=CategoryCommentOut(text=c.text, emoji=c.emoji) if c else None,
        ))  # fmt: skip
    return out


def category_items(core: Core, hub: WallHub, config: WallConfig,
                   ids: Collection[str] | None = None) -> list[CategoryItem]:  # fmt: skip
    entries = board(core, hub.enrichment.active_analyzers(), photo_filter(core, config),
                    enabled_only=False, ids=ids)  # fmt: skip
    wanted = [w.photo_id for e in entries for w in e.winners]
    photos = visible_by_ids(core, config, list(dict.fromkeys(wanted)))
    ready = ai_ready(core)
    props = lifecycle.property_states(core.db)
    return [_item(core, config, e, photos, ready, props) for e in entries]


def _legacy(spec: dict[str, Any]) -> CategorySpecV1 | None:
    old = spec_v1.downgrade(spec)
    return CategorySpecV1.model_validate(old) if old is not None else None


def _item(core: Core, config: WallConfig, e: BoardEntry, photos: dict[int, Any], ready: bool,
          props: Mapping[str, bool]) -> CategoryItem:  # fmt: skip
    cat = e.category
    names = lifecycle.references(cat.spec)
    winners = winners_out(core, config, e.winners, photos, e.comments)
    first = next((w for w in winners if w.comment is not None), None)
    verdict = (
        CategoryVerdictOut(text=first.comment.text, emoji=first.comment.emoji,
                           photo_id=first.photo_id)
        if first is not None and first.comment is not None else None
    )  # fmt: skip
    return CategoryItem(
        id=cat.id, enabled=cat.enabled, preset=cat.preset, position=cat.position,
        spec=CategorySpec.model_validate(cat.spec), legacy_spec=_legacy(cat.spec),
        explanation=engine.explain(cat.spec), needs_ai=bool(names), properties=names,
        locked=lock_out(lifecycle.lock_of(cat.spec, props, ready)),
        off_reason=cat.off_reason, off_detail=cat.off_detail,  # type: ignore[arg-type]
        off_at=cat.off_at, available=e.reason is None, reason=e.reason,
        verdict_paused=bool(cat.spec.get("verdict")) and not ready,
        verdict=verdict, winners=winners,
    )  # fmt: skip


# the key values the Live screen shows as chips (the rest is in the full analysis)
SUMMARY_FACTS = frozenset({
    "people", "faces", "smiles", "happy_max", "hands", "thumbs_up", "peace", "rock",
    "glasses", "hats", "age_groups",
})  # fmt: skip
MAX_SUMMARIES = 100
# the frames a tile draws besides its objects' (persons are objects now)
TILE_FRAMES = frozenset({"face", "hand"})


def _r3(v: float) -> float:
    return round(float(v), 3)


def _object_box(box: tuple[float, float, float, float] | None) -> ObjectBox | None:
    if box is None:
        return None
    x, y, w, h = box
    return ObjectBox(x=_r3(x), y=_r3(y), w=_r3(w), h=_r3(h))


def _summary_box(raw: dict[str, Any]) -> SummaryBox | None:
    try:
        return SummaryBox(kind=raw["kind"], x=_r3(raw["x"]), y=_r3(raw["y"]),
                          w=_r3(raw["w"]), h=_r3(raw["h"]))  # fmt: skip
    except (KeyError, TypeError, ValueError):
        return None


def analysis_summaries(core: Core, hub: WallHub, public_ids: list[str]) -> AnalysisSummariesOut:
    """State, key facts, objects (label, score, frame), face and hand frames,
    opt-outs and category wins of up to MAX_SUMMARIES photos (the Live screen asks
    for its tiles in batches). Coordinates are rounded to 3 places: the frames
    only lie on thumbnails, and a batch stays small."""
    ids = list(dict.fromkeys(public_ids))[:MAX_SUMMARIES]
    if not ids:
        return AnalysisSummariesOut(items=[])
    db = core.db
    marks = ", ".join("?" for _ in ids)
    rows = db.all(
        f"SELECT p.id, p.public_id, u.analysis_opt_out, u.ai_opt_out FROM photos p "
        f"JOIN users u ON u.id = p.user_id WHERE p.public_id IN ({marks}) "
        "AND p.deleted_at IS NULL",
        ids,
    )
    by_public = {r["public_id"]: r for r in rows}
    internal = [int(r["id"]) for r in rows]
    states = hub.enrichment.summaries(internal)
    found = objects.objects_of(db, internal)
    frames = jobs.frames_of(db, internal, TILE_FRAMES)
    wins: dict[int, list[CategoryWin]] = {}
    wanted = set(internal)
    config = load_config(core.repos.app_settings)
    entries = board(core, hub.enrichment.active_analyzers(), photo_filter(core, config),
                    enabled_only=True)  # fmt: skip
    for e in entries:
        spec = e.category.spec
        for w in e.winners:
            if w.photo_id in wanted:
                wins.setdefault(w.photo_id, []).append(CategoryWin(
                    id=e.category.id, emoji=spec["emoji"], title=spec["title"],
                    verdict=w.photo_id in e.comments))  # fmt: skip
    items: list[PhotoAnalysisSummary] = []
    for public_id in ids:
        r = by_public.get(public_id)
        if r is None:
            continue
        pid = int(r["id"])
        summary = states.get(pid)
        items.append(
            PhotoAnalysisSummary(
                photo_id=public_id,
                state=summary.state if summary else "pending",  # type: ignore[arg-type]
                facts={
                    k: v
                    for k, v in (summary.facts if summary else {}).items()
                    if k in SUMMARY_FACTS
                },
                objects=[
                    SummaryObject(
                        label=o.label,
                        label_de=o.label_de,
                        source=o.source,
                        sources=list(o.sources),
                        score=round(o.score, 2),
                        box=_object_box(o.box),
                    )
                    for o in found.get(pid, [])
                ],
                boxes=[b for raw in frames.get(pid, []) if (b := _summary_box(raw))],
                opt_out=OptOutState(
                    analysis=bool(r["analysis_opt_out"]), external_ai=bool(r["ai_opt_out"])
                ),
                wins=wins.get(pid, []),
            )
        )
    return AnalysisSummariesOut(items=items)


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

    @router.get("/photos/analysis")
    def photo_analysis_summaries(
        core: CoreDep,
        hub: HubDep,
        ids: Annotated[
            list[str],
            Query(description=f"Photo public ids (repeat the parameter), at most {MAX_SUMMARIES}."),
        ],
    ) -> AnalysisSummariesOut:
        """The Live screen's analysis chips for a batch of photos: state, key
        facts, object labels, the guest's opt-outs and current category wins."""
        if len(ids) > MAX_SUMMARIES:
            raise errors.bad_request(
                f"Höchstens {MAX_SUMMARIES} Fotos auf einmal.", "invalid_filter"
            )
        return analysis_summaries(core, hub, ids)

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
        """A new category (at the end). A category that cannot be switched on
        right now (`locked`: a property missing or in the Papierkorb, the AI not
        ready) is stored switched off with that reason. 409 `category_exists`,
        400 `invalid_category`."""
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
        lock = lifecycle.lock_of(spec, lifecycle.property_states(core.db), ai_ready(core))
        with core.db.tx():
            if engine.get(core.db, cid) is not None:
                raise errors.ApiError(409, "category_exists", "Diese Kennung gibt es schon.")
            if enabled and lock is None:
                presets.ensure_properties(core.db, spec, by=admin.actor)
            if enabled and lock is not None:
                engine.insert(core.db, cid, spec, enabled=False, preset=None, by=admin.actor,
                              off_reason=lock.reason, off_detail=lock.detail)  # fmt: skip
            else:
                engine.insert(core.db, cid, spec, enabled=enabled, preset=None, by=admin.actor)
            audit(core, admin.actor, cid, "create")
            announce_categories(hub)
        after_change(core)
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
        """„Vorlagen wiederherstellen“: add the presets that were deleted (with
        their default on/off) and the properties they need (nothing is polled
        for them until such a category is switched on)."""
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
        """What a spec would pick right now (nothing is stored), with the
        stored scores also while the AI is off („Werte vom letzten Poll“)."""
        if not isinstance(body, dict):
            raise invalid_category("Kategorie")
        spec = parse_spec(body.get("spec"))
        config = load_config(core.repos.app_settings)
        flt: PhotoFilter = photo_filter(core, config)
        result = engine.run(core, spec, flt)
        props, external = engine.availability_context(core.db)
        reason = engine.spec_availability(spec, hub.enrichment.active_analyzers(), props, external)
        lock = lifecycle.lock_of(spec, lifecycle.property_states(core.db), ai_ready(core))
        return CategoryPreviewOut(
            winners=winners_out(core, config, result.winners), matched=result.matched,
            reason=reason, explanation=engine.explain(spec),
            spec=CategorySpec.model_validate(spec), locked=lock_out(lock),
        )  # fmt: skip

    @router.put("/categories/{cid}", openapi_extra=_PUT_BODY, responses=error_responses(409))
    def put_category(
        cid: str, core: CoreDep, hub: HubDep, admin: AdminDep,
        body: Annotated[Any, Depends(json_body)],
    ) -> CategoryItem:  # fmt: skip
        """Change a category's spec and on/off switch (presets too). 409
        `category_locked` when it is to be on but cannot be (a property it reads
        is missing or in the Papierkorb, or the external AI is not ready): it can
        be saved switched off. Switching on creates the preset properties it reads
        that do not exist yet. A changed verdict prompt, model or effort drops its
        cached comments."""
        if engine.get(core.db, cid) is None:
            raise errors.not_found("Kategorie nicht gefunden.")
        if not isinstance(body, dict):
            raise invalid_category("Kategorie")
        enabled = body.get("enabled")
        if not isinstance(enabled, bool):
            raise invalid_category("Eingeschaltet")
        spec = parse_spec(body.get("spec"))
        if enabled:
            lock = lifecycle.lock_of(spec, lifecycle.property_states(core.db), ai_ready(core))
            if lock is not None:
                raise category_locked(lock)
        with core.db.tx():
            if enabled:
                presets.ensure_properties(core.db, spec, by=admin.actor)
            if not engine.update(core.db, cid, spec, enabled=enabled, by=admin.actor):
                raise errors.not_found("Kategorie nicht gefunden.")
            audit(core, admin.actor, cid, "update")
            announce_categories(hub)
        after_change(core)
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
