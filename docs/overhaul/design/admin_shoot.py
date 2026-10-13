"""Screenshots of the admin app against admin_seed_server.py (wave 2, AD).

    cd backend && uv run python ../docs/overhaul/design/admin_shoot.py OUT_DIR [names…] [--base URL]

Phone 390x844, landscape 844x390 and desktop 1440x900, Chromium. Prints the console
errors per shot (there should be none). Names: login live live-viewer manage manage-guests
user ban-sheet uploads instagram export audit (default: all).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

PASSWORD = "admin-admin-1"
VIEWPORTS = {
    "phone": {
        "viewport": {"width": 390, "height": 844},
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
    "small": {
        "viewport": {"width": 360, "height": 640},
        "device_scale_factor": 2,
        "is_mobile": True,
        "has_touch": True,
    },
    "desk": {"viewport": {"width": 1440, "height": 900}},
}


def settle(page: Page, ms: int = 700) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def login(page: Page, base: str) -> None:
    page.goto(base + "/admin/login")
    status = page.evaluate(
        """async (pw) => (await fetch('/api/admin/login', {method: 'POST',
            headers: {'Content-Type': 'application/json'}, body: JSON.stringify({password: pw})})).status""",
        PASSWORD,
    )
    assert status == 200


def first_user(page: Page, base: str, banned: bool = False) -> int:
    q = "?banned=true" if banned else "?limit=50"
    users = page.evaluate(f"async () => (await (await fetch('/api/admin/users{q}')).json()).users")
    users = [u for u in users if u["photo_count"] > 0] or users
    return int(users[0]["id"])


def shot_live(page: Page, base: str) -> None:
    page.goto(base + "/admin/live")
    settle(page)
    # hide a visible photo: the undo toast says "… ausgeblendet"
    page.locator("[data-testid=photo-card] [data-testid=toggle][data-action=hide]").nth(1).click()
    page.wait_for_timeout(900)


def shot_live_viewer(page: Page, base: str) -> None:
    page.goto(base + "/admin/live")
    settle(page)
    page.locator("[data-testid=photo-card] figure button").first.click()
    page.wait_for_timeout(800)


def shot_manage(page: Page, base: str) -> None:
    page.goto(base + "/admin/manage")
    settle(page)
    tiles = page.locator("[data-testid=photo-tile]")
    if page.viewport_size and page.viewport_size["width"] >= 1024:
        tiles.nth(1).click()
        for i in (1, 4, 9):
            tiles.nth(i).get_by_test_id("select").click(force=True)
    page.wait_for_timeout(700)


def shot_guests(page: Page, base: str) -> None:
    page.goto(base + "/admin/manage?tab=gaeste")
    settle(page)


def shot_user(page: Page, base: str) -> None:
    page.goto(base + f"/admin/user?id={first_user(page, base)}")
    settle(page)


def shot_ban(page: Page, base: str) -> None:
    shot_user(page, base)
    page.get_by_test_id("ban").click()
    page.wait_for_timeout(700)


def shot_uploads(page: Page, base: str) -> None:
    page.goto(base + "/admin/live")
    settle(page)
    page.get_by_test_id("uploads-chip").click()
    page.wait_for_timeout(900)


def shot_instagram(page: Page, base: str) -> None:
    page.goto(base + "/admin/manage?tab=instagram")
    settle(page)


def shot_export(page: Page, base: str) -> None:
    page.goto(base + "/admin/manage?tab=export")
    settle(page, 1500)


def shot_audit(page: Page, base: str) -> None:
    page.goto(base + "/admin/manage?tab=protokoll")
    settle(page)


def shot_login(page: Page, base: str) -> None:
    page.context.clear_cookies()
    page.goto(base + "/admin/login")
    settle(page)
    page.fill("#password", "falsch")
    page.get_by_role("button", name="Anmelden").click()
    page.wait_for_timeout(700)


SHOTS: dict[str, Callable[[Page, str], None]] = {
    "live": shot_live,
    "live-viewer": shot_live_viewer,
    "manage": shot_manage,
    "manage-guests": shot_guests,
    "user": shot_user,
    "ban-sheet": shot_ban,
    "uploads": shot_uploads,
    "instagram": shot_instagram,
    "export": shot_export,
    "audit": shot_audit,
    "login": shot_login,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("names", nargs="*")
    ap.add_argument("--base", default="http://127.0.0.1:8170")
    ap.add_argument("--viewports", default="phone,land,desk")
    ap.add_argument("--full", action="store_true", help="full-page screenshots")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = args.names or list(SHOTS)
    failed = False
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for vp in args.viewports.split(","):
            ctx = browser.new_context(**VIEWPORTS[vp])
            page = ctx.new_page()
            errors: list[str] = []
            page.on(
                "console", lambda m, out=errors: out.append(m.text) if m.type == "error" else None
            )
            page.on("pageerror", lambda e, out=errors: out.append(str(e)))
            login(page, args.base)
            for name in names:
                errors.clear()
                try:
                    if name == "login":
                        page.context.clear_cookies()
                    SHOTS[name](page, args.base)
                    page.screenshot(path=str(out / f"{name}-{vp}.png"), full_page=args.full)
                except Exception as exc:  # keep going, report
                    failed = True
                    print(f"FAIL {name}-{vp}: {exc}", file=sys.stderr)
                real = [e for e in errors if "401" not in e and "Failed to load resource" not in e]
                print(f"{name}-{vp}: {real if real else 'ok'}")
                if name == "login":
                    login(page, args.base)
            ctx.close()
        browser.close()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
