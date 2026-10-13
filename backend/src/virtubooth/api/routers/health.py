"""`/healthz` for Docker's health check (filtered out of the access log)."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas.guest import HealthOut

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> HealthOut:
    return HealthOut(ok=True)


@router.head("/healthz", include_in_schema=False)
def healthz_head() -> HealthOut:
    return HealthOut(ok=True)
