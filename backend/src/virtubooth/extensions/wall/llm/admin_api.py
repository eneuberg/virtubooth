"""The external-AI admin API (PLAN-NIGHT §4.4), under the wall extension's
router: `/api/x/wall/admin/llm…` and `/api/x/wall/admin/test-image`. Admin
session required; mutations pass the CSRF origin check (middleware).

The API key is write-only: no route returns it, not even in part."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool

from ....api.deps import AdminDep, CoreDep, require_admin
from ....core import errors
from ....core.clock import now_iso
from ....runtime import Core
from ..enrich import jobs
from . import budget, crypto, ports, pricing, properties, testimage
from .config import LlmConfigIn, merged, save_config
from .properties import Property
from .providers import BY_ID as PROVIDERS
from .providers import PROVIDERS as PROVIDER_LIST
from .schemas import (
    DetectionOut,
    KeyIn,
    KeyOut,
    KeyTestOut,
    LlmStatus,
    ModelOut,
    PollerOut,
    PollOut,
    PropertiesOut,
    PropertyIn,
    PropertyOut,
    ProviderOut,
    TestImageOut,
    Usage,
    UsageByKind,
    UsageTotals,
)
from .service import LlmService, Unavailable

router = APIRouter(
    tags=["wall"],
    dependencies=[Depends(require_admin)],
    responses=errors.error_responses(400, 401, 403, 404, 409, 422, 429),
)


# ----------------------------------------------------------------- helpers


def _key(status: crypto.KeyStatus) -> KeyOut:
    return KeyOut(
        set=status.set, set_at=status.set_at, provider=status.provider, valid=status.valid
    )


def _totals(t: budget.Totals) -> UsageTotals:
    return UsageTotals(
        calls=t.calls,
        input_tokens=t.input_tokens,
        output_tokens=t.output_tokens,
        cost_usd=round(t.cost_usd, 6),
    )


def usage_of(svc: LlmService) -> Usage:
    db = svc.core.db
    cfg = svc.config()
    reason = svc.blocked_reason(cfg)
    return Usage(
        party=_totals(budget.totals(db)),
        today=_totals(budget.totals(db, budget.party_day(svc.timezone))),
        by_kind=[
            UsageByKind(
                kind=k.kind,
                ref=k.ref,
                calls=k.calls,
                tokens=k.tokens,
                cost_usd=round(k.cost_micro_usd / 1_000_000, 6),
            )
            for k in budget.by_kind(db)
        ],
        budget=cfg.budget,
        blocked=reason is not None,
        reason=reason,
    )


def status_of(svc: LlmService) -> LlmStatus:
    cfg = svc.config()
    # `detect.local` is the `objects` analyzer's switch, which the Models card
    # (PUT /analysis/analyzers/objects) changes too: show the live one
    local = "objects" not in jobs.disabled_analyzers(svc.core.repos.app_settings)
    if local != cfg.detect.local:
        cfg = cfg.model_copy(update={"detect": cfg.detect.model_copy(update={"local": local})})
    db = svc.core.db
    source = PROVIDERS[cfg.provider].source
    runs = {
        r["state"]: r["n"]
        for r in db.all(
            "SELECT state, COUNT(*) AS n FROM photo_detection_runs WHERE source=? GROUP BY state",
            (source,),
        )
    }
    poller = svc.poller
    last_error = poller.last_error or svc.detector.last_error
    return LlmStatus(
        config=cfg,
        key=_key(svc.keys.status()),
        providers=[
            ProviderOut(id=p.id, title=p.title, eu=p.eu, available=True, reason=None)
            for p in PROVIDER_LIST
        ],
        models=[
            ModelOut(
                id=m.id,
                provider=m.provider,
                title=m.title,
                usd_in_mtok=m.usd_in_mtok,
                usd_out_mtok=m.usd_out_mtok,
            )
            for m in pricing.MODELS
        ],
        poller=PollerOut(
            state=poller.state(),
            last_poll_at=poller.last_poll_at or _last_poll(svc.core),
            next_poll_at=poller.next_poll_at,
            last_error=last_error,
        ),
        detection=DetectionOut(
            pending=ports.count_eligible(db, source) if cfg.detect.external else 0,
            done=runs.get("done", 0),
            failed=runs.get("failed", 0),
        ),
        usage=usage_of(svc),
    )


def _last_poll(core: Core) -> str | None:
    row = core.db.one("SELECT MAX(started_at) AS at FROM llm_polls WHERE state != 'running'")
    return row["at"] if row else None


def _property(p: Property) -> PropertyOut:
    return PropertyOut(
        id=p.id,
        name=p.name,
        prompt=p.prompt,
        created_at=p.created_at,
        archived_at=p.archived_at,
        scored_photos=p.scored_photos,
        last_scored_at=p.last_scored_at,
    )


# ------------------------------------------------------------ status, config


@router.get("/admin/llm")
def llm_status(core: CoreDep) -> LlmStatus:
    """Config, key state (never the key), providers, models with prices, the
    poller, the detection queue and the usage meter."""
    return status_of(LlmService.of(core))


@router.put("/admin/llm/config")
def set_llm_config(body: LlmConfigIn, core: CoreDep, admin: AdminDep) -> LlmStatus:
    """Change some settings (missing fields stay). 400 `invalid_llm_config`."""
    svc = LlmService.of(core)
    current = svc.config()
    try:
        new = merged(current, body)
    except ValueError as exc:
        raise errors.bad_request(str(exc), "invalid_llm_config") from None
    changed = sorted(body.model_dump(exclude_none=True))
    with core.db.tx():
        save_config(core.repos.app_settings, new, by=admin.actor)
        if new.detect.local != current.detect.local or "detect" in changed:
            ports.set_local_objects(core, new.detect.local, by=admin.actor)
        core.repos.audit.log(admin.actor, "llm.config", "", {"changed": changed}, at=now_iso())
    svc.forget_provider()
    svc.changed()
    return status_of(svc)


# ---------------------------------------------------------------------- key


@router.put("/admin/llm/key")
def set_llm_key(body: KeyIn, core: CoreDep, admin: AdminDep) -> KeyOut:
    """Store the key encrypted (write-only). 400 `llm_key_invalid` for an
    obviously malformed one (more than 400 characters, whitespace)."""
    problem = crypto.check_format(body.key)
    if problem is not None:
        raise errors.bad_request(problem, "llm_key_invalid")
    return _key(LlmService.of(core).set_key(body.provider, body.key, actor=admin.actor))


@router.delete("/admin/llm/key")
def clear_llm_key(core: CoreDep, admin: AdminDep) -> KeyOut:
    return _key(LlmService.of(core).clear_key(actor=admin.actor))


@router.post("/admin/llm/key/test")
def test_llm_key(core: CoreDep) -> KeyTestOut:
    """Ask the provider whether the key works (no tokens used).
    400 `llm_not_configured` without a key, `llm_key_invalid` when refused."""
    svc = LlmService.of(core)
    try:
        ok, message = svc.test_key()
    except Unavailable as exc:
        raise testimage.unavailable(exc.code, exc.message) from None
    return KeyTestOut(ok=ok, message=message)


# -------------------------------------------------------------------- usage


@router.get("/admin/llm/usage")
def llm_usage(core: CoreDep) -> Usage:
    return usage_of(LlmService.of(core))


# --------------------------------------------------------------- properties


@router.get("/admin/llm/properties")
def list_properties(core: CoreDep) -> PropertiesOut:
    return PropertiesOut(properties=[_property(p) for p in properties.list_all(core.db)])


@router.post("/admin/llm/properties", status_code=201)
def create_property(body: PropertyIn, core: CoreDep, admin: AdminDep) -> PropertyOut:
    """Name and prompt can never change. 409 `property_exists`, 400 `invalid_property`."""
    created = properties.create(
        core.db, core.repos.audit, body.name, body.prompt, actor=admin.actor
    )
    LlmService.of(core).changed()
    return _property(created)


@router.get("/admin/llm/properties/{name}")
def get_property(name: str, core: CoreDep) -> PropertyOut:
    """One property. There is no PUT and no DELETE (405): archive it instead."""
    found = properties.get(core.db, name)
    if found is None:
        raise errors.not_found("Eigenschaft nicht gefunden.")
    return _property(found)


def _set_archived(core: Core, name: str, archived: bool, actor: str) -> PropertyOut:
    found = properties.set_archived(core.db, core.repos.audit, name, archived, actor=actor)
    if found is None:
        raise errors.not_found("Eigenschaft nicht gefunden.")
    LlmService.of(core).changed()
    return _property(found)


@router.post("/admin/llm/properties/{name}/archive")
def archive_property(name: str, core: CoreDep, admin: AdminDep) -> PropertyOut:
    """No more polling; the last scores stay readable."""
    return _set_archived(core, name, True, admin.actor)


@router.post("/admin/llm/properties/{name}/unarchive")
def unarchive_property(name: str, core: CoreDep, admin: AdminDep) -> PropertyOut:
    return _set_archived(core, name, False, admin.actor)


# --------------------------------------------------------------------- poll


@router.post("/admin/llm/poll")
def poll_now(core: CoreDep) -> PollOut:
    """Run the poll now (also when nothing changed). `started: false` says why not."""
    started, reason = LlmService.of(core).poller.trigger()
    return PollOut(started=started, reason=reason)


# --------------------------------------------------------------- test image

_FORM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["file"],
    "properties": {
        "file": {"type": "string", "format": "binary", "description": "A JPEG."},
        "analyzers": {
            "type": "string",
            "default": "all",
            "description": '"all", a comma list of analyzer names, or "" for no local run.',
        },
        "external": {"type": "string", "enum": ["0", "1"], "default": "0"},
    },
}


@router.post(
    "/admin/test-image",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"multipart/form-data": {"schema": _FORM_SCHEMA}},
        }
    },
    responses=errors.error_responses(411, 413, 415),
)
async def test_image(request: Request, core: CoreDep) -> TestImageOut:
    """Analyse an image without storing it: the local pipeline (D1's worker)
    and, with `external=1`, the external AI (usage kind `test`, budget applies).
    409 `worker_off` / `llm_budget_exhausted`, 400 `llm_not_configured`,
    413/415 like uploads, at most 6 per minute."""
    svc = LlmService.of(core)
    if not svc.test_limiter.hit("admin"):
        raise errors.rate_limited(svc.test_limiter.retry_after("admin"))
    form = await testimage.read_form(
        request.headers.get("content-type", ""),
        request.headers.get("content-length", ""),
        request.stream(),
        core.settings.max_upload_bytes,
    )
    return await run_in_threadpool(testimage.run, svc, form)
