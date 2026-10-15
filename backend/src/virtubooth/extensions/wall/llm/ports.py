"""D1's ports (PLAN-NIGHT §4.1) as the LLM code calls them: the object list
(`enrich.objects`), the category engine (`enrich.engine`) and the test-image
round trip (`enrich.testjobs`), re-exported plus the few helpers that need
the wall's config.

Nothing here sends anything anywhere: these are database reads and writes.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING, Any

from ..enrich import jobs
from ..enrich.engine import Winner, category_specs
from ..enrich.objects import (
    DetectedObject,
    FrozenError,
    RunState,
    StoredObject,
    append,
    count_eligible_for_external,
    eligible_for_external,
    objects_of,
    record_run,
)
from ..enrich.testjobs import TestRun, WorkerOff

if TYPE_CHECKING:
    from ....runtime import Core

__all__ = [
    "DetectedObject",
    "FrozenError",
    "RunState",
    "StoredObject",
    "TestRun",
    "Winner",
    "WorkerOff",
    "analyzer_names",
    "append",
    "category_specs",
    "count_eligible",
    "eligible_for_external",
    "evaluate",
    "objects_of",
    "record_run",
    "set_local_objects",
    "submit_test",
]


def count_eligible(db: Any, source: str) -> int:
    """How many photos `eligible_for_external` would still hand out."""
    return count_eligible_for_external(db, source)


def evaluate(core: Core, spec: Mapping[str, Any], limit: int | None = None) -> list[Winner]:
    """The category's current winners as the wall shows them (its filter)."""
    from .. import config as wall_config
    from .. import feed
    from ..enrich import engine

    flt = feed.photo_filter(core, wall_config.load_config(core.repos.app_settings))
    return engine.evaluate(core, dict(spec), flt, limit)


def analyzer_names() -> set[str]:
    from ..enrich.analyzers import BY_NAME

    return set(BY_NAME)


def submit_test(
    core: Core, image: bytes, analyzers: Collection[str] | None, timeout_s: float = 30
) -> TestRun:
    """The local pipeline on a test image (never stored). Raises WorkerOff
    (no worker running) or TimeoutError (no answer in time)."""
    from ..enrich import testjobs

    return testjobs.submit(core, image, analyzers, timeout_s)


def set_local_objects(core: Core, enabled: bool, *, by: str) -> None:
    """The local detector: switch D1's `objects` analyzer in `x.wall.analyzers`
    (only the disabled set changes; the analyzers' settings stay). Off: the
    `people` value falls back to the face count."""
    repo = core.repos.app_settings
    disabled = set(jobs.disabled_analyzers(repo))
    wanted = disabled - {"objects"} if enabled else disabled | {"objects"}
    if wanted != disabled:
        jobs.save_disabled(repo, wanted, by=by)
