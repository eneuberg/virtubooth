"""End-to-end smoke test of a running virtubooth over HTTP.

It joins as a guest, uploads photos and runs one export job of each kind, so
point it only at a throwaway instance (scripts/docker-smoke.sh starts one),
never at a real party.

    uv run --project backend python scripts/smoke.py \
        --url http://127.0.0.1:8180 --env-file /path/to/test.env [--screenshots DIR]

The env file is what `virtubooth gen-env` prints (VB_PARTY_TOKEN and
VB_ADMIN_PASSWORD are read from it). Needs Pillow (backend dependency) and, for
--screenshots, Playwright's Chromium (`uv run playwright install chromium`).
Exits 1 on the first failed check.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from email.message import Message
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

from PIL import Image, ImageDraw

PHOTO_SIZE = (1080, 1440)
EXPORT_TIMEOUT_S = 180


class SmokeError(AssertionError):
    pass


def expect(condition: object, message: str) -> None:
    if not condition:
        raise SmokeError(message)


def ok(message: str) -> None:
    print(f"  ok  {message}", flush=True)


@dataclass
class Res:
    status: int
    headers: Message
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)

    def header(self, name: str) -> str:
        return self.headers.get(name) or ""

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class Client:
    """One browser-like client: its own cookies, never follows redirects."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect()
        )

    def cookie(self, name: str) -> str | None:
        return next((c.value for c in self.jar if c.name == name), None)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
    ) -> Res:
        h = {"Accept": "*/*"}
        if method not in ("GET", "HEAD"):
            h["Origin"] = self.base  # the CSRF origin check
        if json_body is not None:
            data = json.dumps(json_body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.opener.open(req, timeout=timeout) as r:
                return Res(r.status, r.headers, r.read())
        except HTTPError as e:  # 3xx (not followed), 4xx, 5xx
            return Res(e.code, e.headers, e.read())

    def get(self, path: str, **kw: Any) -> Res:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Res:
        return self.request("POST", path, **kw)


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip("'\"")
    return env


def jpeg(color: tuple[int, int, int]) -> bytes:
    img = Image.new("RGB", PHOTO_SIZE, color)
    draw = ImageDraw.Draw(img)
    draw.ellipse((340, 300, 740, 1140), fill=(250, 200, 60), outline=(255, 255, 255), width=12)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def wait_healthy(base: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=3) as r:
                if r.status == 200:
                    return
        except (URLError, OSError, HTTPError):
            pass
        if time.monotonic() > deadline:
            raise SmokeError(f"{base}/healthz did not answer within {timeout:.0f} s")
        time.sleep(0.5)


# ------------------------------------------------------------------- checks


def check_pages(base: str, token: str) -> Client:
    print("pages and assets")
    anon = Client(base)
    res = anon.get("/healthz")
    expect(res.status == 200 and res.json() == {"ok": True}, f"/healthz: {res.status} {res.body!r}")
    ok("/healthz is 200 {ok: true}")

    res = anon.get("/")
    csp = res.header("Content-Security-Policy")
    expect(res.status == 404, f"/ without access: {res.status}")
    expect(res.header("X-VB-Page") == "gate", "gate page header missing")
    expect("Scan den QR-Code" in res.text(), "gate text missing")
    ok("/ without the token: 404 gate page")
    for part in ("script-src 'self'", "style-src 'self'", "frame-ancestors 'none'"):
        expect(part in csp, f"CSP lacks {part!r}: {csp!r}")
    expect(res.header("X-Frame-Options") == "DENY", "X-Frame-Options missing")
    expect(res.header("Referrer-Policy") == "no-referrer", "Referrer-Policy missing")
    ok("strict CSP, X-Frame-Options, Referrer-Policy")
    res = anon.get("/api/extensions")
    expect(
        res.status == 404 and res.json()["error"] == "scan_qr", f"API without access: {res.status}"
    )
    ok("/api/* without the token: 404 scan_qr")

    guest = Client(base)
    res = guest.get(f"/?t={token}")
    expect(res.status == 303, f"/?t=: {res.status}")
    expect(res.header("Location") == "/", f"/?t= redirects to {res.header('Location')!r}")
    expect(guest.cookie("vb_access"), "no vb_access cookie after the token entry")
    ok("/?t=<token>: 303 to / with the vb_access cookie")
    expect(Client(base).get("/?t=wrong-token-0123456789").status == 404, "a wrong token got in")
    ok("/?t=<wrong>: 404")

    res = guest.get("/", headers={"Accept": "text/html"})
    html = res.text()
    expect(res.status == 200, f"/ with access: {res.status}")
    expect(res.header("Content-Type").startswith("text/html"), "index is not HTML")
    expect("no-cache" in res.header("Cache-Control"), "HTML must be no-cache")
    expect('<script src="/boot-check.js" defer' in html, "boot-check.js missing")
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', html)
    expect(
        any(re.fullmatch(r"/assets/e-[0-9a-f]+\.js", a) for a in assets), "no hashed entry script"
    )
    expect(any(a.endswith(".css") for a in assets), "no stylesheet")
    ok(f"/ with access: 200 index.html with {len(assets)} hashed assets")

    for asset in assets:
        res = guest.get(asset)
        expect(res.status == 200 and res.body, f"{asset}: {res.status}")
        cache = res.header("Cache-Control")
        expect("immutable" in cache and "max-age=31536000" in cache, f"{asset}: {cache!r}")
    ok("every referenced asset is 200 and immutable")

    script = next(a for a in assets if a.endswith(".js"))
    res = guest.get(script, headers={"Accept-Encoding": "br, gzip"})
    expect(
        res.header("Content-Encoding") == "br", f"br not served: {res.header('Content-Encoding')!r}"
    )
    expect("javascript" in res.header("Content-Type"), "br answer lost the JS content type")
    expect("Accept-Encoding" in res.header("Vary"), "Vary: Accept-Encoding missing")
    res = guest.get(script, headers={"Accept-Encoding": "gzip"})
    expect(res.header("Content-Encoding") == "gzip", "gzip not served")
    expect(guest.get(script + ".br").status == 404, "the .br URL itself must be 404")
    ok("Accept-Encoding: br serves the .br sibling (gzip too), Vary set")
    expect(guest.get("/.vite/manifest.json").status == 404, "the Vite manifest is served")
    ok("/.vite/manifest.json is not served")

    for path in ("/x/beer/", "/x/booth/"):
        res = guest.get(path)
        expect(res.status == 200 and "boot-check.js" in res.text(), f"{path}: {res.status}")
    res = guest.get("/x/nope/")
    expect(res.status == 404 and res.header("X-VB-Page") == "notfound", f"/x/nope/: {res.status}")
    ok("/x/beer/ and /x/booth/ are 200, an unknown activity is the 404 page")

    res = anon.get("/admin/login")
    expect(res.status == 200 and "/assets/e-" in res.text(), f"/admin/login: {res.status}")
    ok("/admin/login is 200 (admin.html)")
    res = anon.get("/admin/live")
    expect(res.status == 303, f"/admin/live without a session: {res.status}")
    expect(res.header("Location") == "/admin/login?next=/admin/live", res.header("Location"))
    ok("/admin/live without a session: 303 to the login with next")
    return guest


def check_guest(guest: Client) -> list[dict[str, Any]]:
    print("guest: join and upload")
    fp = {"hash": "5a" * 16, "components": {"smoke": True}}
    res = guest.post("/api/identify", json_body={"fp": fp})
    expect(res.status == 200, f"identify: {res.status} {res.body!r}")
    ident = res.json()
    expect(ident["state"] == "needs_consent", f"identify state {ident['state']!r}")
    res = guest.post(
        "/api/join",
        json_body={
            "accept": True,
            "version": ident["consent"]["version"],
            "instagram": "smoke.test",
            "fp": fp,
        },
    )
    expect(res.status == 201, f"join: {res.status} {res.body!r}")
    user = res.json()["user"]
    ok(f"joined as {user['name']!r} (@{user['instagram']})")
    res = guest.request(
        "POST",
        "/api/join",
        json_body={"accept": True},
        headers={"Origin": "https://evil.example.com"},
    )
    expect(res.status == 403 and res.json()["error"] == "bad_origin", f"CSRF: {res.status}")
    ok("a foreign Origin is refused (403 bad_origin)")

    filters = guest.get("/api/x/booth/filters").json()["filters"]
    expect(len(filters) >= 1, "no Fotobox filters")
    photos = []
    for ext, meta, color in (
        ("beer", {"vessel": "bottle", "facing": "environment"}, (120, 60, 20)),
        ("booth", {"filter": filters[0]["id"], "facing": "user"}, (40, 40, 90)),
    ):
        res = guest.post(
            f"/api/x/{ext}/upload",
            data=jpeg(color),
            headers={
                "Content-Type": "image/jpeg",
                "X-VB-Meta": urllib.parse.quote(json.dumps(meta)),
            },
        )
        expect(res.status == 201, f"{ext} upload: {res.status} {res.body!r}")
        body = res.json()
        photos.append(body["photo"])
        extra = {k: v for k, v in body.items() if k != "photo"}
        ok(f"{ext} upload: 201, photo {body['photo']['id']} {extra}")

    mine = guest.get("/api/me/photos").json()["photos"]
    expect({p["id"] for p in mine} == {p["id"] for p in photos}, f"/api/me/photos: {mine}")
    res = guest.get(photos[0]["url"])
    expect(res.status == 200 and res.header("Content-Type") == "image/jpeg", f"media: {res.status}")
    with Image.open(io.BytesIO(res.body)) as img:
        expect(img.size == PHOTO_SIZE, f"stored photo is {img.size}")
    ok("'Deine Bilder' lists both; the photo is served (1080x1440 JPEG)")
    return photos


def check_admin(base: str, password: str, photos: list[dict[str, Any]]) -> None:
    print("admin: login, events, export jobs")
    admin = Client(base)
    res = admin.post("/api/admin/login", json_body={"password": "wrong-password-123"})
    expect(res.status == 401, f"wrong password: {res.status}")
    res = admin.post("/api/admin/login", json_body={"password": password})
    expect(res.status == 200 and admin.cookie("vb_admin"), f"login: {res.status} {res.body!r}")
    ok("admin login (a wrong password is 401)")
    res = admin.get("/admin/live")
    expect(res.status == 200 and "/assets/e-" in res.text(), f"/admin/live: {res.status}")
    res = admin.get("/api/admin/photos")
    listed = {p["id"] for p in res.json()["photos"]}
    expect({p["id"] for p in photos} <= listed, "the admin does not see the uploads")
    expect(res.header("X-VB-Event-Id"), "X-VB-Event-Id header missing")
    ok("/admin/live is 200; the admin sees both photos")

    # the event stream answers through the container (first line: retry)
    req = urllib.request.Request(
        base + "/api/admin/events", headers={"Accept": "text/event-stream"}
    )
    with admin.opener.open(req, timeout=10) as stream:
        expect("text/event-stream" in stream.headers.get("Content-Type", ""), "SSE content type")
        first = stream.readline().decode().strip()
    expect(first == "retry: 3000", f"SSE starts with {first!r}")
    ok("the admin event stream opens (text/event-stream)")

    overview = admin.get("/api/admin/exports").json()
    expect(overview["ffmpeg"] is True, "the image has no ffmpeg (timelapse cannot run)")
    ok("exports: ffmpeg is available")
    requests = {
        "archive": {"include_hidden": True, "include_db": True},
        "timelapse": {"extension": "beer", "fps": 12},
        "qr": {"base_url": base},
    }
    jobs: dict[str, str] = {}
    for kind, options in requests.items():
        res = admin.post("/api/admin/exports", json_body={"kind": kind, "options": options})
        expect(res.status == 202, f"{kind} export: {res.status} {res.body!r}")
        jobs[kind] = res.json()["job"]["id"]
    ok("three export jobs queued (202)")

    deadline = time.monotonic() + EXPORT_TIMEOUT_S
    while True:
        state = {j["id"]: j for j in admin.get("/api/admin/exports").json()["jobs"]}
        pending = [k for k, i in jobs.items() if state[i]["status"] in ("queued", "running")]
        if not pending:
            break
        expect(time.monotonic() < deadline, f"exports still pending: {pending}")
        time.sleep(1)
    for kind, job_id in jobs.items():
        job = state[job_id]
        expect(job["status"] == "done", f"{kind} export {job['status']}: {job['error']}")
        res = admin.get(job["download_url"])
        expect(res.status == 200, f"{kind} download: {res.status}")
        expect(
            len(res.body) == job["bytes"], f"{kind}: {len(res.body)} bytes, job says {job['bytes']}"
        )
        expect("attachment" in res.header("Content-Disposition"), f"{kind}: not an attachment")
        if kind == "timelapse":
            expect(res.header("Content-Type") == "video/mp4", res.header("Content-Type"))
            expect(res.body[4:8] == b"ftyp", "the timelapse is not an MP4")
        else:
            names = zipfile.ZipFile(io.BytesIO(res.body)).namelist()
            want = ("manifest.json", "virtubooth.db") if kind == "archive" else ("qr-sheet.html",)
            for name in want:
                expect(any(n.endswith("/" + name) for n in names), f"{kind} zip lacks {name}")
        ok(f"{kind} export done and downloaded: {job['file_name']} ({job['bytes']:,} bytes)")


def take_screenshots(base: str, token: str, password: str, out: Path) -> None:
    print("browser: screenshots (Chromium)")
    from playwright.sync_api import Page, sync_playwright

    out.mkdir(parents=True, exist_ok=True)

    def ready(page: Page) -> None:
        deadline = time.monotonic() + 15
        while not page.evaluate("() => window.__vbReady === true"):
            expect(time.monotonic() < deadline, f"{page.url}: the app did not boot")
            page.wait_for_timeout(50)

    def watch(page: Page) -> list[str]:
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        return errors

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        phone = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
            has_touch=True,
            locale="de-DE",
        )
        page = phone.new_page()
        errors = watch(page)
        page.goto(f"{base}/?t={token}")
        ready(page)
        page.locator("[data-testid=join] button[type=submit]").click()
        page.locator("[data-testid=join]").wait_for(state="detached")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)  # the develop animation of the cards
        page.screenshot(path=str(out / "start-390.png"))
        expect(not errors, f"Start: console errors {errors}")
        ok(f"Start page (phone): {out / 'start-390.png'}")
        phone.close()

        desk = browser.new_context(viewport={"width": 1440, "height": 900}, locale="de-DE")
        page = desk.new_page()
        errors = watch(page)
        page.goto(f"{base}/admin/login")
        ready(page)
        page.wait_for_timeout(500)
        page.screenshot(path=str(out / "admin-login-1440.png"))
        ok(f"admin login (desktop): {out / 'admin-login-1440.png'}")
        page.get_by_label("Passwort").fill(password)
        page.get_by_role("button", name="Anmelden").click()
        page.wait_for_url(f"{base}/admin/live")
        ready(page)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)
        page.screenshot(path=str(out / "admin-live-1440.png"))
        expect(not errors, f"admin: console errors {errors}")
        ok(f"admin live after login (desktop): {out / 'admin-live-1440.png'}")
        desk.close()
        browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", required=True, help="base URL, e.g. http://127.0.0.1:8180")
    parser.add_argument("--env-file", required=True, type=Path, help="the instance's .env")
    parser.add_argument("--screenshots", type=Path, metavar="DIR", help="also take screenshots")
    parser.add_argument("--wait", type=float, default=60, help="seconds to wait for /healthz")
    args = parser.parse_args(argv)
    env = read_env(args.env_file)
    base = args.url.rstrip("/")
    try:
        wait_healthy(base, args.wait)
        guest = check_pages(base, env["VB_PARTY_TOKEN"])
        photos = check_guest(guest)
        check_admin(base, env["VB_ADMIN_PASSWORD"], photos)
        if args.screenshots:
            take_screenshots(
                base, env["VB_PARTY_TOKEN"], env["VB_ADMIN_PASSWORD"], args.screenshots
            )
    except SmokeError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 1
    print("smoke: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
