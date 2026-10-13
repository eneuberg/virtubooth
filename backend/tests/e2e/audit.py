"""One pass over a screen: content blockers, leaked React Aria classes, and axe.

    audit = Audit()
    page.goto(...)
    audit.check(page, "start")          # collects, never stops the walk
    ...
    audit.assert_clean()                # fails with everything found, screen by screen

- **Blockers:** the rendered DOM (portals included) against the cosmetic rules
  (guest/blockers.py: the vendored rules, plus the full lists with VB_BLOCKLISTS).
- **React Aria default classes** (`react-aria-*`): a component without `className`
  leaks them (DESIGN.md §1, round 4); they are unstyled and unreviewed names.
- **axe** (axe-playwright-python 0.1.8, which bundles axe-core 4.12.1): WCAG 2.x A/AA
  and best practices. Serious and critical findings fail; moderate and minor ones are
  only reported (`VB_AXE_REPORT=<file>` appends one JSON line per screen).

axe is injected with `page.evaluate()`: Playwright evaluates through the browser's
debugging protocol, which the page's CSP does not govern, so the scans run in the
normal contexts under the production CSP (no `bypass_csp`), and every test still ends
with zero console errors. (`add_script_tag(content=…)` would be an inline script,
which `script-src 'self'` refuses.)

`only=` limits axe to one element (a countdown that is over in three seconds).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page

from .conftest import BROWSER_NAME
from .guest.blockers import hidden_by_blockers, rendered_elements

# read once at import: the shared clean_env fixture removes VB_* before each test
REPORT = os.environ.get("VB_AXE_REPORT", "").strip()
FAILING = ("serious", "critical")

_AXE = Axe()


def axe_violations(page: Page, only: str | None = None) -> list[dict[str, Any]]:
    """axe's violations on the page (or inside the element `only` selects)."""
    context = {"include": [[only]]} if only else None
    result = _AXE.run(page, context=context, options={"resultTypes": ["violations"]})
    violations: list[dict[str, Any]] = result.response["violations"]
    return violations


@dataclass
class Audit:
    """Collects findings over a walk through screens (see the module docstring)."""

    area: str = ""
    problems: list[str] = field(default_factory=list)
    screens: int = 0

    def check(self, page: Page, label: str, *, only: str | None = None) -> None:
        self.screens += 1
        name = f"{self.area} {label}".strip()
        # the DOM first: it is a snapshot, axe may take a moment
        elements = rendered_elements(page, name)
        hidden = hidden_by_blockers(elements)
        leaked = sorted(
            {
                c
                for el in elements
                for c in el.attrs.get("class", "").split()
                if c.startswith("react-aria-")
            }
        )
        violations = axe_violations(page, only)
        for line in hidden:
            self.problems.append(f"[{name}] blockers would hide {line}")
        if leaked:
            self.problems.append(f"[{name}] React Aria default classes: {leaked}")
        for v in violations:
            if v.get("impact") in FAILING:
                targets = [" ".join(map(str, n["target"])) for n in v["nodes"]][:5]
                self.problems.append(f"[{name}] axe {v['impact']} {v['id']}: {v['help']} {targets}")
        if REPORT:
            entry = {
                "browser": BROWSER_NAME,
                "screen": name,
                "elements": len(elements),
                "violations": [
                    {
                        "id": v["id"],
                        "impact": v.get("impact"),
                        "nodes": len(v["nodes"]),
                        "targets": [" ".join(map(str, n["target"])) for n in v["nodes"]][:5],
                    }
                    for v in violations
                ],
            }
            with Path(REPORT).open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def assert_clean(self) -> None:
        assert self.screens > 0, "no screen was checked"
        assert self.problems == [], f"{self.area}: {len(self.problems)} problem(s):\n" + "\n".join(
            self.problems
        )
