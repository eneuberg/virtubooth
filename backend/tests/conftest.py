"""Shared fixtures. Extension tests reuse these:

    def test_something(make_client, guest):
        client = guest()                     # consented guest (own cookie jar)
        r = client.post("/api/x/beer/upload", content=jpeg(), headers=JPEG)

The app serves a copy of the stub web dir (tests/fixtures/web: index.html,
admin.html, gate.html, assets/...), so page tests never need a real frontend
build. No test reads the developer's VB_* environment.
"""

from __future__ import annotations

import io
import os
import shutil
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from virtubooth.app import create_app
from virtubooth.extensions.sdk import Extension, UploadContext, UploadPolicy
from virtubooth.runtime import Core
from virtubooth.settings import Settings

PARTY_TOKEN = "test-party-token-0123456789"
ADMIN_PASSWORD = "test-admin-password-123"
SECRET_KEY = "test-secret-key-0123456789abcdef0123456789"
BASE_URL = "http://testserver"
ORIGIN = {"Origin": BASE_URL}
JPEG = {"Content-Type": "image/jpeg", "Origin": BASE_URL}

FIXTURES = Path(__file__).parent / "fixtures"
STUB_WEB = FIXTURES / "web"
# the stub build's files (see tests/fixtures/web)
STUB_JS = "a-3f9c2b71.js"
STUB_CSS = "a-7c41e0f2.css"


def jpeg(
    width: int = 1080, height: int = 1440, color: tuple[int, int, int] = (200, 120, 40)
) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "JPEG", quality=85)
    return buf.getvalue()


def png(width: int = 200, height: int = 200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (1, 2, 3)).save(buf, "PNG")
    return buf.getvalue()


def fp(n: int = 1) -> dict[str, Any]:
    return {"hash": f"{n:064x}", "components": {"ua": "pytest", "screen": "390x844@3"}}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The developer's own VB_* variables must not leak into the app or the tools."""
    for name in list(os.environ):
        if name.startswith("VB_"):
            monkeypatch.delenv(name)


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    """A writable copy of the stub frontend build."""
    target = tmp_path / "web"
    shutil.copytree(STUB_WEB, target)
    return target


def make_settings(data_dir: Path, web_dir: Path | None, **changes: Any) -> Settings:
    return Settings(
        _env_file=None,
        party_token=PARTY_TOKEN,
        admin_password=ADMIN_PASSWORD,
        secret_key=SECRET_KEY,
        data_dir=data_dir,
        web_dir=web_dir,
        **changes,
    )


@pytest.fixture
def settings(tmp_path: Path, web_dir: Path) -> Settings:
    return make_settings(
        tmp_path / "data", web_dir, party_name="Testparty", instagram_account="@testparty"
    )


@pytest.fixture
def demo_extension() -> Extension:
    def validate(meta: dict[str, Any]) -> dict[str, Any]:
        if meta.get("mood") not in (None, "happy", "sad"):
            raise ValueError("Unbekannte Laune.")
        return meta

    def on_upload(ctx: UploadContext) -> dict[str, Any]:
        return {"count": ctx.core.repos.photos.count(ctx.extension.id)}

    return Extension(
        id="demo",
        title="Demo",
        emoji="🧪",
        tagline="Nur für Tests",
        upload=UploadPolicy(meta_keys=frozenset({"mood"}), validate_meta=validate),
        on_upload=on_upload,
    )


@pytest.fixture
def extensions(demo_extension: Extension) -> Sequence[Extension]:
    """Override in an extension's test module to load real extensions."""
    return [demo_extension]


@pytest.fixture
def app(settings: Settings, extensions: Sequence[Extension]) -> Iterator[FastAPI]:
    application = create_app(settings, extensions=extensions)
    yield application
    application.state.core.db.close()


@pytest.fixture
def core(app: FastAPI) -> Core:
    core: Core = app.state.core
    return core


@pytest.fixture
def make_client(app: FastAPI) -> Iterator[Callable[[], TestClient]]:
    clients: list[TestClient] = []

    def make() -> TestClient:
        client = TestClient(app, base_url=BASE_URL, follow_redirects=False)
        client.__enter__()  # runs lifespan (binds the event bus)
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[[], TestClient]) -> TestClient:
    return make_client()


def scan(client: TestClient, path: str = "/") -> None:
    """Simulate scanning the party QR code."""
    r = client.get(f"{path}?t={PARTY_TOKEN}")
    assert r.status_code == 303, r.text


def accept_consent(
    client: TestClient, *, instagram: str | None = None, fp_n: int = 1
) -> dict[str, Any]:
    r = client.post(
        "/api/join",
        json={"accept": True, "version": "1", "instagram": instagram, "fp": fp(fp_n)},
        headers=ORIGIN,
    )
    assert r.status_code in (200, 201), r.text
    body: dict[str, Any] = r.json()
    return body


@pytest.fixture
def guest(make_client: Callable[[], TestClient]) -> Callable[..., TestClient]:
    """guest(instagram=None, fp_n=1) -> a TestClient for a fresh consented guest."""

    def make(*, instagram: str | None = None, fp_n: int = 1) -> TestClient:
        c = make_client()
        scan(c)
        accept_consent(c, instagram=instagram, fp_n=fp_n)
        return c

    return make


@pytest.fixture
def admin(make_client: Callable[[], TestClient]) -> TestClient:
    c = make_client()
    r = c.post("/api/admin/login", json={"password": ADMIN_PASSWORD}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return c
