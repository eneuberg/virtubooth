"""Load built pages in Chromium under the production CSP and fail on any console error.

Also scans the rendered DOM for blocker-prone class/id/test-id values and for React Aria
default class names (react-aria-*), which leak when a component misses `className`.
Screenshots go to OUT if given.

usage: python scripts/browser-check.py BASE_URL [OUT_DIR or ""] [path ...]
  e.g. python scripts/browser-check.py http://127.0.0.1:4310 shots / /admin/live /gate /x/nope /__ui
Needs Python Playwright (the backend's dev environment has it). Dev tool, not a test.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

WORDS = re.compile(r"consent|cookie|gdpr|banner|notice|modal|backdrop|privacy|popup|advert|fingerprint|track|beacon", re.I)
VIEWPORTS = {
    "phone": dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True),
    "desk": dict(viewport={"width": 1440, "height": 900}, device_scale_factor=1),
}
# guests' phones are not all German: the desktop run uses an English browser on purpose
LOCALES = {"phone": "de-DE", "desk": "en-US"}
SCAN = """() => {
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    for (const c of el.classList) out.push(['class', c]);
    if (el.id) out.push(['id', el.id]);
    const t = el.getAttribute('data-testid'); if (t) out.push(['testid', t]);
  }
  return out;
}"""


def main() -> int:
    base, out = sys.argv[1], (Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None)
    paths = sys.argv[3:] or ["/", "/admin/live", "/gate", "/nope"]
    if out:
        out.mkdir(parents=True, exist_ok=True)
    failures = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp_name, vp in VIEWPORTS.items():
            ctx = browser.new_context(**vp, locale=LOCALES[vp_name])
            for path in paths:
                page = ctx.new_page()
                errors: list[str] = []
                page.on("console", lambda m, e=errors: m.type == "error" and e.append(m.text))
                page.on("pageerror", lambda exc, e=errors: e.append(f"pageerror: {exc}"))
                page.goto(base + path)
                page.wait_for_load_state("networkidle")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)
                ready = page.evaluate("window.__vbReady === true")
                overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                bad = [
                    f"{k}={v}"
                    for k, v in page.evaluate(SCAN)
                    if WORDS.search(v) or (k == "class" and v.startswith("react-aria-"))
                ]
                # 404 page loads log "Failed to load resource: 404" for the document itself; ignore that one
                errs = [e for e in errors if "status of 404" not in e]
                ok = not errs and not bad and overflow <= 0
                failures += 0 if ok else 1
                print(f"{'ok  ' if ok else 'FAIL'} {vp_name:5} {path:16} ready={ready} xoverflow={overflow} errors={errs} names={sorted(set(bad))[:8]}")
                if out:
                    page.evaluate("async () => { for (let y = 0; y < document.body.scrollHeight; y += 600) { scrollTo(0, y); await new Promise(r => setTimeout(r, 40)); } scrollTo(0, 0); }")
                    page.wait_for_timeout(400)
                    slug = path.strip("/").replace("/", "_").replace("?", "_").replace("=", "-") or "root"
                    page.screenshot(path=str(out / f"{slug}-{vp_name}.png"), full_page=True)
                page.close()
            ctx.close()
        browser.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
