"""Which photos the wall shows, and how (PLAN-WALL D5).

Visible = not hidden (a ban hides the guest's photos), not deleted, from one
of the configured sources (none configured = every upload extension) and
older than the delay (`created_at <= now - delay_s`).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from ...core.clock import iso
from ...domain.codes import entry_path
from ...domain.models import Photo
from ...repositories._rows import PHOTO_COLS, photo_from_row
from .config import WallConfig, prune_sources
from .enrichment import PUBLIC_FACTS, Enrichment, PhotoFilter
from .schemas import AnalysisState, WallPhoto, WallPhotoUrls, WallQr

if TYPE_CHECKING:
    from ...runtime import Core

WALL_PATH: Final = "/livewall"
MAX_FEED = 1000
_STATES = frozenset({"pending", "running", "done", "failed", "skipped"})

Visibility = Literal["visible", "later", "gone"]


def upload_ids(core: Core) -> list[str]:
    """The extensions that take photos (the possible sources)."""
    return [e.id for e in core.extensions.values() if e.upload is not None]


def sources(core: Core, config: WallConfig) -> tuple[str, ...]:
    """The configured sources that are loaded; all upload extensions when none
    is configured (or every configured one is gone)."""
    loaded = upload_ids(core)
    kept = tuple(s for s in config.sources if s in loaded)
    return kept or tuple(loaded)


def screen_config(core: Core, config: WallConfig) -> WallConfig:
    """The config as screens and the admin see it: stale sources left out."""
    return prune_sources(config, upload_ids(core))


def cutoff(config: WallConfig, now: datetime | None = None) -> str:
    """Photos created at or before this moment are past the delay."""
    return iso((now or datetime.now(UTC)) - timedelta(seconds=config.delay_s))


def photo_filter(core: Core, config: WallConfig) -> PhotoFilter:
    return PhotoFilter(sources=sources(core, config), not_after=cutoff(config))


def _where(src: Sequence[str], not_after: str | None) -> tuple[str, list[Any]]:
    clauses = ["p.hidden_at IS NULL", "p.deleted_at IS NULL"]
    params: list[Any] = []
    if src:
        clauses.append(f"p.extension IN ({','.join('?' * len(src))})")
        params.extend(src)
    else:
        clauses.append("0")
    if not_after is not None:
        clauses.append("p.created_at <= ?")
        params.append(not_after)
    return " AND ".join(clauses), params


def visible_photos(core: Core, config: WallConfig, limit: int) -> tuple[int, list[Photo]]:
    """(total, newest `limit` photos) visible on the wall."""
    where, params = _where(sources(core, config), cutoff(config))
    db = core.db
    total_row = db.one(f"SELECT COUNT(*) FROM photos p WHERE {where}", params)
    rows = db.all(
        f"SELECT {PHOTO_COLS} FROM photos p JOIN users u ON u.id=p.user_id "
        f"WHERE {where} ORDER BY p.id DESC LIMIT ?",
        [*params, max(1, min(limit, MAX_FEED))],
    )
    return (int(total_row[0]) if total_row else 0), [photo_from_row(r) for r in rows]


def visible_by_ids(core: Core, config: WallConfig, ids: Sequence[int]) -> dict[int, Photo]:
    """The photos among `ids` (internal) that are visible on the wall."""
    if not ids:
        return {}
    where, params = _where(sources(core, config), cutoff(config))
    rows = core.db.all(
        f"SELECT {PHOTO_COLS} FROM photos p JOIN users u ON u.id=p.user_id "
        f"WHERE {where} AND p.id IN ({','.join('?' * len(ids))})",
        [*params, *ids],
    )
    return {int(r["id"]): photo_from_row(r) for r in rows}


def visible_of_user(core: Core, config: WallConfig, user_id: int) -> list[Photo]:
    """A guest's photos visible on the wall, newest first (at most MAX_FEED)."""
    where, params = _where(sources(core, config), cutoff(config))
    rows = core.db.all(
        f"SELECT {PHOTO_COLS} FROM photos p JOIN users u ON u.id=p.user_id "
        f"WHERE {where} AND p.user_id=? ORDER BY p.id DESC LIMIT ?",
        [*params, user_id, MAX_FEED],
    )
    return [photo_from_row(r) for r in rows]


def visibility(core: Core, config: WallConfig, public_id: str) -> tuple[Visibility, Photo | None]:
    """`visible`; `later` = only the delay holds it back; `gone` = not on the wall."""
    where, params = _where(sources(core, config), None)
    row = core.db.one(
        f"SELECT {PHOTO_COLS} FROM photos p JOIN users u ON u.id=p.user_id "
        f"WHERE {where} AND p.public_id=?",
        [*params, public_id],
    )
    if row is None:
        return "gone", None
    photo = photo_from_row(row)
    if photo.created_at > cutoff(config):
        return "later", photo
    return "visible", photo


def visible_photo(core: Core, config: WallConfig, public_id: str) -> Photo | None:
    state, photo = visibility(core, config, public_id)
    return photo if state == "visible" else None


def author_key(core: Core, user_id: int) -> str:
    return core.signer.mac("wall-author", str(user_id))[:12]


def media_url(public_id: str, size: str) -> str:
    return f"{WALL_PATH}/media/{public_id}?s={size}"


def wall_photos(
    core: Core, config: WallConfig, enrichment: Enrichment, photos: Sequence[Photo]
) -> list[WallPhoto]:
    summaries = enrichment.summaries([p.id for p in photos]) if photos else {}
    opted_out = _opted_out(core, {p.user_id for p in photos})
    # a photo the analysis has not picked up yet is waiting for it
    unknown: AnalysisState = "pending"
    out: list[WallPhoto] = []
    for p in photos:
        summary = summaries.get(p.id)
        state = unknown
        facts: dict[str, float] = {}
        if p.user_id in opted_out:
            # the guest switched the analysis off: no faces, hands, smiles come
            state = "off"
        elif summary is not None:
            if summary.state in _STATES:
                state = cast(AnalysisState, summary.state)
            facts = {k: float(v) for k, v in summary.facts.items() if k in PUBLIC_FACTS}
        out.append(
            WallPhoto(
                id=p.public_id,
                source=p.extension,
                seq=p.seq,
                taken_at=p.created_at,
                width=p.width,
                height=p.height,
                author=p.user_name,
                instagram=p.user_instagram if config.show_instagram else None,
                author_key=author_key(core, p.user_id),
                urls=WallPhotoUrls(
                    s=media_url(p.public_id, "s"),
                    m=media_url(p.public_id, "m"),
                    l=media_url(p.public_id, "l"),
                ),
                facts=facts,
                analysis=state,
            )
        )
    return out


def _opted_out(core: Core, user_ids: set[int]) -> set[int]:
    """The guests among `user_ids` who switched the photo analysis off."""
    ids = sorted(user_ids)
    out: set[int] = set()
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        out.update(
            int(r[0])
            for r in core.db.all(
                "SELECT id FROM users WHERE analysis_opt_out = 1 "
                f"AND id IN ({','.join('?' * len(chunk))})",
                chunk,
            )
        )
    return out


def event_name(core: Core) -> str:
    """The host's event name (Verwaltung → Einstellungen), else VB_PARTY_NAME."""
    return core.services.host_settings.event_name()


def wall_qr(core: Core, config: WallConfig, origin: str | None = None) -> WallQr | None:
    """The corner QR code: the chosen code (null = the lowest active one) while
    it is active; None when the overlay is off or the code was revoked. The URL
    is absolute with VB_PUBLIC_BASE_URL or `origin`, else a path."""
    if not config.overlay.qr:
        return None
    active = [c for c in core.repos.codes.list() if c.active]
    wanted = config.overlay.qr_code_id
    if wanted is None:
        code = min(active, key=lambda c: c.id) if active else None
    else:
        code = next((c for c in active if c.id == wanted), None)
    if code is None:
        return None
    base = (core.services.host_settings.public_base_url() or origin or "").rstrip("/")
    return WallQr(url=base + entry_path(code.target, code.token), name=code.name)


def config_payload(core: Core, config: WallConfig) -> dict[str, Any]:
    """The `config` event's data (WallConfigData)."""
    qr = wall_qr(core, config)
    return {
        "config": screen_config(core, config).model_dump(mode="json"),
        "event_name": event_name(core),
        "qr": qr.model_dump(mode="json") if qr else None,
    }
