"""Screenshot the static design mockups (docs/overhaul/design/mockups/*.html).

usage: <python with playwright> shoot.py ROUND [name ...]
Writes shots/<ROUND>/<name>-<viewport>.png. Viewports per mockup come from VIEWPORTS below.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
VP = {
    "phone": {
        "viewport": {"width": 390, "height": 844},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
    "small": {
        "viewport": {"width": 360, "height": 640},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
    "land": {
        "viewport": {"width": 844, "height": 390},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
    "desk": {"viewport": {"width": 1440, "height": 900}, "device_scale_factor": 1},
}
VIEWPORTS = {
    "01-start": ["phone", "small", "land", "desk"],
    "02-beer": ["phone", "small", "land", "desk"],
    "03-booth": ["phone", "small", "land"],
    "03b-booth-countdown": ["phone"],
    "03c-booth-result": ["phone", "small", "land"],
    "04-live": ["phone", "small", "land"],
    "05-manage": ["desk"],
    "06-user": ["desk", "phone"],
    "07-uploads-sheet": ["phone", "desk"],
    "08-join": ["phone", "small", "land"],
    "09-gate": ["phone", "desk"],
    "09b-notfound": ["phone"],
}


def main() -> None:
    rnd = sys.argv[1]
    names = sys.argv[2:] or list(VIEWPORTS)
    out = HERE / "shots" / rnd
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name in names:
            for vp in VIEWPORTS[name]:
                ctx = browser.new_context(**VP[vp], locale="de-DE")
                page = ctx.new_page()
                errors: list[str] = []
                page.on(
                    "console", lambda m, errors=errors: m.type == "error" and errors.append(m.text)
                )
                page.goto((HERE / "mockups" / f"{name}.html").as_uri())
                page.wait_for_load_state("networkidle")
                page.evaluate("document.fonts.ready")
                page.screenshot(
                    path=str(out / f"{name}-{vp}.png"),
                    full_page=vp != "land" and name.startswith(("01", "06")),
                )
                if errors:
                    print(name, vp, "console errors:", errors)
                ctx.close()
        browser.close()
    print("done", out)


if __name__ == "__main__":
    main()
