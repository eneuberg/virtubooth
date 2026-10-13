"""The extension interface (backend side).

An extension is a package in `virtubooth/extensions/<name>/` whose
`__init__.py` defines a module-level `extension = Extension(...)`. Core finds it
automatically and then:

- if `upload` is set: accepts JPEG uploads at `POST /api/x/<id>/upload`,
  validates and re-encodes them, stores them under `data/<id>/`, records them
  in the DB, calls `on_upload` and publishes a `photo.created` event
- if `router` is set: mounts it at `/api/x/<id>/` (protect routes yourself with
  the dependencies in `virtubooth.api.deps`)
- if `admin_router` is set: mounts it at `/api/admin/x/<id>/` behind the admin
  session check (like every admin route: CSRF origin check, admin error
  responses); routes take `admin: AdminDep` for the audit actor. That is where
  an extension keeps its admin settings, stored in the `settings` table under
  `x.<id>.<name>` (`core.repos.app_settings`); after a change it publishes
  `core.services.events.extension_settings(<id>)`, so admin screens refetch
- lists it on the home page (`show_on_home`) and in `/api/extensions`
- the guest page `/x/<id>/` is served from the built frontend (`index.html`);
  the frontend renders the extension from its own registry (frontend/src/extensions/<id>/)
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel

from ..domain.constants import EXT_ID_PATTERN, EXT_ID_RE, META_KEY_RE
from ..settings import ConfigError

if TYPE_CHECKING:
    from ..domain.models import Photo, User
    from ..runtime import Core


@dataclass(frozen=True)
class UploadPolicy:
    # None = the global VB_MAX_UPLOAD_BYTES
    max_bytes: int | None = None
    max_side: int = 2400
    min_side: int = 64
    # (width, height) every upload must have exactly, e.g. timelapse frames
    exact_size: tuple[int, int] | None = None
    quality: int = 85
    thumb_side: int = 400
    # keys allowed in the client's X-VB-Meta header; anything else is rejected
    meta_keys: frozenset[str] = frozenset()
    # optional: check/normalize meta values; raise ValueError("German message") to reject
    validate_meta: Callable[[dict[str, Any]], dict[str, Any]] | None = None


@dataclass(frozen=True)
class UploadContext:
    core: Core
    extension: Extension
    user: User
    photo: Photo


@dataclass(frozen=True)
class Extension:
    id: str
    title: str
    emoji: str
    tagline: str
    upload: UploadPolicy | None = None
    router: APIRouter | None = None
    # admin-only routes (settings), mounted at /api/admin/x/<id>/ behind require_admin
    admin_router: APIRouter | None = None
    # runs after a photo is stored; the returned dict is merged into the upload response
    on_upload: Callable[[UploadContext], dict[str, Any]] | None = None
    # the fields on_upload returns, for the API schema (UploadOut lists them)
    upload_result: type[BaseModel] | None = None
    order: int = 100
    show_on_home: bool = True
    # how the admin UI labels meta keys, e.g. {"vessel": "Gefäß"}
    meta_labels: Mapping[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        """The guest page."""
        return f"/x/{self.id}/"


def validate_extension(ext: Extension) -> None:
    if not EXT_ID_RE.match(ext.id):
        raise ConfigError(f"extension id {ext.id!r} must match {EXT_ID_PATTERN}")
    if ext.upload:
        if ext.upload.exact_size and max(ext.upload.exact_size) > ext.upload.max_side:
            raise ConfigError(f"extension {ext.id!r}: exact_size exceeds max_side")
        bad = [k for k in ext.upload.meta_keys if not META_KEY_RE.match(k)]
        if bad:
            raise ConfigError(f"extension {ext.id!r}: invalid meta keys {bad}")


def discover_extensions(enabled: Sequence[str] | None = None) -> list[Extension]:
    """Every extension package; `enabled` picks some and sets their order."""
    from .. import extensions as pkg

    found: dict[str, Extension] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if not info.ispkg or info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{pkg.__name__}.{info.name}")
        ext = getattr(module, "extension", None)
        if not isinstance(ext, Extension):
            raise ConfigError(f"virtubooth.extensions.{info.name} defines no `extension`")
        if ext.id in found:
            raise ConfigError(f"duplicate extension id {ext.id!r}")
        found[ext.id] = ext

    if enabled is not None:
        unknown = sorted(set(enabled) - found.keys())
        if unknown:
            raise ConfigError(f"VB_EXTENSIONS names unknown extensions: {unknown}")
        # an explicit list also sets the order
        return [found[i] for i in dict.fromkeys(enabled)]
    return sorted(found.values(), key=lambda e: (e.order, e.id))
