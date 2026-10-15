"""Whether external AI is in use at all (the join dialog shows its opt-out switch
only then), and who would get the data (the guests' privacy text names them).
Read by services/identity.py."""

from __future__ import annotations

import json

from ....repositories.container import Repositories
from .config import load_config


def external_ai_active(repos: Repositories) -> bool:
    """Switched on, and something would actually be sent: detection at upload,
    or the poll with an active property or an enabled category with an LLM verdict."""
    config = load_config(repos.app_settings)
    if not config.enabled:
        return False
    from .providers import BY_ID

    if config.detect.external and BY_ID[config.provider].vision:
        return True
    if not config.poll:
        return False
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


def external_ai_provider(repos: Repositories) -> str:
    """The configured provider for the privacy text, e.g. „Anthropic, USA“
    (also while external AI is off: the text says what switching it on means)."""
    from .providers import BY_ID

    return BY_ID[load_config(repos.app_settings).provider].privacy


def external_ai_photos(repos: Repositories) -> bool:
    """Whether the configured provider can be sent photos (object detection);
    DeutschlandGPT only ever gets text (the object lists)."""
    from .providers import BY_ID

    return BY_ID[load_config(repos.app_settings).provider].vision
