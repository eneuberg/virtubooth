"""`virtubooth export-openapi`: the schema the frontend's typed client is built from."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import get_args

import pytest

from virtubooth.__main__ import main
from virtubooth.api.schemas.events import ADMIN_EVENT_TYPES
from virtubooth.core.errors import ErrorCode

# files, documented as binary: (method, path) -> media types
BINARY = {
    ("get", "/media/{public_id}"): {"image/jpeg"},
    ("get", "/api/admin/exports/{job_id}/download"): {"application/zip", "video/mp4"},
    ("get", "/api/admin/instagram/{handle}/photos.zip"): {"application/zip"},
    ("get", "/api/admin/poster/template"): {"application/pdf"},
}


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, dict]:
    out = tmp_path_factory.mktemp("openapi") / "openapi.json"
    main(["export-openapi", "-o", str(out)])
    text = out.read_text(encoding="utf-8")
    return text, json.loads(text)


def test_export_is_deterministic_json(exported, tmp_path, monkeypatch):
    text, schema = exported
    assert text == json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    # the developer's settings don't change it
    monkeypatch.setenv("VB_EXTENSIONS", "beer")
    monkeypatch.setenv("VB_PARTY_NAME", "Somewhere else")
    again = tmp_path / "again.json"
    main(["export-openapi", "-o", str(again)])
    assert again.read_text(encoding="utf-8") == text


def test_cli_entry_point_writes_the_file(tmp_path):
    out = tmp_path / "sub" / "openapi.json"
    subprocess.run(
        [sys.executable, "-m", "virtubooth", "export-openapi", "-o", str(out)],
        check=True,
        capture_output=True,
        cwd=tmp_path,
    )
    assert json.loads(out.read_text(encoding="utf-8"))["info"]["title"] == "virtubooth"


def test_every_route_has_a_response_schema(exported):
    _, schema = exported
    paths = schema["paths"]
    assert len(paths) >= 30
    for path, operations in paths.items():
        for method, op in operations.items():
            ok = {code: r for code, r in op["responses"].items() if code.startswith("2")}
            assert ok, f"{method} {path} has no 2xx response"
            for code, response in ok.items():
                content = response.get("content", {})
                if (method, path) in BINARY:
                    assert set(content) == BINARY[method, path], (method, path)
                    for media in content.values():
                        assert media["schema"] == {"type": "string", "format": "binary"}
                    continue
                if path == "/api/admin/events":
                    item = content["text/event-stream"]["itemSchema"]
                    ref = item["properties"]["data"]["contentSchema"]["$ref"]
                    assert ref == "#/components/schemas/AdminEvent"
                    continue
                if path == "/livewall/api/stream":
                    item = content["text/event-stream"]["itemSchema"]
                    ref = item["properties"]["data"]["contentSchema"]["$ref"]
                    assert ref == "#/components/schemas/WallEvent"
                    continue
                body = content["application/json"]["schema"]
                assert body.get("$ref") or body.get("oneOf") or body.get("anyOf"), (
                    method,
                    path,
                    code,
                )


def test_errors_use_error_body(exported):
    _, schema = exported
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method, op in operations.items():
            errors = {code: r for code, r in op["responses"].items() if code[0] in "45"}
            assert errors, f"{method} {path} declares no errors"
            for code, response in errors.items():
                ref = response["content"]["application/json"]["schema"]["$ref"]
                assert ref == "#/components/schemas/ErrorBody", (method, path, code)
            # the framework's own 422 schema is replaced
            assert "HTTPValidationError" not in json.dumps(op)
    codes = schema["components"]["schemas"]["ErrorBody"]["properties"]["error"]["enum"]
    assert set(codes) == set(get_args(ErrorCode))


def test_main_schemas_are_components(exported):
    _, schema = exported
    components = schema["components"]["schemas"]
    for name in (
        "AdminEvent", "ErrorBody", "GuestUser", "GuestPhoto", "MyPhotosOut", "IdentifiedOut",
        "NeedsConsentOut", "JoinOut", "UploadOut", "AdminPhoto", "AdminUser", "UserRef",
        "PhotoListOut", "UserListOut", "StatsOut", "InstagramOut", "AuditOut", "StopState",
        "PauseState", "BeerStats", "BoothFilters", "ExtensionsOut",
    ):  # fmt: skip
        assert name in components, name
    # every event type is a variant of the AdminEvent union
    union = components["AdminEvent"]
    mapping = union["discriminator"]["mapping"]
    assert set(mapping) == {*ADMIN_EVENT_TYPES, "stream.resync"}
    # the upload answer lists the extensions' fields
    upload = components["UploadOut"]["properties"]
    assert {"photo", "beer_number", "total", "booth_number"} <= set(upload)


def test_new_endpoints_are_documented(exported):
    _, schema = exported
    me_photos = schema["paths"]["/api/me/photos"]["get"]["responses"]["200"]
    assert me_photos["content"]["application/json"]["schema"]["$ref"].endswith("/MyPhotosOut")
    assert "/api/x/booth/filters" in schema["paths"]
    # wave 2: exports and the Instagram board
    paths = schema["paths"]
    create = paths["/api/admin/exports"]["post"]
    assert {"200", "202", "409"} <= set(create["responses"])
    assert create["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/ExportIn"
    )
    export_in = schema["components"]["schemas"]["ExportIn"]
    assert set(export_in["discriminator"]["mapping"]) == {"archive", "timelapse"}
    assert "409" in paths["/api/admin/exports/{job_id}"]["delete"]["responses"]
    assert "post" in paths["/api/admin/instagram/{handle}/done"]
    handle = schema["components"]["schemas"]["InstagramHandleOut"]
    assert "done" in handle["required"]
    job = schema["components"]["schemas"]["ExportJob"]
    assert {"id", "kind", "status", "progress", "created_at", "started_at", "finished_at",
            "error", "file_name", "bytes", "options", "download_url"} <= set(job["required"])  # fmt: skip
    # pages are not part of the API
    assert not any(p.startswith(("/admin", "/assets", "/x/")) for p in schema["paths"])
    assert "/" not in schema["paths"]


def test_runtime_docs_stay_off(client):
    for path in ("/openapi.json", "/docs", "/redoc"):
        assert client.get(path).status_code == 404


def test_export_to_stdout(capsys):
    main(["export-openapi", "-o", "-"])
    assert json.loads(capsys.readouterr().out)["openapi"].startswith("3.")


def test_written_into_new_directories(tmp_path: Path):
    out = tmp_path / "a" / "b" / "openapi.json"
    main(["export-openapi", "--out", str(out)])
    assert out.is_file()
