"""QR codes across features: the code on every admin guest (`AdminUser.code`),
the guests list filtered by code, the per-code online time and the overview's
per-code table."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from virtubooth.core.clock import iso

from ..conftest import ORIGIN, accept_consent
from .test_admin_dashboard import overview, user_id_of

TOKEN_2 = "second-code-token-777"


def create_code(admin, token: str) -> dict[str, Any]:
    r = admin.post("/api/admin/codes", json={"token": token}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    code: dict[str, Any] = r.json()["code"]
    return code


def joined_via(make_client, token: str, fp_n: int):
    c = make_client()
    assert c.get(f"/?t={token}").status_code == 303
    accept_consent(c, fp_n=fp_n)
    return c


def users(admin, **query: Any) -> list[dict[str, Any]]:
    r = admin.get("/api/admin/users", params=query)
    assert r.status_code == 200, r.text
    result: list[dict[str, Any]] = r.json()["users"]
    return result


def code_of(admin, code_id: int) -> dict[str, Any]:
    r = admin.get(f"/api/admin/codes/{code_id}")
    assert r.status_code == 200, r.text
    code: dict[str, Any] = r.json()["code"]
    return code


def test_guests_carry_their_code_and_filter_by_it(admin, guest, make_client, core):
    one = guest()
    second = create_code(admin, TOKEN_2)
    two = joined_via(make_client, TOKEN_2, fp_n=2)
    id_one, id_two = user_id_of(core, one), user_id_of(core, two)
    name_one = code_of(admin, 1)["name"]

    listed = {u["id"]: u["code"] for u in users(admin)}
    assert listed[id_one] == {"id": 1, "name": name_one, "active": True}
    assert listed[id_two] == {"id": second["id"], "name": second["name"], "active": True}
    assert [u["id"] for u in users(admin, code=second["id"])] == [id_two]
    assert [u["id"] for u in users(admin, code=1)] == [id_one]
    assert users(admin, code=99) == []
    assert admin.get("/api/admin/users", params={"code": 0}).status_code in (400, 422)

    # deleting the code keeps the guest's reference, marked inactive
    assert admin.delete(f"/api/admin/codes/{second['id']}", headers=ORIGIN).status_code == 200
    detail = admin.get(f"/api/admin/users/{id_two}").json()
    assert detail["user"]["code"] == {"id": second["id"], "name": second["name"], "active": False}

    # a guest without a code (from before the codes): null
    with core.db.tx() as c:
        c.execute("UPDATE users SET code_id=NULL WHERE id=?", (id_one,))
    assert admin.get(f"/api/admin/users/{id_one}").json()["user"]["code"] is None


def test_code_stats_add_up_online_time(admin, guest, core):
    g, other = guest(), guest(fp_n=2)
    now = datetime.now(UTC)
    with core.db.tx() as c:
        c.execute(
            "UPDATE users SET online_seconds=100, online_at=? WHERE id=?",
            (iso(now - timedelta(seconds=30)), user_id_of(core, g)),
        )
        c.execute(
            "UPDATE users SET online_seconds=50, online_at=? WHERE id=?",
            (iso(now - timedelta(seconds=600)), user_id_of(core, other)),  # gone quiet
        )
    stats = code_of(admin, 1)["stats"]
    assert (stats["online_seconds"], stats["online_now"]) == (150, 1)


def test_overview_lists_the_codes(admin, guest, make_client):
    guest()
    second = create_code(admin, TOKEN_2)
    third = create_code(admin, "third-code-token-888")
    joined_via(make_client, TOKEN_2, fp_n=2)
    # deleted without a scan: gone from the overview; deleted after a scan: stays
    assert admin.delete(f"/api/admin/codes/{third['id']}", headers=ORIGIN).status_code == 200
    assert admin.delete(f"/api/admin/codes/{second['id']}", headers=ORIGIN).status_code == 200

    codes = overview(admin)["codes"]
    assert [c["id"] for c in codes] == [1, second["id"]]
    row = codes[1]
    assert row == {
        "id": second["id"], "name": second["name"], "active": False, "scans": 1, "people": 1,
        "guests": 1, "photos": 0, "active_now": 1,
    }  # fmt: skip
    assert codes[0]["active"] and codes[0]["guests"] == 1


def test_qr_cli_takes_the_event_name_from_the_database(admin, core, tmp_path, monkeypatch):
    from virtubooth.tools import qr as qr_tool

    monkeypatch.setenv("VB_PARTY_NAME", "Envparty")
    out = tmp_path / "qr"
    base = ["--base-url", "https://party.example", "--extensions", "beer",
            "--data-dir", str(core.settings.data_dir), "--out", str(out)]  # fmt: skip
    assert qr_tool.main(base) == 0
    assert "<title>QR-Codes · Envparty</title>" in (out / "qr-sheet.html").read_text()
    r = admin.put("/api/admin/settings/event", json={"name": "Lenas 30."}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert qr_tool.main(base) == 0
    assert "<title>QR-Codes · Lenas 30.</title>" in (out / "qr-sheet.html").read_text()
    assert qr_tool.main([*base, "--party-name", "Andere"]) == 0
    assert "<title>QR-Codes · Andere</title>" in (out / "qr-sheet.html").read_text()
