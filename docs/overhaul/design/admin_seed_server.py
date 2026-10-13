"""A seeded party for looking at the admin app (wave 2, AD): screenshots and manual checks.

    cd backend && uv run python ../docs/overhaul/design/admin_seed_server.py [--port 8170]

Serves frontend/dist on 127.0.0.1:<port> with a fresh data dir, 14 guests, ~40 photos
(the synthetic mockup images, scaled to 1080x1440), hidden photos, a banned guest with a
banned device trait plus an automatically banned twin, a paused guest, the new-guest
pause with one affected guest, two Instagram names marked done and a slow export job
(it runs for about five minutes, so its progress can be seen). Admin password: "admin-admin-1".
Runs until Ctrl-C; prints SEEDED when ready.
"""

from __future__ import annotations

import argparse
import io
import itertools
import json
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote

import httpx2 as httpx
import uvicorn
from PIL import Image

from virtubooth.app import create_app
from virtubooth.core.ratelimit import RateLimiter
from virtubooth.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
IMG = ROOT / "docs/overhaul/design/mockups/img"
PASSWORD = "admin-admin-1"
TOKEN = "seed-party-token-0123456789"

HANDLES = [
    "hupf.alpaka", "anna.party", "ben_b", "dj.dennis", "clara.k", "mo.tanzt",
    "lena.lacht", None, None, "kiki.k", None, "tom.t",
]  # fmt: skip
FILTERS = ["normal", "neon", "bw", "sepia", "party", "comic", "vhs", "retro"]
UA_PHONE = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"
)
UA_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
)


def photo_bytes(name: str) -> bytes:
    img = Image.open(IMG / name).convert("RGB").resize((1080, 1440), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=82)
    return buf.getvalue()


def fp(n: int) -> dict[str, object]:
    return {
        "hash": f"{n:064x}",
        "components": {
            "screen": "412x915@2.6",
            "gl_renderer": "Adreno (TM) 730",
            "languages": "de-DE,de,en",
            "timezone": "Europe/Berlin",
            "cores": 8,
            "memory": 8,
        },
    }


class Guest:
    def __init__(self, base: str, n: int, instagram: str | None, ua: str) -> None:
        self.base = base
        self.c = httpx.Client(base_url=base, headers={"User-Agent": ua, "Origin": base})
        assert self.c.get(f"/?t={TOKEN}").status_code in (200, 303)
        ident = self.c.post("/api/identify", json={"fp": fp(n)}).json()
        version = ident["consent"]["version"] if "consent" in ident else "1"
        r = self.c.post(
            "/api/join",
            json={"accept": True, "version": version, "instagram": instagram, "fp": fp(n)},
        )
        assert r.status_code in (200, 201), r.text
        self.state = r.json()["state"]

    def upload(self, ext: str, data: bytes, meta: dict[str, object]) -> str | None:
        r = self.c.post(
            f"/api/x/{ext}/upload",
            content=data,
            headers={
                "Content-Type": "image/jpeg",
                "X-VB-Meta": quote(json.dumps(meta), safe=""),
            },
        )
        if r.status_code != 201:
            return None
        return str(r.json()["photo"]["id"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8170)
    args = ap.parse_args()
    data = Path(tempfile.mkdtemp(prefix="vb-admin-seed-"))
    settings = Settings(
        _env_file=None,
        party_token=TOKEN,
        admin_password=PASSWORD,
        secret_key="seed-secret-key-0123456789abcdef0123456789",
        data_dir=data,
        web_dir=ROOT / "frontend/dist",
        party_name="Eriks Geburtstag",
        public_base_url=f"http://127.0.0.1:{args.port}",
        uploads_per_user_per_min=1000,
    )
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    core = app.state.core
    # screenshot runs log in and out a lot
    core.limits.login_ip = RateLimiter(10_000, 60)
    core.limits.login_ip_hourly = RateLimiter(10_000, 3600)
    base = f"http://127.0.0.1:{args.port}"

    beer = [photo_bytes(f"beer-{i}.jpg") for i in range(1, 5)]
    booth = [photo_bytes(f"booth-{i}.jpg") for i in range(1, 9)]
    guests = [Guest(base, i + 1, h, UA_IPHONE if i % 3 == 0 else UA_PHONE) for i, h in enumerate(HANDLES)]
    ids: list[str] = []
    cycle_beer, cycle_booth, cycle_filter = itertools.cycle(beer), itertools.cycle(booth), itertools.cycle(FILTERS)
    for round_ in range(4):
        for i, g in enumerate(guests):
            if (i + round_) % 3 == 2:
                continue
            if (i + round_) % 2:
                pid = g.upload("beer", next(cycle_beer), {"vessel": "bottle" if i % 2 else "cup", "facing": "environment"})
            else:
                pid = g.upload("booth", next(cycle_booth), {"filter": next(cycle_filter), "facing": "user"})
            if pid:
                ids.append(pid)

    admin = httpx.Client(base_url=base, headers={"Origin": base})
    assert admin.post("/api/admin/login", json={"password": PASSWORD}).status_code == 200
    for pid in ids[3:30:6]:
        admin.post(f"/api/admin/photos/{pid}/hide")
    troll = guests[4]
    troll_id = core.repos.users.get_by_public_id(
        core.signer.unsign("uid", troll.c.cookies.get("vb_uid"))
    ).id
    admin.post(f"/api/admin/users/{troll_id}/ban", json={"reason": "Spam", "fingerprint": True})
    Guest(base, 5, None, UA_PHONE)  # same phone model as the troll: starts banned
    paused_id = core.repos.users.get_by_public_id(
        core.signer.unsign("uid", guests[2].c.cookies.get("vb_uid"))
    ).id
    admin.post(f"/api/admin/users/{paused_id}/uploads", json={"paused": True})
    admin.post("/api/admin/upload-pause", json={"enabled": True})
    Guest(base, 40, "neu.hier", UA_PHONE)  # joins during the pause
    for handle in ("ben_b", "kiki.k"):
        admin.post(f"/api/admin/instagram/{handle}/done", json={"done": True})

    # a slow export, so the running state can be seen
    svc = core.services.exports
    original = svc.runners["archive"]

    def slow(ctx):  # type: ignore[no-untyped-def]
        for step in range(300):
            ctx.progress(0.2 + step / 600)
            time.sleep(1)
        original(ctx)

    svc.runners["archive"] = slow
    admin.post("/api/admin/exports", json={"kind": "qr", "options": {}})
    time.sleep(1.5)
    admin.post("/api/admin/exports", json={"kind": "archive", "options": {"include_hidden": False, "include_db": False}})
    print("SEEDED", base, "photos:", len(ids), "data:", data, flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.should_exit = True


if __name__ == "__main__":
    main()
