"""Whether external AI is in use at all (the join dialog shows its opt-out switch
only then). UI2 keeps a copy of `external_ai_active` in services/identity.py
until INT2 replaces it with an import of this one."""

from __future__ import annotations

import json

from ....repositories.container import Repositories
from .config import load_config


def external_ai_active(repos: Repositories) -> bool:
    """Switched on, and something would actually be sent: detection at upload,
    an active property or an enabled category with an LLM verdict."""
    config = load_config(repos.app_settings)
    if not config.enabled:
        return False
    if config.detect.external:
        return True
    if repos.db.one("SELECT 1 FROM llm_properties WHERE archived_at IS NULL LIMIT 1"):
        return True
    for row in repos.db.all("SELECT spec FROM wall_categories WHERE enabled = 1"):
        try:
            spec = json.loads(row["spec"])
        except ValueError:
            continue
        if isinstance(spec, dict) and spec.get("verdict"):
            return True
    return False
