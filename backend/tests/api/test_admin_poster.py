"""The poster template (`/api/admin/poster`): upload (streamed, capped, admin only),
the bytes back with safe headers, the QR-field layout and its checks, delete, audit."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import AsyncIterator
from typing import Any

import anyio
import pytest
from PIL import Image

from virtubooth.core.errors import ApiError
from virtubooth.services import posters

from ..conftest import BASE_URL, ORIGIN

PDF = {"Content-Type": "application/pdf", "Origin": BASE_URL}
A4 = (595.0, 842.0)


def pdf_bytes(pages: int = 2) -> bytes:
    """A small PDF made with Pillow: one A4-sized image per page."""
    images = [Image.new("RGB", (595, 842), (255, 255 - 40 * i, 255)) for i in range(pages)]
    buf = io.BytesIO()
    images[0].save(buf, "PDF", save_all=True, append_images=images[1:], resolution=72)
    return buf.getvalue()


def upload(client, data: bytes, headers: dict[str, str] = PDF, expect: int = 200) -> Any:
    r = client.put("/api/admin/poster/template", content=data, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


def layout(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "page": 1,
        "pages": 2,
        "page_width": A4[0],
        "page_height": A4[1],
        # 30 % of the width, square in points
        "rect": {"x": 0.35, "y": 0.4, "w": 0.3, "h": 0.3 * A4[0] / A4[1]},
    }
    rect = changes.pop("rect", None)
    body.update(changes)
    if rect is not None:
        body["rect"] = {**body["rect"], **rect}
    return body


def put_layout(client, body: dict[str, Any], expect: int = 200) -> Any:
    r = client.put("/api/admin/poster/layout", json=body, headers=ORIGIN)
    assert r.status_code == expect, r.text
    return r.json()


def audit_actions(core) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (e.action, e.target, e.details) for e in core.repos.audit.list() if "poster" in e.action
    ]


# ------------------------------------------------------------------ upload


def test_no_template_at_first(admin):
    r = admin.get("/api/admin/poster")
    assert r.status_code == 200
    assert r.json() == {"template": None, "max_bytes": 8_000_000}
    r = admin.get("/api/admin/poster/template")
    assert r.status_code == 409 and r.json()["error"] == "no_template"
    assert r.json()["message"] == "Erst eine Vorlage hochladen."


def test_upload_stores_the_file_and_meta(admin, core, settings):
    data = pdf_bytes()
    body = upload(admin, data)
    meta = body["template"]
    assert body["max_bytes"] == 8_000_000
    assert meta["sha256"] == hashlib.sha256(data).hexdigest()
    assert meta["bytes"] == len(data)
    assert meta["by"].startswith("admin:")
    assert meta["uploaded_at"]
    for key in ("pages", "page", "page_width", "page_height", "rect"):
        assert meta[key] is None
    stored = settings.data_dir / "poster" / "template.pdf"
    assert stored.read_bytes() == data
    assert not (settings.data_dir / "poster" / "template.pdf.part").exists()
    assert admin.get("/api/admin/poster").json() == body
    assert core.repos.app_settings.get("poster.template")["sha256"] == meta["sha256"]

    r = admin.get("/api/admin/poster/template")
    assert r.status_code == 200
    assert r.content == data
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'attachment; filename="plakat-vorlage.pdf"'
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["x-vb-event-id"]
    assert audit_actions(core) == [("poster.template", "", {"bytes": len(data)})]


def test_not_a_pdf(admin, settings):
    r = admin.put("/api/admin/poster/template", content=b"GIF89a" + b"\0" * 2000, headers=PDF)
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_pdf", "message": "Das ist keine PDF-Datei."}
    # the marker must come within the first 1024 bytes
    late = b" " * 1100 + pdf_bytes(1)
    assert admin.put("/api/admin/poster/template", content=late, headers=PDF).status_code == 400
    # an empty body is no PDF either
    assert admin.put("/api/admin/poster/template", content=b"", headers=PDF).status_code == 400
    assert not (settings.data_dir / "poster" / "template.pdf").exists()
    # a few junk bytes before the header are fine (some writers do that)
    upload(admin, b"\n\n" + pdf_bytes(1))


def test_declared_too_large_is_refused_before_reading(admin):
    headers = {**PDF, "Content-Length": str(posters.MAX_BYTES + 1)}

    def body():
        yield b"%PDF-1.4\n"
        raise AssertionError("the body was read")

    r = admin.put("/api/admin/poster/template", content=body(), headers=headers)
    assert r.status_code == 413
    assert r.json() == {"error": "too_large", "message": "Die PDF ist zu groß (höchstens 8 MB)."}


def test_body_is_capped_while_reading(core, monkeypatch):
    """Declared small, but more arrives (the server stops reading at the cap)."""
    monkeypatch.setattr(posters, "MAX_BYTES", 1000)
    data = pdf_bytes(1)
    assert len(data) > 1000

    async def chunks() -> AsyncIterator[bytes]:
        for start in range(0, len(data), 400):
            yield data[start : start + 400]

    async def run() -> None:
        await core.services.posters.upload(
            chunks(), content_length="10", chunked=False, actor="admin:test"
        )

    with pytest.raises(ApiError) as exc:
        anyio.run(run)
    assert exc.value.code == "too_large"
    assert core.services.posters.template() is None


def test_content_length_required(admin):
    def body():
        yield pdf_bytes(1)

    # a generator body goes out chunked, without Content-Length
    r = admin.put("/api/admin/poster/template", content=body(), headers=PDF)
    assert r.status_code == 411 and r.json()["error"] == "length_required"


def test_needs_an_admin_session(client, guest):
    routes = [
        ("GET", "/api/admin/poster", None),
        ("PUT", "/api/admin/poster/template", b"%PDF-1.4"),
        ("GET", "/api/admin/poster/template", None),
        ("PUT", "/api/admin/poster/layout", json.dumps(layout()).encode()),
        ("DELETE", "/api/admin/poster/template", None),
    ]
    for c in (client, guest()):
        for method, path, content in routes:
            r = c.request(method, path, content=content, headers=PDF)
            assert r.status_code == 401, (method, path, r.text)
            assert r.json()["error"] == "admin_required"


def test_foreign_origin_is_refused(admin, settings):
    for origin in ({}, {"Origin": "https://evil.example"}):
        headers = {"Content-Type": "application/pdf", **origin}
        r = admin.put("/api/admin/poster/template", content=pdf_bytes(1), headers=headers)
        assert r.status_code == 403 and r.json()["error"] == "bad_origin"
        r = admin.request("DELETE", "/api/admin/poster/template", headers=origin)
        assert r.status_code == 403
    assert not (settings.data_dir / "poster").exists()


def test_new_upload_replaces_and_resets_the_layout(admin, settings):
    upload(admin, pdf_bytes(2))
    put_layout(admin, layout())
    data = pdf_bytes(3)
    meta = upload(admin, data)["template"]
    assert meta["rect"] is None and meta["page"] is None and meta["pages"] is None
    assert (settings.data_dir / "poster" / "template.pdf").read_bytes() == data


# ------------------------------------------------------------------ layout


def test_layout_is_saved(admin, core):
    upload(admin, pdf_bytes())
    body = layout()
    meta = put_layout(admin, body)["template"]
    assert meta["page"] == 1 and meta["pages"] == 2
    assert meta["page_width"] == A4[0] and meta["page_height"] == A4[1]
    assert meta["rect"] == body["rect"]
    assert admin.get("/api/admin/poster").json()["template"]["rect"] == body["rect"]
    assert ("poster.layout", "", {"page": 1, "pages": 2}) in audit_actions(core)


def test_layout_without_template(admin):
    r = admin.put("/api/admin/poster/layout", json=layout(), headers=ORIGIN)
    assert r.status_code == 409 and r.json()["error"] == "no_template"


@pytest.mark.parametrize(
    "changes",
    [
        {"rect": {"x": 0.8}},  # leaves the page on the right
        {"rect": {"y": 0.9}},  # below the page
        {"rect": {"x": -0.01}},
        {"rect": {"w": 0.02, "h": 0.02 * A4[0] / A4[1]}},  # under 3 %
        {"rect": {"h": 0.3}},  # not square in points (A4 is not square)
        {"page": 2},  # page >= pages
        {"page": -1},
        {"pages": 501, "page": 0},
        {"pages": 0, "page": 0},
        {"page_width": 0},
        {"page_height": 20000},
    ],
)
def test_layout_validation(admin, changes):
    upload(admin, pdf_bytes())
    r = admin.put("/api/admin/poster/layout", json=layout(**changes), headers=ORIGIN)
    assert r.status_code == 400, (changes, r.text)
    assert r.json() == {
        "error": "invalid_layout",
        "message": "Das QR-Feld muss ganz auf der Seite liegen und quadratisch sein.",
    }


def test_layout_edges_and_tolerance(admin):
    upload(admin, pdf_bytes())
    # flush with the bottom right corner (float noise allowed)
    h = 0.3 * A4[0] / A4[1]
    put_layout(admin, layout(rect={"x": 0.7 + 1e-7, "y": 1 - h, "w": 0.3, "h": h}))
    # 1.5 % off square is still square enough
    put_layout(admin, layout(rect={"h": h * 1.015}))
    # a square page: the same relative numbers
    put_layout(admin, layout(page_width=500, page_height=500, rect={"w": 0.4, "h": 0.4}))


def test_layout_rejects_junk_bodies(admin):
    upload(admin, pdf_bytes())
    r = admin.put("/api/admin/poster/layout", json={"page": 0}, headers=ORIGIN)
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"
    r = admin.put(
        "/api/admin/poster/layout",
        content=b'{"page": 0, "pages": 1, "page_width": NaN, "page_height": 842,'
        b' "rect": {"x": 0, "y": 0, "w": 0.5, "h": 0.5}}',
        headers={**ORIGIN, "Content-Type": "application/json"},
    )
    assert r.status_code in (400, 422)


# ------------------------------------------------------------------ delete


def test_delete_is_idempotent(admin, core, settings):
    upload(admin, pdf_bytes())
    for _ in range(2):
        r = admin.delete("/api/admin/poster/template", headers=ORIGIN)
        assert r.status_code == 200
        assert r.json() == {"template": None, "max_bytes": 8_000_000}
    assert not (settings.data_dir / "poster" / "template.pdf").exists()
    assert admin.get("/api/admin/poster/template").status_code == 409
    deletes = [a for a in audit_actions(core) if a[0] == "poster.template_delete"]
    assert deletes == [("poster.template_delete", "", {})]
    # and a new upload works afterwards
    upload(admin, pdf_bytes(1))
