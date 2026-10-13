"""Admin QR codes (`/api/admin/codes`): numbering, names, tokens, target and
note, revoking, audit, events; the QR-Bogen export job and the QR CLI with
codes. Access through the codes (the gate): test_code_access.py."""

from __future__ import annotations

import random
from typing import Any

import pytest

from virtubooth.api.schemas.events import AdminEvent
from virtubooth.domain import codes as dc
from virtubooth.tools import qr as qr_tool

from ..conftest import ORIGIN, PARTY_TOKEN

CUSTOM = "my-printed-token-0123"


@pytest.fixture
def published(core, monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    seen: list[tuple[str, dict[str, Any]]] = []
    real = core.bus.publish

    def spy(type_: str, data: dict[str, Any]) -> None:
        seen.append((type_, data))
        real(type_, data)

    monkeypatch.setattr(core.bus, "publish", spy)
    return seen


def listing(admin) -> dict[str, Any]:
    r = admin.get("/api/admin/codes")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def create(admin, expect: int = 201, **body: Any) -> dict[str, Any]:
    r = admin.post("/api/admin/codes", json=body, headers=ORIGIN)
    assert r.status_code == expect, r.text
    out: dict[str, Any] = r.json()
    return out


def retoken(admin, code_id: int, token: str | None, expect: int = 200) -> dict[str, Any]:
    r = admin.post(f"/api/admin/codes/{code_id}/token", json={"token": token}, headers=ORIGIN)
    assert r.status_code == expect, r.text
    out: dict[str, Any] = r.json()
    return out


def patch(admin, code_id: int, expect: int = 200, **body: Any) -> dict[str, Any]:
    r = admin.patch(f"/api/admin/codes/{code_id}", json=body, headers=ORIGIN)
    assert r.status_code == expect, r.text
    out: dict[str, Any] = r.json()
    return out


def revoke(admin, code_id: int, expect: int = 200) -> dict[str, Any]:
    r = admin.delete(f"/api/admin/codes/{code_id}", headers=ORIGIN)
    assert r.status_code == expect, r.text
    out: dict[str, Any] = r.json()
    return out


def audit(admin, prefix: str = "code.") -> list[dict[str, Any]]:
    entries = admin.get("/api/admin/audit").json()["entries"]
    return [e for e in entries if e["action"].startswith(prefix)]


# ----------------------------------------------------------------- reading


def test_code_1_is_listed(admin):
    body = listing(admin)
    assert (body["active"], body["revoked"], body["base_url"]) == (1, 0, None)
    [code] = body["codes"]
    assert code["id"] == 1 and code["name"] == f"{code['animal']} 1"
    assert code["animal"] in dc.ANIMALS
    assert code["token"] == PARTY_TOKEN and code["token_gen"] == 1
    assert code["entry_path"] == f"/?t={PARTY_TOKEN}"
    assert code["active"] is True and code["revoked_at"] is None and code["revoked_by"] is None
    assert code["created_by"] == "system" and code["target"] == "" == code["note"]
    assert code["stats"] == {
        "scans": 0, "people": 0, "guests": 0, "not_joined": 0, "photos": 0, "active_now": 0,
        "first_scan_at": None, "last_scan_at": None,
    }  # fmt: skip
    one = admin.get("/api/admin/codes/1").json()
    assert one == {"code": code, "changed": False}


def test_base_url_is_the_public_url(admin, core):
    core.settings = core.settings.replace(public_base_url="https://party.example/")
    assert listing(admin)["base_url"] == "https://party.example"


def test_unknown_code_is_404(admin):
    for method, path, body in (
        ("GET", "/api/admin/codes/99", None),
        ("PATCH", "/api/admin/codes/99", {"note": "x"}),
        ("POST", "/api/admin/codes/99/token", {"token": None}),
        ("DELETE", "/api/admin/codes/99", None),
    ):
        r = admin.request(method, path, json=body, headers=ORIGIN)
        assert r.status_code == 404, (method, r.text)
        assert r.json() == {"error": "not_found", "message": "QR-Code nicht gefunden."}
    assert admin.get("/api/admin/codes/0").status_code == 422
    assert admin.get("/api/admin/codes/abc").status_code == 422


def test_codes_need_an_admin(client, guest):
    for c in (client, guest()):
        assert c.get("/api/admin/codes").status_code == 401
        r = c.post("/api/admin/codes", json={}, headers=ORIGIN)
        assert r.status_code == 401 and r.json()["error"] == "admin_required"
        assert c.delete("/api/admin/codes/1", headers=ORIGIN).status_code == 401
    # and the CSRF origin check applies
    assert client.post("/api/admin/codes", json={}).status_code == 403


# ---------------------------------------------------------------- creating


def test_create_with_a_generated_token(admin, core):
    out = create(admin)
    code = out["code"]
    assert out["changed"] is True
    assert code["id"] == 2 and code["name"] == f"{code['animal']} 2"
    assert len(code["token"]) == 24 and dc.token_problem(code["token"]) is None
    assert code["entry_path"] == f"/?t={code['token']}"
    assert code["created_by"].startswith("admin:") and code["active"]
    assert core.services.codes.entry(code["token"]).id == 2


def test_create_with_a_custom_token_target_and_note(admin):
    code = create(admin, token=f"  {CUSTOM} ", target="demo", note="  Eingang  ")["code"]
    assert code["token"] == CUSTOM
    assert (code["target"], code["note"]) == ("demo", "Eingang")
    assert code["entry_path"] == f"/x/demo/?t={CUSTOM}"


@pytest.mark.parametrize(
    ("token", "message"),
    [
        ("short", dc.TOKEN_INVALID),
        (f"http://testserver/x/demo/?t={CUSTOM}", dc.TOKEN_INVALID),
        (f"/?t={CUSTOM}", dc.TOKEN_INVALID),
        ("with spaces inside it", dc.TOKEN_INVALID),
        ("x" * 129, dc.TOKEN_INVALID),
        ("", dc.TOKEN_INVALID),
        ("abababababababababab", dc.TOKEN_TOO_SIMPLE),
    ],
)
def test_unusable_tokens_are_refused(admin, token, message):
    r = admin.post("/api/admin/codes", json={"token": token}, headers=ORIGIN)
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_token", "message": message}
    r = admin.post("/api/admin/codes/1/token", json={"token": token}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["error"] == "invalid_token"
    assert [c["id"] for c in listing(admin)["codes"]] == [1]


def test_numbers_are_never_reused_and_names_follow_them(admin, core):
    core.services.codes.rng = random.Random(5)
    for expected in (2, 3):
        assert create(admin)["code"]["id"] == expected
    revoke(admin, 2)
    code = create(admin)["code"]
    assert code["id"] == 4
    body = listing(admin)
    assert [c["id"] for c in body["codes"]] == [1, 2, 3, 4]
    assert (body["active"], body["revoked"]) == (3, 1)
    names = [c["name"] for c in body["codes"]]
    assert names == [f"{c['animal']} {c['id']}" for c in body["codes"]]
    # the first hundred codes all get different animals
    assert len({c["animal"] for c in body["codes"]}) == 4


def test_a_token_is_never_handed_out_twice(admin):
    code = create(admin, token=CUSTOM)["code"]
    taken = {
        "error": "token_taken",
        "message": "Dieses Token hatte schon ein QR-Code. Ein Token wird nie zweimal vergeben.",
    }
    # the current token of another code
    for token in (CUSTOM, PARTY_TOKEN):
        r = admin.post("/api/admin/codes", json={"token": token}, headers=ORIGIN)
        assert r.status_code == 409 and r.json() == taken
    # a token a code had before
    new = retoken(admin, code["id"], None)["code"]
    assert new["token_gen"] == 2 and new["token"] != CUSTOM
    r = admin.post("/api/admin/codes", json={"token": CUSTOM}, headers=ORIGIN)
    assert r.status_code == 409 and r.json() == taken
    r = admin.post("/api/admin/codes/1/token", json={"token": CUSTOM}, headers=ORIGIN)
    assert r.status_code == 409 and r.json() == taken
    # its own current token, too
    r = admin.post(f"/api/admin/codes/{code['id']}/token", json={"token": new["token"]},
                   headers=ORIGIN)  # fmt: skip
    assert r.status_code == 409
    # a revoked code's token stays taken
    revoke(admin, code["id"])
    r = admin.post("/api/admin/codes", json={"token": new["token"]}, headers=ORIGIN)
    assert r.status_code == 409


def test_change_the_token(admin, core):
    out = retoken(admin, 1, CUSTOM)
    assert out["changed"] is True
    code = out["code"]
    assert (code["token"], code["token_gen"], code["entry_path"]) == (CUSTOM, 2, f"/?t={CUSTOM}")
    assert core.services.codes.entry(PARTY_TOKEN) is None
    assert core.services.codes.entry(CUSTOM).id == 1
    generated = retoken(admin, 1, None)["code"]
    assert generated["token_gen"] == 3 and len(generated["token"]) == 24
    hashes = core.db.all("SELECT token_hash, retired_at FROM party_code_tokens WHERE code_id=1")
    assert len(hashes) == 3 and sum(r["retired_at"] is None for r in hashes) == 1
    r = admin.post("/api/admin/codes/1/token", json={}, headers=ORIGIN)
    assert r.status_code == 422  # null must be said: no accidental new token


# ------------------------------------------------------- target and note


def test_edit_target_and_note(admin):
    out = patch(admin, 1, target="demo", note="Bar")
    assert out["changed"] is True
    code = out["code"]
    assert (code["target"], code["note"], code["entry_path"]) == (
        "demo", "Bar", f"/x/demo/?t={PARTY_TOKEN}",
    )  # fmt: skip
    assert code["name"] == listing(admin)["codes"][0]["name"]  # name and number stay
    # null = unchanged; the same values change nothing
    assert patch(admin, 1, note="Bar")["changed"] is False
    assert patch(admin, 1)["changed"] is False
    assert patch(admin, 1, target=None, note=None)["changed"] is False
    code = patch(admin, 1, target="")["code"]
    assert (code["target"], code["note"], code["entry_path"]) == ("", "Bar", f"/?t={PARTY_TOKEN}")
    assert [e["action"] for e in audit(admin, "code.edit")] == ["code.edit", "code.edit"]


@pytest.mark.parametrize(
    ("body", "error", "message"),
    [
        ({"target": "booth"}, "invalid_target", "Unbekanntes Ziel."),
        ({"target": "../admin"}, "invalid_target", "Unbekanntes Ziel."),
        ({"note": "x" * 61}, "invalid_note", "Die Notiz darf höchstens 60 Zeichen haben."),
        ({"note": "zwei\nZeilen"}, "invalid_note", dc.NOTE_CONTROL),
    ],
)
def test_target_and_note_are_checked(admin, body, error, message):
    for r in (
        admin.post("/api/admin/codes", json=body, headers=ORIGIN),
        admin.patch("/api/admin/codes/1", json=body, headers=ORIGIN),
    ):
        assert r.status_code == 400
        assert r.json() == {"error": error, "message": message}
    assert patch(admin, 1, note="x" * 60)["code"]["note"] == "x" * 60


def test_a_target_that_is_no_longer_loaded(admin, core):
    patch(admin, 1, target="demo")
    del core.extensions["demo"]
    code = listing(admin)["codes"][0]
    assert code["target"] == "demo"  # shown as „Ziel nicht verfügbar“
    assert code["entry_path"] == f"/?t={PARTY_TOKEN}"
    # the note can still be changed; the stored target stays unless it is changed
    code = patch(admin, 1, note="Garten", target="demo")["code"]
    assert code["target"] == "demo" and code["note"] == "Garten"
    assert patch(admin, 1, target="")["code"]["target"] == ""
    assert (
        admin.patch("/api/admin/codes/1", json={"target": "demo"}, headers=ORIGIN).status_code
        == 400
    )


# ----------------------------------------------------------------- revoking


def test_revoke_keeps_a_tombstone(admin, core):
    code = create(admin, note="Bar")["code"]
    out = revoke(admin, code["id"])
    assert out["changed"] is True
    tomb = out["code"]
    assert (
        tomb["active"] is False and tomb["revoked_at"] and tomb["revoked_by"].startswith("admin:")
    )
    assert (tomb["id"], tomb["name"], tomb["token"], tomb["note"]) == (
        code["id"], code["name"], code["token"], "Bar",
    )  # fmt: skip
    assert core.services.codes.entry(code["token"]) is None
    again = revoke(admin, code["id"])
    assert again == {"code": again["code"], "changed": False}
    assert again["code"]["revoked_at"] == tomb["revoked_at"]
    assert admin.get(f"/api/admin/codes/{code['id']}").json()["code"]["active"] is False
    revoked = {"error": "code_revoked",
               "message": "Dieser QR-Code ist gelöscht und lässt sich nicht mehr ändern."}  # fmt: skip
    r = admin.patch(f"/api/admin/codes/{code['id']}", json={"note": "x"}, headers=ORIGIN)
    assert r.status_code == 409 and r.json() == revoked
    for token in (None, CUSTOM, "short"):
        r = admin.post(f"/api/admin/codes/{code['id']}/token", json={"token": token},
                       headers=ORIGIN)  # fmt: skip
        assert r.status_code == 409 and r.json() == revoked
    assert [e["action"] for e in audit(admin, "code.revoke")] == ["code.revoke"]


def test_the_last_active_code_can_be_revoked(admin, core):
    revoke(admin, 1)
    body = listing(admin)
    assert (body["active"], body["revoked"]) == (0, 1)
    assert core.services.codes.entry(PARTY_TOKEN) is None


# ------------------------------------------------------------ audit, events


def test_every_change_is_audited_without_the_token(admin):
    code = create(admin, token=CUSTOM, target="demo", note="Eingang")["code"]
    patch(admin, code["id"], note="Bar")
    new = retoken(admin, code["id"], None)["code"]
    retoken(admin, code["id"], "another-own-token-42")
    revoke(admin, code["id"])
    entries = audit(admin)
    target = f"code:{code['id']}"
    mine = [(e["action"], e["details"]) for e in entries if e["target"] == target]
    assert mine == [
        ("code.revoke", {"name": code["name"]}),
        ("code.token", {"token": "eigenes", "token_end": "n-42"}),
        ("code.token", {"token": "erzeugt", "token_end": new["token"][-4:]}),
        ("code.edit", {"target": "demo", "note": "Bar"}),
        ("code.create", {"name": code["name"], "target": "demo", "note": "Eingang",
                         "token": "eigenes", "token_end": "0123"}),
    ]  # fmt: skip
    assert all(e["actor"].startswith("admin:") for e in entries if e["target"] == target)
    text = str(entries)
    for token in (CUSTOM, new["token"], "another-own-token-42", PARTY_TOKEN):
        assert token not in text
    # the seed entry of code 1
    assert entries[-1]["action"] == "code.create" and entries[-1]["actor"] == "system"
    assert entries[-1]["details"]["token"] == "VB_PARTY_TOKEN"
    # refused changes leave no entry
    admin.post("/api/admin/codes", json={"token": "short"}, headers=ORIGIN)
    patch(admin, 1, expect=400, target="nope")
    assert len(audit(admin)) == len(entries)


def test_code_changed_events(admin, published):
    code = create(admin)["code"]
    patch(admin, code["id"], note="Bar")
    patch(admin, code["id"], note="Bar")  # unchanged: no event
    retoken(admin, code["id"], None)
    revoke(admin, code["id"])
    revoke(admin, code["id"])  # revoked already: no event
    ours = [(t, d) for t, d in published if t == "code.changed"]
    assert [d["change"] for _, d in ours] == ["created", "edited", "token", "revoked"]
    assert all(d["code"]["id"] == code["id"] for _, d in ours)
    assert ours[1][1]["code"]["note"] == "Bar"
    assert ours[2][1]["code"]["token_gen"] == 2
    assert ours[3][1]["code"]["active"] is False
    for i, (type_, data) in enumerate(ours):
        AdminEvent.model_validate({"type": type_, "id": f"0badcafe-{i}", "data": data})


# --------------------------------------------- the QR-Bogen job, the QR CLI


def test_qr_job_uses_the_lowest_active_code(admin, core):
    from .test_admin_exports import download, run, strip_root, unzip

    core.settings = core.settings.replace(public_base_url="https://party.example")
    retoken(admin, 1, CUSTOM)
    create(admin, token="second-code-token-777")
    done = run(admin, core, "qr")
    files = strip_root(unzip(download(admin, done).content), done["file_name"][:-4])
    assert files["qr-home.svg"]
    assert qr_tool.home_url("https://party.example", CUSTOM).encode() not in files["qr-home.svg"]
    expected = qr_tool.make_qr(qr_tool.home_url("https://party.example", CUSTOM))
    assert (
        files["qr-sheet.html"]
        .decode()
        .count(expected.svg_inline(scale=1, border=4, dark="#000", light="#fff", omitsize=True))
        == 1
    )
    revoke(admin, 1)
    second = qr_tool.make_qr(qr_tool.home_url("https://party.example", "second-code-token-777"))
    done = run(admin, core, "qr")
    sheet = strip_root(unzip(download(admin, done).content), done["file_name"][:-4])
    assert second.svg_inline(scale=1, border=4, dark="#000", light="#fff", omitsize=True) in (
        sheet["qr-sheet.html"].decode()
    )


def test_qr_job_without_an_active_code_fails(admin, core):
    from .test_admin_exports import run

    core.settings = core.settings.replace(public_base_url="https://party.example")
    revoke(admin, 1)
    job = run(admin, core, "qr")
    assert job["status"] == "failed"
    assert job["error"] == "Kein aktiver QR-Code. Leg im Tab „QR-Codes“ einen an."


def test_qr_cli_takes_the_token_from_the_database(admin, core, tmp_path, monkeypatch, capsys):
    data_dir = str(core.settings.data_dir)
    out = tmp_path / "qr"
    base = ["--base-url", "https://party.example", "--no-home", "--extensions", "beer",
            "--data-dir", data_dir, "--out", str(out)]  # fmt: skip

    def url_in_sheet(token: str) -> bool:
        code = qr_tool.make_qr(qr_tool.extension_url("https://party.example", token, "beer"))
        inline = code.svg_inline(scale=1, border=4, dark="#000", light="#fff", omitsize=True)
        return inline in (out / "qr-sheet.html").read_text()

    monkeypatch.setenv("VB_PARTY_TOKEN", "env-token-not-used-0000")
    retoken(admin, 1, CUSTOM)
    second = create(admin, token="second-code-token-777")["code"]
    # default: the active code with the lowest number
    assert qr_tool.main(base) == 0 and url_in_sheet(CUSTOM)
    assert qr_tool.main([*base, "--code", str(second["id"])]) == 0
    assert url_in_sheet("second-code-token-777")
    assert qr_tool.main([*base, "--token", "explicit-token-abcdef"]) == 0
    assert url_in_sheet("explicit-token-abcdef")
    capsys.readouterr()
    assert qr_tool.main([*base, "--code", "9"]) == 1
    assert "there is no QR code 9" in capsys.readouterr().err
    revoke(admin, 1)
    assert qr_tool.main([*base, "--code", "1"]) == 1
    assert "is deleted" in capsys.readouterr().err
    assert qr_tool.main(base) == 0 and url_in_sheet("second-code-token-777")
    revoke(admin, second["id"])
    assert qr_tool.main(base) == 1
    assert "every QR code in the database is deleted" in capsys.readouterr().err


def test_qr_cli_without_a_database_uses_the_env_token(tmp_path, monkeypatch, capsys):
    out = tmp_path / "qr"
    base = ["--base-url", "https://party.example", "--no-home", "--extensions", "beer",
            "--data-dir", str(tmp_path / "nothing"), "--out", str(out)]  # fmt: skip
    monkeypatch.setenv("VB_PARTY_TOKEN", "env-token-for-the-cli-0")
    assert qr_tool.main(base) == 0
    assert qr_tool.main([*base, "--code", "1"]) == 1
    assert "--code needs the database" in capsys.readouterr().err
