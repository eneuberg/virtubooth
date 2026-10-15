"""Display names (PLAN-NIGHT N15): the guest sets one (PATCH /api/me), the
shown name everywhere others see the guest, the rules against impersonation,
and the admin's reset."""

from __future__ import annotations

import pytest

from virtubooth.core.errors import ApiError
from virtubooth.domain.models import shown_name
from virtubooth.services.identity import name_key, normalize_display_name

from ..conftest import JPEG, ORIGIN, jpeg


def set_name(client, name):
    return client.patch("/api/me", json={"display_name": name}, headers=ORIGIN)


def me(client) -> dict:
    r = client.post("/api/identify", json={}, headers=ORIGIN)
    assert r.status_code == 200, r.text
    user: dict = r.json()["user"]
    return user


# --------------------------------------------------------------- the rules


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("   ", None),
        ("  Anna   Banana ", "Anna Banana"),
        ("Ｆｒｅｄ", "Fred"),  # NFKC: full-width letters
        ("Jo", "Jo"),
        ("x" * 24, "x" * 24),
        ("Zoë 🎉", "Zoë 🎉"),
        ("a@b", "a@b"),  # only a LEADING „@“ is refused
    ],
)
def test_normalise(raw, expected):
    assert normalize_display_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("J", "Der Name braucht 2 bis 24 Zeichen."),
        ("x" * 25, "Der Name braucht 2 bis 24 Zeichen."),
        ("Anna‮anna", "Dieser Name geht leider nicht."),  # bidi override
        ("Ann⁦a", "Dieser Name geht leider nicht."),  # bidi isolate
        ("An​na", "Dieser Name geht leider nicht."),  # zero-width space
        ("An‍na", "Dieser Name geht leider nicht."),  # zero-width joiner
        ("An\x00na", "Dieser Name geht leider nicht."),  # control
        ("Anna\nBob", "Anna Bob"),  # newline: just whitespace, collapsed
        ("Anna", "Dieser Name geht leider nicht."),  # private use
        ("@anna", "Dieser Name geht leider nicht."),
        ("＠anna", "Dieser Name geht leider nicht."),  # full-width @ (NFKC → @)
        ("...", "Dieser Name geht leider nicht."),
    ],
)
def test_refused(raw, message):
    if message == "Anna Bob":
        assert normalize_display_name(raw) == "Anna Bob"
        return
    with pytest.raises(ApiError) as caught:
        normalize_display_name(raw)
    assert caught.value.code == "invalid_display_name"
    assert caught.value.message == message


def test_name_key_ignores_case_spaces_and_punctuation():
    assert name_key("Anna_B") == name_key(" anna b ") == name_key("@ANNA.b") == "annab"
    assert name_key("Verrückte Ente #3") == name_key("verrückte-ente 3")


def test_shown_name_order():
    assert shown_name("Fred", "fred.ig", "Ente #1") == "Fred"
    assert shown_name(None, "fred.ig", "Ente #1") == "@fred.ig"
    assert shown_name(None, None, "Ente #1") == "Ente #1"


# ------------------------------------------------------------------- API


def test_set_shown_and_reset(guest, core):
    g = guest()
    before = me(g)
    assert before["display_name"] is None and before["shown_name"] == before["name"]
    r = set_name(g, "  Party   Fred ")
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["display_name"] == user["shown_name"] == "Party Fred"
    assert user["name"] == before["name"]  # the pseudonym stays
    entry = core.repos.audit.list(limit=1)[0]
    assert entry.action == "user.display_name" and entry.actor.startswith("guest:")
    assert entry.details == {"display_name": "Party Fred", "previous": None}
    # back to the default: blank or null
    assert set_name(g, " ").json()["user"]["display_name"] is None
    assert set_name(g, None).json()["user"]["shown_name"] == before["name"]


def test_default_is_the_instagram_handle(guest):
    g = guest(instagram="fred.ig")
    assert me(g)["shown_name"] == "@fred.ig"
    assert set_name(g, "Fred").json()["user"]["shown_name"] == "Fred"


def test_patch_keeps_the_other_field(guest):
    g = guest(instagram="fred.ig")
    set_name(g, "Fred")
    # only display_name sent: the handle stays
    assert set_name(g, "Freddy").json()["user"]["instagram"] == "fred.ig"
    # only instagram sent: the display name stays
    r = g.patch("/api/me", json={"instagram": "other.ig"}, headers=ORIGIN)
    assert r.json()["user"]["display_name"] == "Freddy"
    assert r.json()["user"]["instagram"] == "other.ig"


def test_duplicates_are_taken(guest):
    anna = guest(instagram="anna.party", fp_n=1)
    bob = guest(fp_n=2)
    assert set_name(bob, "Bobby").status_code == 200
    carl = guest(fp_n=3)
    pseudonym = me(anna)["name"]
    for taken in ("Bobby", "bobby", "B o b b y", "bob_by", pseudonym, pseudonym.upper(),
                  "anna.party", "Anna Party", "@anna.party"[1:]):  # fmt: skip
        r = set_name(carl, taken)
        assert r.status_code == 409, taken
        assert r.json() == {
            "error": "display_name_taken",
            "message": "Dieser Name ist schon vergeben.",
        }
    # their own names are fine
    assert set_name(anna, "anna.party").status_code == 200
    assert set_name(bob, "BOBBY").status_code == 200
    assert set_name(anna, pseudonym).status_code == 200


@pytest.mark.parametrize("name", ["Admin", "host", "Gast-Geber", "MODERATOR", "Veranstalter",
                                  "virtu booth", "Testparty", "Test_Party"])  # fmt: skip
def test_reserved_names_and_the_event_name(guest, name):
    r = set_name(guest(), name)
    assert r.status_code == 400 and r.json()["error"] == "invalid_display_name", name
    assert r.json()["message"] == "Dieser Name geht leider nicht."


def test_banned_guest_cannot(guest, admin, core):
    g = guest()
    uid = core.repos.users.list()[0].id
    admin.post(f"/api/admin/users/{uid}/ban", json={}, headers=ORIGIN)
    assert set_name(g, "Fred").status_code == 403


def test_wall_and_admin_see_it(guest, admin, core):
    from virtubooth.extensions.wall.config import WallConfig
    from virtubooth.extensions.wall.feed import wall_photos

    g = guest(instagram="fred.ig")
    r = g.post("/api/x/demo/upload", content=jpeg(400, 300), headers=JPEG)
    assert r.status_code == 201
    photo = core.repos.photos.get(r.json()["photo"]["id"])
    config = WallConfig()

    class NoAnalysis:
        def summaries(self, ids):
            return {}

    enrichment = NoAnalysis()

    def author(cfg: WallConfig) -> str:
        p = core.repos.photos.get(photo.public_id)
        return wall_photos(core, cfg, enrichment, [p])[0].author  # type: ignore[arg-type]

    config.show_instagram = True
    assert author(config) == "@fred.ig"
    # the host hides handles on the wall: the default falls back to the pseudonym
    config.show_instagram = False
    assert author(config) == me(g)["name"]
    set_name(g, "Fred")
    assert author(config) == "Fred"

    uid = photo.user_id
    user = admin.get(f"/api/admin/users/{uid}").json()["user"]
    assert (user["display_name"], user["shown_name"]) == ("Fred", "Fred")
    assert user["name"] == me(g)["name"]
    assert admin.get("/api/admin/users", params={"search": "Fred"}).json()["users"][0]["id"] == uid


def test_admin_reset(guest, admin, core, published_events):
    g = guest()
    set_name(g, "Fred")
    uid = core.repos.users.list()[0].id
    r = admin.delete(f"/api/admin/users/{uid}/display-name", headers=ORIGIN)
    assert r.status_code == 200, r.text
    assert r.json()["changed"] is True
    assert r.json()["user"]["display_name"] is None
    assert me(g)["display_name"] is None
    entry = core.repos.audit.list(limit=1)[0]
    assert entry.action == "user.display_name_reset" and entry.actor.startswith("admin:")
    assert entry.details == {"previous": "Fred"}
    again = admin.delete(f"/api/admin/users/{uid}/display-name", headers=ORIGIN)
    assert again.json()["changed"] is False
    assert admin.delete("/api/admin/users/9999/display-name", headers=ORIGIN).status_code == 404
    # open walls hear about it like about a new handle
    assert ("user.instagram", {"id": uid, "instagram": None}) in published_events


@pytest.fixture
def published_events(core, monkeypatch) -> list:
    seen: list = []
    real = core.bus.publish

    def spy(type_, data):
        seen.append((type_, data))
        real(type_, data)

    monkeypatch.setattr(core.bus, "publish", spy)
    return seen
