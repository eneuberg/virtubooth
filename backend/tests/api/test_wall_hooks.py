"""The platform hooks the wall added, tested generically: `Extension.web_router`,
`on_start` / `on_stop` in the lifespan, and `WebFrontend.extra_page`."""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from virtubooth.extensions.sdk import Extension
from virtubooth.web.frontend import WebFrontend

from ..conftest import BASE_URL

calls: list[str] = []


def hooked(ext_id: str, *, fail_start: bool = False, fail_stop: bool = False) -> Extension:
    router = APIRouter()

    @router.get(f"/{ext_id}-page", include_in_schema=False)
    def page() -> PlainTextResponse:
        return PlainTextResponse(f"page of {ext_id}")

    def on_start(core) -> None:
        calls.append(f"start {ext_id}")
        # may create tasks on the running loop
        asyncio.get_running_loop().create_task(asyncio.sleep(0))
        if fail_start:
            raise RuntimeError("boom")

    def on_stop(core) -> None:
        calls.append(f"stop {ext_id}")
        if fail_stop:
            raise RuntimeError("bang")

    return Extension(
        id=ext_id,
        title=ext_id,
        emoji="🧪",
        tagline="",
        web_router=router,
        on_start=on_start,
        on_stop=on_stop,
    )


@pytest.fixture
def extensions(demo_extension):
    calls.clear()
    return [
        demo_extension,
        hooked("first", fail_start=True),
        hooked("second", fail_stop=True),
        hooked("third"),
    ]


def test_lifecycle_hooks_run_in_order_and_never_fail_the_app(app, caplog):
    with caplog.at_level(logging.ERROR, logger="virtubooth"):
        with TestClient(app, base_url=BASE_URL) as client:
            assert calls == ["start first", "start second", "start third"]
            # a failing on_start is logged; the app and the other extensions run
            assert client.get("/healthz").status_code == 200
    assert calls[3:] == ["stop third", "stop second", "stop first"]
    messages = [r.getMessage() for r in caplog.records]
    assert "extension first: on_start failed" in messages
    assert "extension second: on_stop failed" in messages


def test_web_router_is_mounted_at_the_root(client):
    r = client.get("/third-page")
    assert r.status_code == 200 and r.text == "page of third"
    assert "content-security-policy" in r.headers
    assert client.get("/api/x/third/third-page").status_code == 404


def test_extra_page(web_dir):
    web = WebFrontend(web_dir)
    assert web.extra_page("wall.html") is None
    (web_dir / "wall.html").write_text("<!doctype html><title>Wall</title>\n", encoding="utf-8")
    page = web.extra_page("wall.html")
    assert page is not None and page.status_code == 200
    assert page.body == b"<!doctype html><title>Wall</title>\n"
    assert page.headers["cache-control"] == "private, no-cache"
    etag = page.headers["etag"]
    again = web.extra_page("wall.html")
    assert again is not None and again.headers["etag"] == etag
    (web_dir / "wall.html").write_text("<!doctype html><title>Neu</title>\n", encoding="utf-8")
    changed = web.extra_page("wall.html")
    assert changed is not None and changed.headers["etag"] != etag
    for name in ("index.html", "../wall.html", "Wall.html", ".wall.html", "wall.js", "a/b.html"):
        assert web.extra_page(name) is None, name


def test_extra_page_dev_placeholder():
    page = WebFrontend(None).extra_page("wall.html")
    assert page is not None and page.status_code == 200
    assert b"dev-placeholder" in page.body and b"<script" not in page.body
    assert b"style" not in page.body
