"""The admin guest („Als Gast teilnehmen“, POST /api/admin/guest): the admin
session signs its own browser in to the guest app as the party's one admin
guest. Auth and CSRF of the two routes are also in test_admin_api.py's route
table."""

from __future__ import annotations

import csv
import io

from virtubooth.tools.export import USER_COLUMNS, users_csv

from ..conftest import ADMIN_PASSWORD, JPEG, ORIGIN, PARTY_TOKEN, accept_consent, jpeg, scan


def sign_in(client, status=200):
    r = client.post("/api/admin/guest", headers=ORIGIN)
    assert r.status_code == status, r.text
    return r.json()


def identify(client):
    r = client.post("/api/identify", json={}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    return r.json()


def upload(client, status=201):
    r = client.post("/api/x/demo/upload", content=jpeg(), headers=JPEG)
    assert r.status_code == status, r.text
    return r.json()


def post(client, path, json=None, status=200):
    r = client.post(path, json=json, headers=ORIGIN)
    assert r.status_code == status, r.text
    return r.json()


def user_of(core, client):
    public_id = core.signer.unsign("uid", client.cookies.get("vb_uid"))
    user = core.repos.users.get_by_public_id(public_id) if public_id else None
    assert user is not None
    return core.repos.users.get(user.id)


def secrets_of(core) -> list[str]:
    """Every QR token the party has, and the admin password: never in an answer."""
    return [c.token for c in core.repos.codes.list()] + [PARTY_TOKEN, ADMIN_PASSWORD]


# ---------------------------------------------------------------- sign in


def test_creates_the_admin_guest_once_and_signs_the_browser_in(admin, core):
    assert admin.get("/api/admin/guest").json() == {
        "user": None,
        "browser_is_host": False,
        "browser_guest": None,
    }
    first = sign_in(admin)
    assert first["created"] is True and first["url"] == "/" and first["replaced"] is None
    user = first["user"]
    assert user["is_host"] is True
    assert user["display_name"] == "Gastgeber" and user["shown_name"] == "Gastgeber"
    assert user["instagram"] is None and user["code"] is None
    assert not user["uploads_paused"] and not user["banned"]
    row = core.repos.users.get(user["id"])
    assert row.consent_version == core.settings.consent_version and row.code_id is None

    # idempotent: the same guest on every press (and from any admin session)
    again = sign_in(admin)
    assert again["created"] is False and again["user"]["id"] == user["id"]
    assert len([u for u in core.repos.users.list() if u.is_host]) == 1
    state = admin.get("/api/admin/guest").json()
    assert state["user"]["id"] == user["id"]
    assert state["browser_is_host"] is True and state["browser_guest"] is None


def test_sets_the_guest_cookie_and_no_party_token(admin, core):
    r = admin.post("/api/admin/guest", headers=ORIGIN)
    cookies = r.headers.get_list("set-cookie")
    assert any(c.startswith("vb_uid=") for c in cookies)
    assert not any(c.startswith("vb_access=") for c in cookies)  # no QR code involved
    assert user_of(core, admin).is_host
    for secret in secrets_of(core):
        assert secret not in r.text
        assert all(secret not in v for v in r.headers.values())
    entries = [e for e in core.repos.audit.list() if e.action == "host_guest.sign_in"]
    assert len(entries) == 1 and entries[0].actor.startswith("admin:")
    assert entries[0].details == {"created": True}
    for secret in secrets_of(core):
        assert secret not in repr(entries[0])


def test_the_guest_app_works_without_a_qr_scan(admin, core):
    sign_in(admin)
    assert admin.get("/").status_code == 200  # the guest page, not the gate
    body = identify(admin)
    assert body["state"] == "ok"
    assert body["user"]["is_host"] is True and body["user"]["shown_name"] == "Gastgeber"
    photo = upload(admin)["photo"]
    listed = admin.get("/api/admin/photos").json()["photos"]
    assert listed[0]["id"] == photo["id"] and listed[0]["user"]["is_host"] is True


def test_needs_an_admin_and_same_origin(client, guest, admin):
    g = guest()
    assert g.post("/api/admin/guest", headers=ORIGIN).status_code == 401
    assert client.post("/api/admin/guest", headers=ORIGIN).status_code == 401
    r = admin.post("/api/admin/guest", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"] == "bad_origin"
    assert admin.post("/api/admin/guest").status_code == 403  # no Origin at all
    assert "vb_uid" not in admin.cookies


def test_replaces_another_guest_identity_and_says_so(admin, core):
    scan(admin)
    accept_consent(admin)
    before = user_of(core, admin)
    assert not before.is_host
    assert admin.get("/api/admin/guest").json()["browser_guest"] == before.name
    out = sign_in(admin)
    assert out["replaced"] == before.name
    assert user_of(core, admin).is_host
    assert identify(admin)["user"]["is_host"] is True
    [entry] = [e for e in core.repos.audit.list() if e.action == "host_guest.sign_in"]
    assert entry.details == {"created": True, "replaced": f"user:{before.id}"}
    # the old guest is untouched (not deleted, not merged)
    assert core.repos.users.get(before.id) is not None
    assert sign_in(admin)["replaced"] is None  # already the admin guest


def test_a_normal_guest_never_becomes_the_admin_guest(admin, guest, core, make_client):
    sign_in(admin)
    g = guest()
    assert not user_of(core, g).is_host
    assert identify(g)["user"]["is_host"] is False
    r = g.patch("/api/me", json={"display_name": "Gastgeber"}, headers=ORIGIN)
    assert r.status_code == 400 and r.json()["error"] == "invalid_display_name"
    # a cookie with the admin guest's id but no valid signature counts for nothing
    host = core.repos.users.host()
    forged = make_client()
    forged.cookies.set("vb_uid", f"{host.public_id}.not-the-mac")
    r = forged.post("/api/identify", json={}, headers=ORIGIN)
    assert r.status_code == 404 and r.json()["error"] == "scan_qr"


def test_the_admin_guest_may_keep_its_reserved_name(admin):
    sign_in(admin)
    r = admin.patch("/api/me", json={"display_name": "Anna"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["user"]["shown_name"] == "Anna"
    r = admin.patch("/api/me", json={"display_name": "Gastgeber"}, headers=ORIGIN)
    assert r.status_code == 200 and r.json()["user"]["shown_name"] == "Gastgeber"


# ------------------------------------------------------------- exemptions


def test_join_stop_and_new_guest_lock_do_not_apply(admin, core):
    post(admin, "/api/admin/join-stop", {"enabled": True})
    post(admin, "/api/admin/upload-pause", {"enabled": True})
    user = sign_in(admin)["user"]
    assert user["uploads_paused"] is False
    upload(admin)


def test_the_upload_stop_applies_to_the_admin_guest_too(admin):
    sign_in(admin)
    post(admin, "/api/admin/upload-stop", {"enabled": True})
    r = admin.post("/api/x/demo/upload", content=jpeg(), headers=JPEG)
    assert r.status_code == 403 and r.json()["error"] == "uploads_stopped"


def test_no_photo_cap_for_the_admin_guest(admin, guest, core):
    core.settings = core.settings.replace(max_photos_per_guest=1)
    sign_in(admin)
    upload(admin)
    upload(admin)
    g = guest()
    upload(g)
    assert upload(g, status=403)["error"] == "photo_limit"


def test_the_admin_guest_cannot_be_banned(admin, core):
    host = sign_in(admin)["user"]
    r = admin.post(
        f"/api/admin/users/{host['id']}/ban", json={"reason": "x", "fingerprint": False},
        headers=ORIGIN,
    )  # fmt: skip
    assert r.status_code == 409 and r.json()["error"] == "host_guest"
    assert not core.repos.users.get(host["id"]).banned
    assert identify(admin)["state"] == "ok"


# --------------------------------------------------------- QR codes, stats


def test_codes_and_scan_counts_never_count_the_admin_guest(admin, guest, core):
    g = guest()
    upload(g)
    stats_before = core.repos.codes.stats()
    overview_before = admin.get("/api/admin/overview").json()
    host = sign_in(admin)["user"]
    identify(admin)
    upload(admin)
    admin.post("/api/here", json={"visible": True}, headers=ORIGIN)
    assert core.repos.codes.stats() == stats_before
    overview = admin.get("/api/admin/overview").json()
    assert overview["scans"] == overview_before["scans"]
    assert overview["guests"]["total"] == overview_before["guests"]["total"] + 1
    assert core.repos.users.get(host["id"]).code_id is None


def test_deleting_or_retokening_codes_never_locks_the_admin_guest_out(admin, core):
    sign_in(admin)
    post(admin, "/api/admin/codes/1/token", {"token": None})
    assert identify(admin)["state"] == "ok"
    r = admin.delete("/api/admin/codes/1", headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert identify(admin)["state"] == "ok"
    assert admin.get("/").status_code == 200
    upload(admin)


def test_marked_in_the_admin_lists_and_the_export(admin, guest, core):
    g = guest()
    host = sign_in(admin)["user"]
    users = admin.get("/api/admin/users").json()["users"]
    assert {u["id"]: u["is_host"] for u in users} == {host["id"]: True, user_of(core, g).id: False}
    assert admin.get(f"/api/admin/users/{host['id']}").json()["user"]["is_host"] is True
    rows = list(csv.DictReader(io.StringIO(users_csv(core.repos.users.list()).decode("utf-8-sig"))))
    assert list(rows[0]) == USER_COLUMNS
    assert {r["user"]: r["is_host"] for r in rows} == {
        host["name"]: "1",
        user_of(core, g).name: "0",
    }
