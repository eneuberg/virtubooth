"""Content blockers vs. virtubooth (docs/ARCHITECTURE.md, "Content blockers").

uBlock Origin, AdGuard, Brave Shields and iOS content blockers drop URLs that
look like ads or tracking, strip query parameters, and hide elements that look
like cookie banners. One dropped module stops every module on the page; a
hidden join dialog leaves the guest at a page that never starts. These tests
match every URL the app serves or requests (tests/unit/blockerlists.py) against
real filter rules: the API routes, pages, media URLs and the files of the built
frontend (the stub build, plus frontend/dist when it exists).

The frontend's own files, by how they reach a browser:

- `frontend/public/*` and the HTML entries ship under their names: they must pass
  the rules and the name heuristic (FILE_NAME_RE), with or without a build.
- `frontend/src/**` never ships under its name: Vite bundles and hashes it into
  neutral `a-`/`c-`/`e-` names (scripts/check-names.mjs fails the build otherwise),
  and those are checked above with the heuristic. Only `vite dev` serves sources by
  path (`/src/sdk/upload.ts`), so a source path matters only when a real rule would
  drop it there; the heuristic does not apply. (`upload.ts` trips the heuristic,
  "ad." at the end of "upload", but matches no rule in any list: it keeps its name.)

The element checks (cosmetic rules, the join dialog's names) run on the rendered
DOM in the e2e suite (tests/e2e/guest/blockers.py: every main screen of the guest
app, the activities and the admin).

Rule sources:

- always: tests/fixtures/blocker_rules.txt, the rules that matter (see its header);
- with VB_BLOCKLISTS=<dir>: the full lists, downloaded into <dir> when missing,
  skipped when they can't be fetched. Keep <dir> out of git (.blocklists/ is
  ignored), e.g. `VB_BLOCKLISTS=.blocklists uv run pytest tests/unit/test_core_blockers.py`.
"""

from __future__ import annotations

import os
import re
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from virtubooth.extensions.sdk import Extension, discover_extensions
from virtubooth.settings import DEFAULT_WEB_DIR, REPO_ROOT

from ..conftest import FIXTURES, PARTY_TOKEN
from . import blockerlists as bl

VENDORED = FIXTURES / "blocker_rules.txt"
# the real build, when there is one: its file names must pass too
BUILT = [DEFAULT_WEB_DIR] if DEFAULT_WEB_DIR.is_dir() else []
FRONTEND = REPO_ROOT / "frontend"
# the HTML entries (vite.config.ts); served under their routes, but their names ship
ENTRIES = ("index.html", "admin.html", "gate.html")
# what a served file may not be called (hashes included: "…ad.js" fails)
FILE_NAME_RE = re.compile(
    r"fingerprint|track|analytic|telemetry|beacon|pixel|advert|banner|consent|cookie|gdpr|ads?[-_./]",
    re.I,
)

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
TRACKING_WORDS = (
    "fingerprint",
    "track",
    "analytic",
    "telemetry",
    "beacon",
    "pixel",
    "advert",
    "/ads",
    "/ad/",
    "collect",
)
# what the join dialog every new guest must accept may not be called
COOKIE_NOTICE_WORDS = (
    "consent",
    "cookie",
    "gdpr",
    "banner",
    "notice",
    "modal",
    "backdrop",
    "privacy",
    "popup",
)


@pytest.fixture
def extensions() -> Sequence[Extension]:
    return discover_extensions()


@pytest.fixture
def requests_(app) -> list[bl.Request]:  # type: ignore[no-untyped-def]
    reqs = bl.app_requests(app, PARTY_TOKEN, web_dirs=BUILT)
    assert len(reqs) > 80
    # every API route is in there
    urls = {r.url.split("?")[0] for r in reqs}
    for path, _ in bl._routes(app.routes):
        if path.startswith("/api/") and "{" not in path:
            assert bl.BASE + path in urls, path
    return reqs


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
    return [
        f"{r.method} {r.url} ({r.type}) <- {rule.source}: {rule.text}"
        for r in reqs
        for rule in rules.check(r)
    ]


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
                # one name per process: xdist workers may download the same list at once
                part = target.with_suffix(f".{os.getpid()}.part")
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


def test_served_file_names_avoid_blocker_keywords(app):
    """File names of the build (hashed bundles included) vs the words lists key on."""
    roots = [app.state.core.web.root, *BUILT]
    names = [url for root in roots for url, _ in bl.served_files(root)]
    assert names, "no served files found"
    bad = [n for n in names if FILE_NAME_RE.search(n.rsplit("/", 1)[-1])]
    assert bad == []


# ------------------------------------------- the frontend's own files


def frontend_public() -> list[bl.Request]:
    """frontend/public/* as served from the site root (they keep their names)."""
    folder = FRONTEND / "public"
    if not folder.is_dir():
        pytest.skip("no frontend/ next to the backend")
    return [
        bl.Request(
            f"{bl.BASE}/{f.relative_to(folder).as_posix()}", bl.ASSET_TYPES.get(f.suffix, "other")
        )
        for f in sorted(folder.rglob("*"))
        if f.is_file()
    ]


def frontend_sources() -> list[bl.Request]:
    """frontend/src/** as `vite dev` serves it (by path; modules load as scripts)."""
    folder = FRONTEND / "src"
    if not folder.is_dir():
        pytest.skip("no frontend/ next to the backend")
    out = []
    for f in sorted(folder.rglob("*")):
        if not f.is_file():
            continue
        typ = "script" if f.suffix in (".ts", ".tsx") else bl.ASSET_TYPES.get(f.suffix, "other")
        out.append(bl.Request(f"{bl.BASE}/{f.relative_to(FRONTEND).as_posix()}", typ))
    assert len(out) > 100
    return out


def test_public_files_and_entries_avoid_blocker_keywords():
    """They ship under their names: rules and the name heuristic, no build needed."""
    public = frontend_public()
    names = [r.url.rsplit("/", 1)[-1] for r in public] + list(ENTRIES)
    assert "boot-check.js" in names
    for entry in ENTRIES:
        assert (FRONTEND / entry).is_file(), entry
    assert [n for n in names if FILE_NAME_RE.search(n)] == []
    words = TRACKING_WORDS + COOKIE_NOTICE_WORDS
    assert [n for n in names if any(w in f"/{n.lower()}" for w in words)] == []
    assert network_hits(public, vendored_lists()) == []


def test_source_paths_survive_vendored_rules():
    """Sources ship hashed; only the dev server serves them by path. No rule may drop one
    there (the name heuristic is for shipped names, see the module docstring)."""
    assert network_hits(frontend_sources(), vendored_lists()) == []


def test_public_files_and_sources_survive_full_lists(full_lists):
    assert network_hits(frontend_public() + frontend_sources(), full_lists) == []
