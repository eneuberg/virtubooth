"""Content blockers vs. virtubooth (docs/ARCHITECTURE.md, "Content blockers").

uBlock Origin, AdGuard, Brave Shields and iOS content blockers drop URLs that
look like ads or tracking, strip query parameters, and hide elements that look
like cookie banners. One dropped module stops every module on the page; a
hidden join dialog leaves the guest at a page that never starts. These tests
match every URL the app serves or requests (tests/blockerlists.py) and every
element its pages build against real filter rules:

- always: tests/fixtures/blocker_rules.txt, the rules that matter (see its header);
- with VB_BLOCKLISTS=<dir>: the full lists, downloaded into <dir> when missing,
  skipped when they can't be fetched. Keep <dir> out of git (.blocklists/ is
  ignored), e.g. `VB_BLOCKLISTS=.blocklists uv run pytest tests/test_core_blockers.py`.
"""

from __future__ import annotations

import os
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from virtubooth.extension import Extension, discover_extensions

from . import blockerlists as bl
from .conftest import PARTY_TOKEN

VENDORED = Path(__file__).parent / "fixtures" / "blocker_rules.txt"

# The lists uBO, AdGuard and Brave ship (on by default or one click away), the
# cookie-notice/annoyance lists, the German regional lists, and domain lists.
FULL_LISTS = {
    "easylist": "https://easylist.to/easylist/easylist.txt",
    "easyprivacy": "https://easylist.to/easylist/easyprivacy.txt",
    "easylist-germany": "https://easylist.to/easylistgermany/easylistgermany.txt",
    "ubo-filters": "https://ublockorigin.github.io/uAssetsCDN/filters/filters.min.txt",
    "ubo-privacy": "https://ublockorigin.github.io/uAssetsCDN/filters/privacy.min.txt",
    "ubo-badware": "https://ublockorigin.github.io/uAssetsCDN/filters/badware.min.txt",
    "ubo-unbreak": "https://ublockorigin.github.io/uAssetsCDN/filters/unbreak.min.txt",
    "ubo-quick-fixes": "https://ublockorigin.github.io/uAssetsCDN/filters/quick-fixes.min.txt",
    "ubo-annoyances": "https://ublockorigin.github.io/uAssetsCDN/filters/annoyances.min.txt",
    "ubo-annoyances-cookies": "https://ublockorigin.github.io/uAssetsCDN/filters/annoyances-cookies.txt",
    "ubo-url-tracking": "https://ublockorigin.github.io/uAssetsCDN/filters/privacy-removeparam.txt",
    "adguard-base": "https://filters.adtidy.org/extension/ublock/filters/2.txt",
    "adguard-tracking": "https://filters.adtidy.org/extension/ublock/filters/3.txt",
    "adguard-social": "https://filters.adtidy.org/extension/ublock/filters/4.txt",
    "adguard-german": "https://filters.adtidy.org/extension/ublock/filters/6.txt",
    "adguard-mobile": "https://filters.adtidy.org/extension/ublock/filters/11.txt",
    "adguard-url-tracking": "https://filters.adtidy.org/extension/ublock/filters/17.txt",
    "adguard-cookies": "https://filters.adtidy.org/extension/ublock/filters/18.txt",
    "adguard-popups": "https://filters.adtidy.org/extension/ublock/filters/19.txt",
    "adguard-other-annoyances": "https://filters.adtidy.org/extension/ublock/filters/21.txt",
    "fanboy-annoyance": "https://secure.fanboy.co.nz/fanboy-annoyance.txt",
    "fanboy-social": "https://easylist.to/easylist/fanboy-social.txt",
    "fanboy-cookiemonster": "https://secure.fanboy.co.nz/fanboy-cookiemonster.txt",
    "fanboy-mobile-notifications": "https://secure.fanboy.co.nz/fanboy-mobile-notifications.txt",
    "brave-firstparty": "https://raw.githubusercontent.com/brave/adblock-lists/master/brave-lists/brave-firstparty.txt",
    "brave-cookie-specific": "https://raw.githubusercontent.com/brave/adblock-lists/master/brave-lists/brave-cookie-specific.txt",
    "peter-lowe": "https://pgl.yoyo.org/adservers/serverlist.php?hostformat=hosts&showintro=1&mimetype=plaintext",
    "hagezi-pro": "https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/pro.txt",
}
TRACKING_WORDS = ("fingerprint", "track", "analytic", "telemetry", "beacon", "pixel", "advert", "/ads", "/ad/", "collect")
# what the join dialog every new guest must accept may not be called
COOKIE_NOTICE_WORDS = ("consent", "cookie", "gdpr", "banner", "notice", "modal", "backdrop", "privacy", "popup")


@pytest.fixture
def extensions() -> Sequence[Extension]:
    return discover_extensions()


@pytest.fixture
def requests_(app) -> list[bl.Request]:  # type: ignore[no-untyped-def]
    reqs = bl.app_requests(app, PARTY_TOKEN)
    assert len(reqs) > 80
    return reqs


@pytest.fixture
def elements(app) -> list[bl.El]:  # type: ignore[no-untyped-def]
    els = bl.ui_elements(app)
    assert len(els) > 500
    return els


def vendored_lists() -> list[tuple[str, str]]:
    """[(list title, rules)] from the vendored file."""
    out: list[tuple[str, list[str]]] = []
    for line in VENDORED.read_text(encoding="utf-8").splitlines():
        if line.startswith("! list: "):
            out.append((line[8:], []))
        elif out:
            out[-1][1].append(line)
    return [(name, "\n".join(lines)) for name, lines in out]


def network_hits(reqs: list[bl.Request], lists: list[tuple[str, str]]) -> list[str]:
    rules = bl.NetworkRules(r.url for r in reqs)
    for name, text in lists:
        rules.add_list(text, name)
    return [f"{r.method} {r.url} ({r.type}) <- {rule.source}: {rule.text}"
            for r in reqs for rule in rules.check(r)]


def cosmetic_hits(elements: list[bl.El], lists: list[tuple[str, str]]) -> list[str]:
    rules = bl.CosmeticRules()
    for name, text in lists:
        rules.add_list(text, name)
    return [f"{el.describe()} <- {rule.source}: {rule.text}" for rule, el in rules.check(elements)]


# ------------------------------------------------------------- always


def test_vendored_rules_still_catch_what_broke_the_app():
    """The matcher and the vendored rules are not vacuous: they block the old
    device script and hide cookie-banner-like markup."""
    lists = vendored_lists()
    old = bl.Request(bl.BASE + "/static/core/fingerprint.js", "script")
    hits = network_hits([old], lists)
    assert any("EasyPrivacy: /fingerprint.js^$domain=~github.com" in h for h in hits), hits
    assert any("AdGuard Tracking Protection: /fingerprint.js^" in h for h in hits), hits

    html, body = bl.new_document("synthetic")
    banner = bl.El("div", {"data-testid": "consent-banner"})
    app_root = bl.El("main", {"id": "app"})
    app_root.append(bl.El("div", {"class": "cookie"}))
    body.append(banner)
    body.append(app_root)
    hidden = cosmetic_hits(list(html.walk()), lists)
    assert any('[data-testid="consent-banner"]' in h for h in hidden), hidden
    assert any("#app > .cookie" in h for h in hidden), hidden


def test_app_urls_survive_vendored_rules(requests_):
    assert network_hits(requests_, vendored_lists()) == []


def test_ui_survives_vendored_cosmetic_rules(elements):
    assert cosmetic_hits(elements, vendored_lists()) == []


def test_join_dialog_avoids_cookie_notice_words(elements):
    roots = [e for e in elements if e.attrs.get("data-testid") == "join" and e.origin.endswith("core/vb.js")]
    assert len(roots) == 1, "the join dialog (askConsent in vb.js) was not found"
    dialog = list(roots[0].walk())
    assert any(e.attrs.get("role") == "dialog" for e in dialog)
    names = [v for e in dialog for k, v in e.attrs.items()
             if k in ("class", "id", "data-testid", "aria-labelledby", "for", "name")]
    bad = [n for n in names if any(w in n.lower() for w in COOKIE_NOTICE_WORDS)]
    assert bad == []


def test_url_paths_avoid_blocker_words(requests_):
    """Lists key on these words; a near miss today is a block after the next list update."""
    words = TRACKING_WORDS + COOKIE_NOTICE_WORDS
    bad = [r.url for r in requests_ if any(w in urlsplit(r.url).path.lower() for w in words)]
    assert bad == []


# ------------------------------------------------- full lists (opt-in)


@pytest.fixture(scope="module")
def full_lists() -> list[tuple[str, str]]:
    raw = os.environ.get("VB_BLOCKLISTS", "").strip()
    if not raw:
        pytest.skip("set VB_BLOCKLISTS=<dir> to check against the full filter lists")
    folder = Path(raw)
    folder.mkdir(parents=True, exist_ok=True)
    for name, url in FULL_LISTS.items():
        target = folder / f"{name}.txt"
        if target.exists():
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "virtubooth-tests"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                part = target.with_suffix(".part")
                part.write_bytes(resp.read())
                part.replace(target)
        except OSError:
            continue  # offline or moved: use what we have
    files = sorted(folder.glob("*.txt"))
    if not files:
        pytest.skip(f"no filter lists in {folder} and none could be downloaded")
    return [(f.stem, f.read_text(encoding="utf-8", errors="replace")) for f in files]


def test_app_urls_survive_full_lists(requests_, full_lists):
    assert network_hits(requests_, full_lists) == []


def test_ui_survives_full_lists(elements, full_lists):
    assert cosmetic_hits(elements, full_lists) == []
