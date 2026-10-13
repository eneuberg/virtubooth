"""Content blockers vs. the RENDERED page (reusable: admin and INT import it).

The unit test (tests/unit/test_core_blockers.py) checks URLs and file names; this
checks what a blocker's element-hiding rules see: the live DOM, portals (sheets,
toasts) included, against the vendored cosmetic rules, plus the full lists when
`VB_BLOCKLISTS=<dir>` holds them (they are only read here, never downloaded; the
unit test downloads them). The join sheet's names must also avoid the cookie-notice
words.

    from ..guest.blockers import assert_survives_blockers
    page.goto(...)
    assert_survives_blockers(page, "admin live")
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

from playwright.sync_api import Page

from ...unit import blockerlists as bl
from ...unit.test_core_blockers import COOKIE_NOTICE_WORDS, vendored_lists

# read once at import: the shared clean_env fixture removes VB_* before each test
FULL_LISTS_DIR = os.environ.get("VB_BLOCKLISTS", "").strip()

# attributes cookie-notice rules key on
NAMED_ATTRS = ("class", "id", "data-testid", "aria-labelledby", "for", "name")


def _lists() -> list[tuple[str, str]]:
    lists = vendored_lists()
    if FULL_LISTS_DIR:
        folder = Path(FULL_LISTS_DIR)
        for f in sorted(folder.glob("*.txt")):
            lists.append((f.stem, f.read_text(encoding="utf-8", errors="replace")))
    return lists


@cache
def cosmetic_rules() -> bl.CosmeticRules:
    """The element-hiding rules, parsed once per run (the full lists take seconds)."""
    rules = bl.CosmeticRules()
    for name, text in _lists():
        rules.add_list(text, name)
    return rules


def hidden_by_blockers(elements: list[bl.El]) -> list[str]:
    """Elements a generic element-hiding rule would hide, as readable lines."""
    return [
        f"{el.describe()} <- {rule.source}: {rule.text}"
        for rule, el in cosmetic_rules().check(elements)
    ]


def rendered_elements(page: Page, origin: str) -> list[bl.El]:
    """The page's current DOM as blockerlists elements (portals included)."""
    html: str = page.evaluate("() => document.documentElement.outerHTML")
    root = bl.html_tree(html, origin)
    return list(root.walk())


def cosmetic_hits_on(page: Page, origin: str) -> list[str]:
    """Elements a generic element-hiding rule would hide, as readable lines."""
    return hidden_by_blockers(rendered_elements(page, origin))


def notice_word_hits(elements: list[bl.El], testid: str = "join") -> list[str]:
    """Names inside the element with `testid` that contain a cookie-notice word."""
    hits: list[str] = []
    roots = [el for el in elements if el.attrs.get("data-testid") == testid]
    for root in roots:
        for el in root.walk():
            for attr in NAMED_ATTRS:
                value = el.attrs.get(attr, "").lower()
                hits += [
                    f"{el.describe()} {attr}={value!r} has {w!r}"
                    for w in COOKIE_NOTICE_WORDS
                    if w in value
                ]
    return hits


def assert_survives_blockers(page: Page, label: str, *, join: bool = False) -> int:
    """Fails with the offending elements when a rule would hide one. With `join`,
    the join sheet must be on the page and pass the name check too. Returns the
    number of elements scanned (so callers can assert the page was not empty)."""
    elements = rendered_elements(page, label)
    hidden = hidden_by_blockers(elements)
    assert hidden == [], f"{label}: blockers would hide:\n" + "\n".join(hidden)
    if join:
        assert any(el.attrs.get("data-testid") == "join" for el in elements), (
            f"{label}: no join sheet"
        )
        dialog = [el for el in elements if el.attrs.get("role") == "dialog"]
        assert dialog, f"{label}: the join sheet has no role=dialog"
        words = notice_word_hits(elements)
        assert words == [], f"{label}: join sheet names:\n" + "\n".join(words)
    return len(elements)
