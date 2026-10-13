"""Party access through QR codes: every access path of the gate and the access
cookie (`?t=` scans, current and stale cookies, cookies from before the codes,
forged cookies), the wrong-token limiter, and the attribution of scans and
joins to codes with the statistics that follow."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from virtubooth.core.security import Signer

from ..conftest import BASE_URL, JPEG, ORIGIN, PARTY_TOKEN, SECRET_KEY, accept_consent, jpeg

TOKEN_2 = "second-code-token-0002"
TOKEN_3 = "third-code-token-00003"
GATE_TEXT = "Scan den QR-Code"


@pytest.fixture
def codes(core):
    """Codes 2 and 3 next to the seeded code 1 (token PARTY_TOKEN)."""
    service = core.services.codes
    service.create(token=TOKEN_2, target="demo", note="Bar", actor="pytest")
    service.create(token=TOKEN_3, target="", note="", actor="pytest")
    return service


def scan(client: TestClient, token: str, path: str = "/") -> Any:
    return client.get(f"{path}?t={token}")


def scanned(client: TestClient, token: str) -> TestClient:
    r = scan(client, token)
    assert r.status_code == 303, r.text
    return client


def gated(client: TestClient, path: str = "/") -> bool:
    r = client.get(path)
    return r.status_code == 404 and GATE_TEXT in r.text


def page_ok(client: TestClient, path: str = "/") -> bool:
    return client.get(path).status_code == 200


def api_ok(client: TestClient) -> bool:
    r = client.post("/api/identify", json={}, headers=ORIGIN)
    if r.status_code == 404:
        assert r.json()["error"] == "scan_qr"
        return False
    assert r.status_code == 200, r.text
    return True


def join(client: TestClient, fp_n: int = 1) -> dict[str, Any]:
    return accept_consent(client, fp_n=fp_n)


def user_code(core, client: TestClient) -> int | None:
    public_id = core.signer.unsign("uid", client.cookies.get("vb_uid"))
    row = core.db.one("SELECT code_id FROM users WHERE public_id=?", (public_id,))
    return row[0]


def stats(core, code_id: int) -> dict[str, Any]:
    view = core.services.codes.view(code_id)
    return view.stats.model_dump()


def upload(client: TestClient) -> str:
    r = client.post("/api/x/demo/upload", content=jpeg(), headers=JPEG)
    assert r.status_code == 201, r.text
    photo_id: str = r.json()["photo"]["id"]
    return photo_id


def legacy_cookie(core, token: str = PARTY_TOKEN) -> str:
    """vb_access as the code before QR codes set it."""
    return core.signer.mac("access", token)


# ------------------------------------------------------------------- scans


def test_a_scan_of_any_active_code_opens_the_party(make_client, codes, core):
    c = make_client()
    r = scan(c, TOKEN_2, "/x/demo/")
    assert r.status_code == 303 and r.headers["location"] == "/x/demo/"
    cookie = c.cookies.get("vb_access")
    assert cookie.startswith("2.1.") and core.signer.unsign("access", cookie) == "2.1"
    assert "HttpOnly" in r.headers["set-cookie"]
    assert page_ok(c) and page_ok(c, "/x/demo/") and api_ok(c)
    for token in (PARTY_TOKEN, TOKEN_3):
        assert page_ok(scanned(make_client(), token))


def test_scans_are_counted_per_code(make_client, codes, core):
    a, b = make_client(), make_client()
    scanned(a, TOKEN_2)
    scanned(a, TOKEN_2)
    scanned(b, TOKEN_2)
    scanned(b, TOKEN_3)
    s2 = stats(core, 2)
    assert (s2["scans"], s2["people"], s2["not_joined"], s2["guests"]) == (3, 2, 2, 0)
    assert s2["first_scan_at"] <= s2["last_scan_at"]
    assert (stats(core, 3)["scans"], stats(core, 3)["people"]) == (1, 1)
    assert stats(core, 1)["scans"] == 0
    # the dashboard's "Gescannt" counts browsers, as before
    assert core.db.one("SELECT COUNT(*) FROM visitors")[0] == 2


@pytest.mark.parametrize(
    "token", ["definitely-not-the-token", "", "x" * 129, PARTY_TOKEN + "x", PARTY_TOKEN.upper()]
)
def test_a_wrong_token_gets_the_gate_and_no_cookie(make_client, codes, core, token):
    c = make_client()
    r = scan(c, token)
    assert r.status_code == 404 and GATE_TEXT in r.text
    assert "set-cookie" not in r.headers
    assert gated(c) and not api_ok(c)
    assert core.db.one("SELECT COUNT(*) FROM code_visitors")[0] == 0
    assert core.db.one("SELECT COUNT(*) FROM visitors")[0] == 0


def test_a_revoked_codes_token_gets_the_gate(make_client, codes):
    codes.revoke(2, actor="pytest")
    c = make_client()
    assert scan(c, TOKEN_2).status_code == 404
    assert "vb_access" not in c.cookies and gated(c)
    assert page_ok(scanned(make_client(), TOKEN_3))


def test_an_old_token_gets_the_gate_after_a_change(make_client, codes):
    new = codes.set_token(2, None, actor="pytest").token
    c = make_client()
    assert scan(c, TOKEN_2).status_code == 404 and gated(c)
    c = scanned(make_client(), new)
    assert c.cookies.get("vb_access").startswith("2.2.") and page_ok(c)


# ------------------------------------------- revoked or re-tokened codes


@pytest.mark.parametrize("change", ["revoke", "token"])
def test_joined_guests_keep_their_session(make_client, codes, core, change):
    guest = scanned(make_client(), TOKEN_2)
    join(guest)
    photo = upload(guest)
    if change == "revoke":
        codes.revoke(2, actor="pytest")
    else:
        codes.set_token(2, None, actor="pytest")
    assert page_ok(guest) and page_ok(guest, "/x/demo/")
    assert guest.post("/api/identify", json={}, headers=ORIGIN).json()["state"] == "ok"
    assert guest.get("/api/extensions").status_code == 200
    assert guest.get("/api/me/photos").status_code == 200
    assert (
        guest.patch("/api/me", json={"instagram": "still.here"}, headers=ORIGIN).status_code == 200
    )
    assert guest.get(f"/media/{photo}").status_code == 200
    upload(guest)
    # a second tab's join keeps the identity
    assert join(guest)["already_joined"] is True
    assert user_code(core, guest) == 2


@pytest.mark.parametrize("change", ["revoke", "token"])
def test_browsers_that_did_not_join_must_scan_again(make_client, codes, core, change):
    waiting = scanned(make_client(), TOKEN_2)
    assert page_ok(waiting) and api_ok(waiting)
    if change == "revoke":
        codes.revoke(2, actor="pytest")
    else:
        codes.set_token(2, None, actor="pytest")
    assert gated(waiting) and gated(waiting, "/x/demo/") and gated(waiting, "/nope")
    assert not api_ok(waiting)
    r = waiting.post("/api/join", json={"accept": True, "version": "1", "fp": {"hash": "a" * 64,
                     "components": {}}}, headers=ORIGIN)  # fmt: skip
    assert r.status_code == 404 and r.json()["error"] == "scan_qr"
    assert core.repos.users.list() == []
    # a valid code lets it in again (and counts for that code)
    scanned(waiting, TOKEN_3)
    assert page_ok(waiting) and waiting.cookies.get("vb_access").startswith("3.1.")
    join(waiting)
    assert user_code(core, waiting) == 3


def test_a_rescan_of_a_retokened_code_refreshes_the_cookie(make_client, codes):
    c = scanned(make_client(), TOKEN_2)
    new = codes.set_token(2, None, actor="pytest").token
    assert gated(c)
    scanned(c, new)
    assert page_ok(c) and c.cookies.get("vb_access").startswith("2.2.")


# ------------------------------------------------------------ attribution


def test_join_stores_the_code_and_never_changes_it(make_client, codes, core):
    guest = scanned(make_client(), TOKEN_2)
    assert join(guest)["already_joined"] is False
    assert user_code(core, guest) == 2
    # scanning another code later: counted there, the guest stays with code 2
    scanned(guest, TOKEN_3)
    assert join(guest)["already_joined"] is True
    assert user_code(core, guest) == 2
    assert stats(core, 3)["people"] == 1 and stats(core, 3)["guests"] == 0
    s2 = stats(core, 2)
    assert (s2["guests"], s2["not_joined"], s2["people"]) == (1, 0, 1)


def test_statistics_per_code(make_client, codes, core):
    anna = scanned(make_client(), TOKEN_2)
    join(anna, fp_n=1)
    ben = scanned(make_client(), TOKEN_2)
    join(ben, fp_n=2)
    scanned(make_client(), TOKEN_2)  # never joins
    photos = [upload(anna), upload(anna), upload(ben)]
    core.services.moderation.delete_photo(photos[0], actor="pytest")
    core.services.moderation.hide_photo(photos[1], actor="pytest")  # hidden still counts
    s = stats(core, 2)
    assert (s["scans"], s["people"], s["guests"], s["not_joined"]) == (3, 3, 2, 1)
    assert (s["photos"], s["active_now"]) == (2, 2)
    ben_id = core.signer.unsign("uid", ben.cookies.get("vb_uid"))
    user = core.repos.users.get_by_public_id(ben_id)
    core.services.moderation.ban_user(user.id, reason="test", actor="pytest")
    assert stats(core, 2)["active_now"] == 1
    with core.db.tx() as c:
        c.execute("UPDATE users SET last_seen_at='2020-01-01T00:00:00.000+00:00'")
    assert stats(core, 2)["active_now"] == 0
    assert stats(core, 3) == stats(core, 1) == {
        "scans": 0, "people": 0, "guests": 0, "not_joined": 0, "photos": 0, "active_now": 0,
        "first_scan_at": None, "last_scan_at": None,
    }  # fmt: skip


def test_admin_list_has_the_statistics(make_client, codes, admin):
    guest = scanned(make_client(), TOKEN_2)
    join(guest)
    upload(guest)
    by_id = {c["id"]: c for c in admin.get("/api/admin/codes").json()["codes"]}
    assert by_id[2]["stats"]["guests"] == 1 and by_id[2]["stats"]["photos"] == 1
    assert by_id[2]["stats"]["scans"] == 1 and by_id[1]["stats"]["guests"] == 0


# ------------------------------------------------------ cookies from before


def test_a_cookie_from_before_the_codes_still_works(make_client, codes, core):
    c = make_client()
    c.cookies.set("vb_access", legacy_cookie(core))
    assert page_ok(c) and api_ok(c)
    join(c)
    assert user_code(core, c) == 1
    stranger = make_client()
    stranger.cookies.set("vb_access", legacy_cookie(core, TOKEN_2))
    assert gated(stranger) and not api_ok(stranger)


@pytest.mark.parametrize("change", ["revoke", "token"])
def test_old_cookies_after_code_1_changed(make_client, codes, core, change):
    joined, waiting = make_client(), make_client()
    for c in (joined, waiting):
        c.cookies.set("vb_access", legacy_cookie(core))
    join(joined)
    if change == "revoke":
        codes.revoke(1, actor="pytest")
    else:
        codes.set_token(1, None, actor="pytest")
    assert page_ok(joined) and api_ok(joined)
    assert gated(waiting) and not api_ok(waiting)


def test_old_cookies_need_the_seeded_token_once_code_1_has_a_new_one(make_client, codes, core):
    """After code 1 got a new token, a cookie from before is recognised with
    the help of VB_PARTY_TOKEN; once that changed too, it can't be checked."""
    joined = make_client()
    joined.cookies.set("vb_access", legacy_cookie(core))
    join(joined)
    codes.set_token(1, None, actor="pytest")
    assert page_ok(joined)
    core.settings = core.settings.replace(party_token="a-completely-new-token-xyz")
    assert gated(joined) and not api_ok(joined)
    core.settings = core.settings.replace(party_token=None)
    assert gated(joined)


# ------------------------------------------------------------ forged cookies


def test_forged_and_foreign_cookies_get_the_gate(make_client, codes, core):
    other = Signer("another-secret-key-0123456789abcdef0123")
    assert other.sign("access", "2.1") != core.signer.sign("access", "2.1")
    good = core.signer.sign("access", "2.1")
    forged = [
        "2.1.forgedsignature",
        good[:-1] + ("A" if good[-1] != "A" else "B"),
        other.sign("access", "2.1"),
        other.mac("access", PARTY_TOKEN),
        core.signer.sign("access", "99.1"),  # no such code
        core.signer.sign("access", "2"),
        core.signer.sign("access", "2.x"),
        core.signer.sign("access", "-2.1"),
        core.signer.sign("access", " 2.1"),
        core.signer.sign("vid", "2.1"),  # another purpose
        core.signer.sign("uid", "2.1"),
        core.signer.mac("vid", PARTY_TOKEN),
        core.signer.mac("access", TOKEN_2),  # old style, but not code 1's token
        PARTY_TOKEN,
        "",
        "." * 300,
    ]
    for value in forged:
        c = make_client()
        c.cookies.set("vb_access", value)
        assert gated(c) and not api_ok(c), value
    c = make_client()
    c.cookies.set("vb_access", good)
    assert page_ok(c)
    assert Signer(SECRET_KEY).sign("access", "2.1") == good


def test_a_stale_cookie_without_a_guest_cookie_gets_the_gate(make_client, codes, core):
    guest = scanned(make_client(), TOKEN_2)
    join(guest)
    codes.revoke(2, actor="pytest")
    guest.cookies.delete("vb_uid")
    assert gated(guest)
    guest.cookies.set("vb_uid", "forged.uid")
    assert gated(guest)


# ------------------------------------------------------- the failure limit


def test_wrong_tokens_are_limited_per_address(make_client, app, codes, core):
    c = make_client()
    for _ in range(60):
        assert scan(c, "wrong-token-guessing-00").status_code == 404
    # over the limit even the right token gets the gate, unchecked
    r = scan(c, TOKEN_2)
    assert r.status_code == 404 and "set-cookie" not in r.headers
    assert core.db.one("SELECT COUNT(*) FROM code_visitors")[0] == 0
    # another address is not affected
    with TestClient(app, base_url=BASE_URL, follow_redirects=False, client=("10.0.0.9", 4000)) as o:
        assert scan(o, TOKEN_2).status_code == 303
    core.limits.token_fail_ip.reset()
    assert scan(c, TOKEN_2).status_code == 303


def test_valid_scans_do_not_use_the_failure_budget(make_client, codes, core):
    c = make_client()
    for _ in range(70):
        assert scan(c, TOKEN_2).status_code == 303
    for _ in range(59):
        assert scan(c, "wrong-token-guessing-00").status_code == 404
    assert scan(c, TOKEN_3).status_code == 303


def test_ipv6_neighbours_share_the_failure_budget(app, codes):
    def client(ip: str) -> TestClient:
        return TestClient(app, base_url=BASE_URL, follow_redirects=False, client=(ip, 4000))

    with client("2001:db8:1:2::1") as a, client("2001:db8:1:2::ffff") as b:
        for _ in range(60):
            scan(a, "wrong-token-guessing-00")
        assert scan(b, TOKEN_2).status_code == 404
    with client("2001:db8:1:3::1") as other:
        assert scan(other, TOKEN_2).status_code == 303
