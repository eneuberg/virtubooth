"""The OpenAPI schema for the frontend's typed client.

    uv run virtubooth export-openapi -o ../frontend/openapi.json

Built from an app with dummy settings and every built-in extension, so the
output depends on the code only. Deterministic: sorted keys, 2-space indent.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .app import create_app
from .extensions.sdk import discover_extensions
from .settings import Settings

_DUMMY_ENV = {
    "VB_PARTY_TOKEN": "openapi-export-token",
    "VB_ADMIN_PASSWORD": "openapi-export-password",
    "VB_SECRET_KEY": "openapi-export-secret-key-0123456789",
    "VB_DEV": "1",
}


def build_schema() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="vb-openapi-") as tmp:
        # only this mapping counts: the developer's VB_* variables don't leak in
        settings = Settings.from_env(_DUMMY_ENV | {"VB_DATA_DIR": tmp}).replace(web_dir=None)
        app = create_app(settings, extensions=discover_extensions())
        try:
            return app.openapi()
        finally:
            app.state.core.db.close()


def render_schema() -> str:
    return json.dumps(build_schema(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def export_openapi(out: str) -> None:
    text = render_schema()
    if out == "-":
        print(text, end="")
        return
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
