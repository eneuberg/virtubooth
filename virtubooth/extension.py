"""The extension interface.

An extension is a package in `virtubooth/extensions/<name>/` whose
`__init__.py` defines a module-level `extension = Extension(...)`. Core finds it
automatically and then:

- serves `static_dir` at `/x/<id>/` (party guests only; `index.html` is the page)
- if `upload` is set: accepts JPEG uploads at `POST /api/x/<id>/upload`,
  validates and re-encodes them, stores them under `data/<id>/`, records them
  in the DB, calls `on_upload` and publishes a `photo.created` event
- if `router` is set: mounts it at `/api/x/<id>/` (protect routes yourself with
  the dependencies in `virtubooth.deps`)
- lists it on the home page (`show_on_home`) and in `/api/extensions`

See docs/ARCHITECTURE.md for the full contract.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from .config import ConfigError

if TYPE_CHECKING:
    from .context import Core
    from .repo import Photo, User

EXT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
META_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


@dataclass(frozen=True)
class UploadPolicy:
    # None = the global VB_MAX_UPLOAD_BYTES
    max_bytes: int | None = None
    max_side: int = 2400
    min_side: int = 64
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
    static_dir: Path
    upload: UploadPolicy | None = None
    router: APIRouter | None = None
    # runs after a photo is stored; the returned dict is merged into the upload response
    on_upload: Callable[[UploadContext], dict[str, Any]] | None = None
    order: int = 100
    show_on_home: bool = True
    # how the admin UI labels meta keys, e.g. {"vessel": "Gefäß"}
    meta_labels: Mapping[str, str] = field(default_factory=dict)

    def public_view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "emoji": self.emoji,
            "tagline": self.tagline,
            "url": f"/x/{self.id}/",
            "uploads": self.upload is not None,
        }

    def admin_view(self) -> dict[str, Any]:
        return self.public_view() | {"meta_labels": dict(self.meta_labels)}


def validate_extension(ext: Extension) -> None:
    if not EXT_ID_RE.match(ext.id):
        raise ConfigError(f"extension id {ext.id!r} must match {EXT_ID_RE.pattern}")
    if not ext.static_dir.is_dir() or not (ext.static_dir / "index.html").is_file():
        raise ConfigError(f"extension {ext.id!r}: static_dir needs an index.html")
    if ext.upload:
        bad = [k for k in ext.upload.meta_keys if not META_KEY_RE.match(k)]
        if bad:
            raise ConfigError(f"extension {ext.id!r}: invalid meta keys {bad}")


def discover_extensions(enabled: Sequence[str] | None = None) -> list[Extension]:
    from . import extensions as pkg

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
        chosen = [found[i] for i in enabled]
    else:
        chosen = list(found.values())
    return sorted(chosen, key=lambda e: (e.order, e.id))
