# virtubooth: plan (draft, awaiting approval)

Status: **proposal, nothing built yet.** The Pi environment is not checked yet
(no SSH access configured). Items marked ⚠ depend on that check.

Spec: [REQUIREMENTS.md](REQUIREMENTS.md)

## Architecture

```
phone (QR scan) ──HTTPS──▶ Caddy :443 ──▶ uvicorn 127.0.0.1:8000  (Starlette app)
TV / projector  ──HTTPS + SSE──┘                │
                                                ├─ data/beer/*.jpg
                                                ├─ data/booth/*.jpg
                                                └─ data/virtubooth.db  (SQLite, WAL)
```

- **Caddy**: automatic Let's Encrypt TLS, HTTP→HTTPS redirect, compression,
  request body cap (6 MB), reverse proxy to the app. Caddy flushes
  `text/event-stream` responses immediately, so SSE works without extra config.
- **App**: a single Python process (Starlette + uvicorn, one async worker). It
  serves the static pages, the API, the photos and the SSE stream. Image
  validation runs in a thread pool so the event loop stays free.
- **Frontend**: plain HTML/CSS/JS (ES modules), no build step, **no CDN**.
  Everything is served from the Pi, so a flaky venue internet connection
  doesn't break the pages.

**Why Python/Starlette:** Python ships with Raspberry Pi OS, the process uses
~40–60 MB RAM, Pillow handles image validation and `sqlite3` is in the stdlib.
50 guests produce a few requests per second at peak, far below what one
uvicorn worker handles on a Pi. ⚠ Final check against Pi model, arch and
Python version.

## Access control

- Two secrets in `/etc/virtubooth/env`: `PARTY_TOKEN` (guests) and
  `ADMIN_TOKEN` (host).
- The QR code URLs look like `https://<domain>/beer?t=<PARTY_TOKEN>`. The
  server checks the token, sets an HttpOnly, `SameSite=Lax` cookie and
  redirects to `/beer`. The token disappears from the address bar, so it
  doesn't spread by link sharing.
- Every API call, photo request and SSE stream requires that cookie (or an
  `X-Party-Token` header as a fallback). Without it the server answers 404.
- **Admin page** `/admin?t=<ADMIN_TOKEN>` (not in the spec, recommended):
  recent photos, one tap hides a photo from the wall and the timelapse.
  50 guests and a projector means someone will upload something.

## Upload limits

- Caddy: request body ≤ 6 MB.
- App: `image/jpeg` only, magic-byte check, full Pillow decode, max 2400 px per
  side, then re-encode to JPEG q85. The re-encode strips all metadata
  (EXIF/GPS) and normalizes files for ffmpeg.
- Rate limit, in-memory token buckets: per device (random ID in a cookie)
  10 uploads/min, per IP 60/min, global 300/min. The per-IP limit is loose on
  purpose: guests on the venue WiFi all share one IP.

## Storage

```
data/
├── beer/20261024-211403-123_a1b2c3.jpg
├── booth/20261024-211530-456_d4e5f6.jpg
└── virtubooth.db
```

Table `photos(id, activity, filename, created_at, device_id, width, height,
bytes, filter, hidden)`. Filenames sort by time; the DB is the source of truth
for ordering, the beer count and the hidden flag.

## The three pages

### Beer Cam `/beer`

- `getUserMedia({ video: { facingMode: "environment" } })` with
  `<video playsinline muted autoplay>` (required on iOS).
- SVG overlay: glass silhouette inside a square frame, the area outside is
  darkened.
- Capture: crop to the guide square → canvas 1080×1080 → JPEG q0.85
  (~150–250 KB) → upload with a progress bar.
- The response carries the beer number → "Beer #127 logged 🍺", confetti,
  running counter, "One more" button.
- Every frame has the same size and framing, so the timelapse needs no scaling
  or cropping.

### Photo Booth `/booth`

- WebGL1 pipeline: video → texture → fragment shader → canvas. Canvas 2D
  pixel-op fallback if WebGL is unavailable. No CSS filters, no `ctx.filter`.
- Filters (swipe or tap): Normal, B&W, Sepia, Color pop (one hue stays, the
  rest goes gray), Pixel/retro (pixelate + reduced palette), Vintage/VHS, Party
  frame, Emoji props (stickers at fixed positions + confetti border).
- Frames and emoji are drawn once into a 2D canvas, uploaded as a texture and
  composited in the same shader pass. The saved image is exactly the preview.
- Front camera by default, mirrored **in the shader** so frame text stays
  readable. Toggle to switch to the rear camera.
- Optional 3-2-1 countdown, flash effect, capture from the WebGL canvas,
  output 1080×1440 (3:4) JPEG.
- Result screen: **Save** (Web Share API with a file → "Save Image" on iOS,
  download on Android), upload to the Pi runs in parallel, **Retake**.

### Live Wall `/wall`

- Fullscreen. An SSE stream (`/api/events`) pushes new photos and the counter,
  with auto-reconnect.
- New photo → hero animation (polaroid style, scale-in), labeled 🍺 or 📸.
  When idle, a Ken Burns slideshow cycles through older photos every ~6 s.
- Large beer counter with a count-up animation, plus a small
  "x / 1,000,000" progress bar.
- QR code (SVG, generated server-side with `segno`) + "Scan to join".
- Images are preloaded before they're shown, and only a few `<img>` elements
  stay in the DOM, so memory stays flat over a long night.

## Scripts

- `scripts/make_timelapse.py --fps 12 [--crossfade] [--out beer.mp4]`: reads
  the order from SQLite (skips hidden photos), writes an ffmpeg concat list and
  encodes H.264. Crossfade uses ffmpeg's `framerate` filter (blends
  neighbouring frames up to 30 fps): one pass instead of a chain of hundreds
  of `xfade` filters. Runs on the Pi, or faster on a laptop after the export.
- `scripts/make_qr.py`: A4 print sheet (HTML → print to PDF) with QR codes for
  Beer Cam and Photo Booth, token baked in, big labels.
- `scripts/export.sh`: tarball of `data/` + metadata CSV.

## Deploy

- `deploy/install.sh`: creates the `virtubooth` user, venv, deps, env file with
  random tokens, installs Caddy (apt) + Caddyfile + systemd unit.
- `deploy/virtubooth.service`: `Restart=always`, sandboxing
  (`ProtectSystem=strict`, `ReadWritePaths=/var/lib/virtubooth`), memory cap.
- Caddy runs as its own systemd service from the apt package.

## Repo layout

```
virtubooth/
├── README.md
├── pyproject.toml
├── virtubooth/      app.py, config.py, db.py, auth.py, images.py, events.py
├── web/
│   ├── shared/      camera.js, upload.js, party.css, confetti.js
│   ├── beer/        index.html, beer.js
│   ├── booth/       index.html, booth.js, shaders.js, overlays.js
│   ├── wall/        index.html, wall.js
│   └── admin/       index.html, admin.js
├── scripts/         make_timelapse.py, make_qr.py, export.sh
├── deploy/          Caddyfile, virtubooth.service, install.sh
├── tests/           pytest: token gate, limits, image validation, ordering
└── docs/            REQUIREMENTS.md, PLAN.md
```

## Build order (each step tested before the next)

1. App skeleton: config, DB, token gate, upload endpoint, pytest.
2. Beer Cam page → test on laptop webcam.
3. Live Wall + SSE.
4. Photo Booth + shaders.
5. Admin page.
6. Scripts: QR sheet, timelapse, export.
7. Deploy to the Pi (Caddy, systemd), phone tests on the real domain, load test
   with ~50 concurrent uploads while watching CPU/RAM.

## Testing

- **Laptop:** run the app locally and open `http://localhost:8000`.
  `localhost` counts as a secure context, so the webcam works without HTTPS.
- **Phones:** on the real domain over HTTPS, the same setup as party night.
  `?debug=1` shows an on-screen log, because iOS remote debugging needs a Mac.
  Android: `chrome://inspect` over USB from the laptop.

## Risks and gotchas

- **NAT loopback:** if guests are on the same WiFi as the Pi, the router must
  support NAT loopback (hairpinning), otherwise the public domain is
  unreachable from inside the network. Fix: a local DNS override (router or
  Pi-hole) that points the domain to the Pi's LAN IP. Must be tested before
  party night.
- **Certificates:** Let's Encrypt needs port 80 or 443 reachable from the
  internet (or a DNS challenge). If that's not possible: Cloudflare Tunnel as a
  fallback.
- **In-app browsers:** a QR code scanned from inside an app (e.g. Instagram)
  can open an in-app browser with limited camera support. The pages detect
  this and show "open in Safari/Chrome".

## Open questions

1. SSH access to the Pi (host, user)?
2. Domain? Are ports 80/443 forwarded to the Pi? Is anything already listening
   there (Pi-hole, nginx, Home Assistant…)? Static IP or DynDNS?
3. Where is the party, and which network will guests use (the Pi's WiFi or
   mobile data)? See NAT loopback above.
4. What drives the TV? A laptop, smart TV, or Fire TV stick browser, or the Pi
   itself via HDMI (Chromium on the Pi costs CPU: fine on a Pi 4/5, tight on a
   Pi 3)?
5. Admin/moderation page: yes or no?
6. Party date?
