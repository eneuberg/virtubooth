"""`/healthz` for Docker's health check (filtered out of the access log), and
the public-address check's probe (`?probe=<nonce>`, see services/host_settings.py)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ...services.host_settings import PROBE_PATTERN, probe_mac
from ..deps import CoreDep
from ..schemas.guest import HealthOut

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(
    core: CoreDep,
    probe: Annotated[str | None, Query(max_length=64, pattern=PROBE_PATTERN)] = None,
) -> HealthOut:
    """`probe`: a nonce; the answer's `probe_mac` proves this server answered."""
    return HealthOut(ok=True, probe_mac=probe_mac(core.signer, probe) if probe else None)


@router.head("/healthz", include_in_schema=False)
def healthz_head() -> HealthOut:
    return HealthOut(ok=True)
