"""Erscheinungsbild: the theme of the guest UI and the Live Wall
(`/api/admin/theme`). The admin UI itself keeps its look."""

from __future__ import annotations

from fastapi import APIRouter

from ...deps import AdminDep, CoreDep
from ...schemas.theme import AdminThemeOut, ThemeIn

router = APIRouter()


@router.get("/theme")
def get_theme(core: CoreDep) -> AdminThemeOut:
    """The theme in use and the presets."""
    return core.services.theme.admin_out()


@router.put("/theme")
def put_theme(body: ThemeIn, core: CoreDep, admin: AdminDep) -> AdminThemeOut:
    """Save a preset (without `colors`) or own colours. 400 `invalid_theme`
    names the field, or the pair of text and background that is not readable
    (4.5:1). Guests get it on their next page view, open walls at once."""
    return core.services.theme.save(body, actor=admin.actor)


@router.delete("/theme")
def reset_theme(core: CoreDep, admin: AdminDep) -> AdminThemeOut:
    """Back to the default preset („Neon Nacht“)."""
    return core.services.theme.reset(actor=admin.actor)
