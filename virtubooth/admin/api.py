"""Admin JSON API, mounted at /api/admin. Every route requires an admin session.

Login/logout/session live in virtubooth/admin_auth.py (core).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import require_admin

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])
