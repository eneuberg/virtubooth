# virtubooth

A self-hosted digital photo booth for parties. Guests scan a QR code with
their phone and land on a small set of camera activities. No app, no
registration, no accounts. Everything runs as one Docker container on your
server, behind any HTTPS reverse proxy.

- **Beer Cam** (`/x/beer/`): photograph your drink inside a bottle outline
  (switchable to a cup), so every photo is framed the same way. Every photo
  becomes a frame of a "1 million beers" timelapse; guests get a running beer
  count ("Bier #127").
- **Fotobox** (`/x/booth/`): live camera with real-time WebGL filters, a
  countdown, and the result saved to the guest's phone and uploaded.
- **Admin moderation** (`/admin`): a live screen that shows photos as they
  arrive (hide only) and a management screen to hide or delete photos, see
  guests, and ban devices.
- **Guest identity without registration**: a consent banner on first visit,
  a pseudonym per device (e.g. "Tanzender Waschbär #17"), an optional
  Instagram handle so you can tag people, and a browser fingerprint that is
  kept as a moderation hint.
- **Extension platform**: every activity is a small package with its own
  page and optional upload policy. Core handles access, identity, uploads,
  storage, rate limits and moderation. A live wall for a TV can come back as
  an extension.

The UI is German and mobile-first, built for recent iOS Safari and Android
Chrome.

**Contents:**
[How it works](#how-it-works) ·
[Quickstart](#quickstart) ·
[Configuration](#configuration) ·
[Running with Docker](#running-with-docker) ·
[HTTPS and reverse proxy](#https-and-reverse-proxy) ·
[Testing on a real phone](#testing-on-a-real-phone-before-party-night) ·
[Automated tests](#automated-tests) ·
[Admin](#admin) ·
[QR codes](#printing-the-qr-codes) ·
[After the party](#after-the-party) ·
[Security and privacy](#security-and-privacy) ·
[Adding an extension](#adding-an-extension) ·
[Project layout](#project-layout) ·
[Troubleshooting](#troubleshooting)

## How it works

1. **No token, no entry.** The printed QR codes point to
   `https://your-host/<page>?t=<VB_PARTY_TOKEN>`. A valid token sets an
   access cookie (`vb_access`, 30 days) and redirects to the same URL without
   the token. Without that cookie every page shows "Scan den QR-Code!" (HTTP
   404) and every API call returns 404.
2. **Consent banner.** On the first visit the guest sees what happens with
   their photos (stored, may be posted on Instagram, device recognition) and
   can enter an Instagram handle. There is no "no" button: declining means
   not using the booth. Accepting creates a pseudonymous user pinned to the
   device by a signed cookie (plus a localStorage copy).
3. **Uploads.** Photos are taken and resized in the browser, uploaded as
   JPEG, then validated, re-encoded (EXIF and GPS stripped) and stored with a
   thumbnail under the data directory, one folder per activity. Uploads are
   rate limited per guest, per IP and globally.
4. **Moderation.** Core serves a photo only to the guest who took it and to
   the admin. The admin can hide, delete, and ban a device (or, separately, a
   fingerprint).

One process with **one uvicorn worker, on purpose**: rate limits and the live
event bus live in memory. Never run several workers or replicas. SQLite and
the photo files live in `VB_DATA_DIR` (`/data` in Docker).

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Deploying to a server:
[docs/DEPLOY.md](docs/DEPLOY.md).

## Quickstart

### Local, with uv

Needs [uv](https://docs.astral.sh/uv/) (it installs Python 3.14 itself).

```bash
uv sync
uv run virtubooth gen-env > .env          # random token, admin password, secret key
set -a && . ./.env && set +a              # the app reads the environment, not the file
uv run virtubooth serve                   # http://127.0.0.1:8000 (add --reload while developing)
```

Open `http://localhost:8000/?t=<VB_PARTY_TOKEN from .env>`. On `localhost` the
desktop browser allows the camera without HTTPS; phones need HTTPS (see
[Testing on a real phone](#testing-on-a-real-phone-before-party-night)).

### Docker

Needs Docker Engine 25+ with the Compose plugin.

```bash
docker compose run --rm -T app virtubooth gen-env > .env   # builds the image on first run
$EDITOR .env                                                # party name, public URL, ...
docker compose up -d --build
docker compose ps                                           # wait for "(healthy)"
```

Open `http://localhost:8000/?t=<VB_PARTY_TOKEN>`. On the first run Compose
prints "pull access denied for virtubooth" before it builds the image; that
is expected. All settings are documented in [.env.example](.env.example).

## Configuration

Settings come from environment variables (in Docker: the `.env` file).
[.env.example](.env.example) lists every variable with comments. Empty means
default.

| Variable | Default | Purpose |
|---|---|---|
| `VB_PARTY_TOKEN` | *required* | Secret in every QR code URL (`?t=`). 16-128 chars of `A-Za-z0-9_-`. Changing it locks out all guests until they scan a new code. |
| `VB_ADMIN_PASSWORD` | *required* | Admin password (min. 12 chars). Changing it ends all admin sessions. |
| `VB_SECRET_KEY` | *required* | Signs cookies (min. 32 chars). Changing it forgets every guest device (new consent, new pseudonym). |
| `VB_PARTY_NAME` | `Party` | Shown on the home page and in the consent banner. |
| `VB_INSTAGRAM_ACCOUNT` | empty | Account you may post photos to, named in the consent banner. |
| `VB_PUBLIC_BASE_URL` | empty | Public URL without trailing slash, e.g. `https://party.example.com`. Used for the QR codes. |
| `VB_TIMEZONE` | `Europe/Berlin` | Timezone for the timestamps in photo file names. |
| `VB_CONSENT_VERSION` | `1` | Stored with each consent. Bump it when the consent text changes (devices that already accepted are not asked again). |
| `VB_EXTENSIONS` | all | Comma-separated extension ids to enable, in order, e.g. `beer,booth`. |
| `VB_COOKIE_SECURE` | `auto` | `auto` (Secure when the request came in over https or `VB_PUBLIC_BASE_URL` is https), `true`, `false`. |
| `VB_ALLOWED_ORIGINS` | empty | Extra origins for the CSRF check, e.g. `https://party.example.com`. Only needed when the proxy rewrites the `Host` header. |
| `VB_DATA_DIR` | `./data` | SQLite database and photos. Docker pins it to `/data`. |
| `VB_MAX_UPLOAD_BYTES` | `8000000` | Max size of one upload. |
| `VB_UPLOADS_PER_USER_PER_MIN` | `10` | Uploads per guest per minute. |
| `VB_UPLOADS_PER_IP_PER_MIN` | `180` | Valid uploads per IP per minute. |
| `VB_UPLOADS_GLOBAL_PER_MIN` | `300` | Uploads per minute for the whole party. |
| `VB_NEW_USERS_PER_IP_PER_10MIN` | `120` | New guest identities per IP per 10 minutes. |
| `VB_API_REQUESTS_PER_GUEST_PER_MIN` | `300` | API requests per identified guest device per minute. |
| `VB_API_REQUESTS_PER_IP_PER_MIN` | `1200` | API requests per IP per minute from devices without an identity yet. |
| `VB_ADMIN_SESSION_HOURS` | `12` | Admin login lifetime. |
| `VB_HOST` | `127.0.0.1` | Listen address of `virtubooth serve`. Docker pins `0.0.0.0`. |
| `VB_PORT` | `8000` | Listen port. Docker pins `8000`. |
| `VB_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies (IPs or CIDR ranges, comma-separated) whose `X-Forwarded-For`/`-Proto` are trusted. See [HTTPS and reverse proxy](#https-and-reverse-proxy). |
| `VB_PUBLISH_PORT` | `127.0.0.1:8000` | Compose only: host address and port. `8000` alone publishes on all interfaces. |
| `VB_IMAGE` | `virtubooth:local` | Compose only: image name the build produces and `up` runs. |
| `VB_CPU_LIMIT` / `VB_MEM_LIMIT` | `1.0` / `1g` | Compose only: container limits. The CPU limit must not exceed the host's CPU count. |

Guests on the same venue Wi-Fi (or behind carrier NAT) share one IP. So API
requests of identified guests count per device
(`VB_API_REQUESTS_PER_GUEST_PER_MIN`), only first visits count per IP, and
admin sessions are never throttled. Uploads count per guest first; the
per-IP and global upload budgets only count valid photos, so one guest
spamming broken uploads can't block everyone else. For a big crowd on one
network raise `VB_UPLOADS_PER_IP_PER_MIN` and `VB_NEW_USERS_PER_IP_PER_10MIN`.

## Running with Docker

| Task | Command |
|---|---|
| Start (build if needed) | `docker compose up -d --build` |
| Status / health | `docker compose ps` |
| Logs | `docker compose logs -f app` |
| Stop (keeps data) | `docker compose stop` (or `down`, which also removes the container) |
| Restart | `docker compose restart app` |
| Apply `.env` changes | `docker compose up -d` (a plain `restart` does **not** re-read `.env`) |
| Update to new code | `git pull && docker compose up -d --build` |
| Shell inside the container | `docker compose exec app sh` |
| Remove everything incl. photos | `docker compose down -v` (irreversible) |

What the container does:

- Runs as uid/gid `10001`, read-only root filesystem, no Linux capabilities,
  `no-new-privileges`, CPU/memory/pids limits, a small init process.
- Stores everything in the named volume `virtubooth_data` mounted at `/data`.
  It survives `down`, rebuilds and updates; only `down -v` deletes it.
- Has a health check on `GET /healthz` and rotates its logs (5 x 10 MB).
- Ships ffmpeg for the timelapse tool.

## HTTPS and reverse proxy

Browsers only allow camera access on **HTTPS** pages (or `localhost`). The
container speaks plain HTTP on port 8000, so put a TLS-terminating reverse
proxy in front (Caddy, Traefik, nginx, Coolify, ...). Then set in `.env`:

```dotenv
VB_PUBLIC_BASE_URL=https://party.example.com
VB_COOKIE_SECURE=true
VB_FORWARDED_ALLOW_IPS=172.16.0.0/12   # the proxy's address as seen from the container
VB_PUBLISH_PORT=127.0.0.1:8000         # if the proxy runs on the same host
```

- `VB_FORWARDED_ALLOW_IPS` matters: without it the app sees every guest as
  the proxy's IP, so the per-IP rate limits apply to the whole party at once,
  and logs show the proxy instead of guests. A proxy on the host or in
  another container connects from a Docker network address
  (`172.16.0.0/12` covers Docker's default networks; the exact address shows
  up in `docker compose logs app` for proxied requests).
- The proxy must pass the original `Host` header (Caddy and Traefik do;
  nginx needs `proxy_set_header Host $host;`), else every POST fails the CSRF
  check with `403 bad_origin`. Alternative: `VB_ALLOWED_ORIGINS`.
- Live screens use Server-Sent Events: the proxy must not buffer them. The
  app sends `X-Accel-Buffering: no`; Caddy and Traefik stream by default.
- Uploads are up to `VB_MAX_UPLOAD_BYTES` (8 MB): raise the proxy's body
  limit if it has one (nginx: `client_max_body_size 10m;`).
- Docker's published ports bypass ufw/firewalld. Publish on `127.0.0.1` (or
  not at all, with the proxy in the same Docker network) so nobody reaches
  the app around the proxy.

Copy-paste configs for Caddy, Traefik and nginx: [docs/DEPLOY.md](docs/DEPLOY.md).

## Testing on a real phone before party night

Do this a few days before the party, and once more on the real domain.

1. **Get an HTTPS URL.** Either deploy to the real domain, or tunnel your
   local instance with a [Cloudflare quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
   (no account needed; the URL changes every run, so it is for testing only):

   ```bash
   cloudflared tunnel --url http://localhost:8000
   # prints https://<random-words>.trycloudflare.com
   ```

2. **Open the QR URL on the phone**: `https://<host>/?t=<VB_PARTY_TOKEN>`.
   To avoid typing the token, show it as a QR code in the terminal and scan
   it with the phone's camera app:

   ```bash
   uv run python -c "import segno, sys; segno.make(sys.argv[1]).terminal(compact=True)" \
     "https://<host>/?t=<VB_PARTY_TOKEN>"
   ```

   Or print the real sheet with the [QR tool](#printing-the-qr-codes)
   (`--base-url https://<host>`).

3. **Walk through as a guest:** consent banner, Instagram handle, Beer Cam
   (rear camera, outline, upload, beer count), Fotobox (front camera, filter
   switching, countdown, save to phone, upload), camera switch, and what
   happens when you deny the camera permission. Try both iOS Safari and
   Android Chrome, and opening the link from inside Instagram or WhatsApp
   (in-app browsers often block the camera; guests should open it in Safari
   or Chrome).
4. **Watch it in the admin** on a laptop: `https://<host>/admin`, new photos
   appear on the live screen.

**Debugging on the phone:**

- **`?debug=1`**: append it to any page (e.g. `/?t=<token>&debug=1` or
  `/x/beer/?debug=1`) to get an on-screen log panel. It stays on for that tab.
- **Android:** enable *Developer options* → *USB debugging*, connect the
  phone by USB, open `chrome://inspect#devices` in desktop Chrome and click
  *inspect* under the tab. You get the full DevTools (console, network).
- **iOS:** remote debugging needs a Mac: on the iPhone *Settings → Safari →
  Advanced → Web Inspector*, connect by cable, then in Safari on the Mac
  *Develop → <your iPhone> → <the tab>*. Without a Mac, use `?debug=1`.

## Automated tests

```bash
uv sync                              # includes the dev dependencies
uv run pytest                        # unit and API tests (fast, default)
uv run playwright install chromium   # once, for the browser tests (Linux: add --with-deps)
uv run pytest -m e2e                 # browser tests: Chromium with a fake camera
VB_FAKE_VIDEO=clip.y4m uv run pytest -m e2e   # use your own camera clip (.y4m/.mjpeg)
```

The fixtures (`tests/conftest.py`, `tests/e2e/conftest.py`) give you a
consented guest client, a logged-in admin, and a live server for Playwright.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#testing).

## Admin

Open `https://<host>/admin` and log in with `VB_ADMIN_PASSWORD`. The admin
area does not need the party token.

- **Live screen**: photos appear as they are uploaded. You can only *hide*
  here, so nothing is deleted by an accidental tap during the party.
- **Management screen**: hide/unhide and delete photos (delete removes the
  files for good; the photo number is never reused), see guests with their
  pseudonym, Instagram handle and photo count, and ban:
  - **Ban a user** (one device): hides all their photos and blocks uploads.
    Unbanning restores exactly those photos.
  - **Ban a fingerprint** (with a warning): new identities that show this
    fingerprint start out banned. Identical phone models often share a
    fingerprint, so this can hit innocent guests. Use it for repeat offenders
    who clear their cookies.

Sessions last `VB_ADMIN_SESSION_HOURS` (12 h); log in before the guests
arrive. Login is rate limited per IP (5 per minute, 20 per hour). After 50
wrong passwords within an hour from anywhere, further wrong guesses get "Zu
viele Fehlversuche"; the correct password always still works, so nobody can
lock you out by guessing. Keep the password long and random (`gen-env` does).

A fingerprint ban is a speed bump, not a wall: someone who forges their
fingerprint with developer tools gets a fresh identity. Against the usual
evasion (private tab, cleared cookies) it works, because the fingerprint
stays the same.

## Printing the QR codes

```bash
docker compose exec app python -m virtubooth.tools.qr --base-url https://party.example.com
docker compose cp app:/data/exports/qr ./qr        # then open qr/qr-sheet.html and print
```

The tool writes a printable `qr-sheet.html` (one A4 page per code: the home
page plus each activity) and SVG/PNG files of the codes to `/data/exports/qr/`
(`--out DIR` to change), with the party token baked into every URL but never
printed as text. `--extensions beer,booth` picks the activities, `--base-url`
overrides `VB_PUBLIC_BASE_URL`, and `--token` prints codes for a token you
have not deployed yet. Locally (with the `.env` loaded): `uv run python -m
virtubooth.tools.qr --out ./exports`.

Anyone holding a printed code is in, so treat the sheets like keys and
reprint after [rotating the token](docs/DEPLOY.md#9-rotating-the-party-token).

## After the party

All tools run inside the container and write to `/data/exports/` by default.
`docker compose exec app ...` uses the running app; with the app stopped, use
`docker compose run --rm app ...` instead.

**Beer timelapse** (ffmpeg, photos in upload order):

```bash
docker compose exec app python -m virtubooth.tools.timelapse --extension beer --fps 12 --crossfade
docker compose exec app python -m virtubooth.tools.timelapse --dry-run   # show what it would do
```

Options: `--fps 12`, `--crossfade` (with `--fade 0.5`: share of each photo's
time spent blending into the next, matters at low fps), `--size 1080x1440`,
`--hold-last 2` (seconds on the last frame), `--crf 20` (quality, lower is
better), `--preset medium`, `--include-hidden`, `--limit N` (quick preview
with the first N photos), `--out FILE`, `--data-dir DIR`. Hidden and deleted
photos are left out by default.

**Export** the photos and their metadata as one `.tar.gz`:

```bash
docker compose exec app python -m virtubooth.tools.export                 # all photos
docker compose exec app python -m virtubooth.tools.export --no-hidden     # skip hidden ones
```

Options: `--out FILE.tar.gz`, `--data-dir DIR`, `--no-db`. The archive holds
one folder `virtubooth-export-<timestamp>/` with `photos/<extension>/`
(hidden ones in `photos/<extension>/hidden/`), `photos.csv`, `users.csv`,
`instagram.csv` (handle → photos to tag them on), a consistent copy of
`virtubooth.db` (contains IPs and fingerprints; leave it out with `--no-db`)
and a `README.txt`.

**Copy results off the server:**

```bash
# on the server
docker compose cp app:/data/exports ./exports
# on your machine
scp -r server:virtubooth/exports ./party-exports
```

For a raw copy of the whole data volume (database + all photos), stop the
app first so the SQLite files are consistent:

```bash
docker compose stop
docker run --rm -v virtubooth_data:/data:ro -v "$PWD":/backup alpine:3.22 \
  tar czf /backup/virtubooth-data.tar.gz -C /data .
docker compose start
```

Data layout inside `/data`: `virtubooth.db` (+ `-wal`/`-shm`),
`<extension>/<YYYYmmdd-HHMMSS-mmm>_<rand>.jpg`, `<extension>/thumbs/`,
`exports/`.

## Security and privacy

- **Party token.** Everything a guest sees requires the token from the QR
  code. It is a shared secret: whoever has a code (or a photo of it) is in.
  The token is removed from the URL right after the scan, pages send
  `Referrer-Policy: no-referrer`, and the access log masks it (`?t=***`).
- **Rotating the token** (a code leaked, or the party is over): change
  `VB_PARTY_TOKEN` in `.env`, run `docker compose up -d`, reprint the codes.
  Every guest must scan again; their pseudonym and photos stay theirs. Steps:
  [docs/DEPLOY.md](docs/DEPLOY.md#9-rotating-the-party-token).
- **Admin password.** At least 12 characters, generated by `gen-env`. Never
  print it on anything. Changing it ends all admin sessions.
- **Consent.** Guests agree to photos being stored and posted on Instagram
  and to device recognition before they can take photos. The fingerprint is
  a moderation hint, not an identity.
- **Data minimisation.** Photos are re-encoded, so EXIF/GPS data from the
  phone never reaches the disk. Core serves a photo only to the guest who
  took it and to the admin. The database keeps per guest: pseudonym, optional
  Instagram handle, fingerprint hashes and components, first/last IP, user
  agent, and timestamps.
- **Hardening.** Strict CSP (no inline scripts, no CDNs), CSRF origin check
  on every state-changing request, upload validation and size caps, rate
  limits, HttpOnly cookies (admin: `SameSite=Strict`), container without
  root or capabilities.
- **Retention: delete everything afterwards.** Hidden photos stay on disk
  (only deleting removes the files), so once you have exported what you want
  to keep and posted what you promised:
  1. `docker compose down -v` deletes the container, its logs and the data
     volume (database and every photo).
  2. Delete exported archives, backups and copies you made, and the `.env`.

## Adding an extension

An activity is a package `virtubooth/extensions/<name>/` whose `__init__.py`
exports `extension = Extension(...)`: id, title, emoji, a static directory
with `index.html`, and optionally an `UploadPolicy`, an API router and an
`on_upload` hook. Core discovers it automatically, serves its page at
`/x/<name>/`, mounts its API at `/api/x/<name>/`, handles uploads, and lists
it on the home page, in the QR sheet and in the admin. The frontend uses the
SDK in `/static/core/vb.js` (`boot()`, `openCamera()`, `uploadJpeg()`, ...).

Full contract, example and SDK reference:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#extension-interface).

## Project layout

```
virtubooth/
├── app.py, config.py, ...   core: settings, access, identity, uploads, media, events
├── static/core/             frontend SDK (vb.js, camera.js, fingerprint.js, vb.css) + home page
├── admin/                   admin API + admin UI
├── extensions/              one package per activity: beer/, booth/, ...
└── tools/                   CLI tools: timelapse, qr, export
tests/                       pytest unit/API tests; tests/e2e/ Playwright browser tests
docs/
├── ARCHITECTURE.md          how the pieces fit, extension interface, SDK
├── DEPLOY.md                server deployment, reverse proxy, backups, updates
├── PLAN.md                  decisions
└── REQUIREMENTS.md          original spec
Dockerfile, compose.yaml     container image and deployment
.env.example                 every setting, documented
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Every page says "Scan den QR-Code!" | No or outdated access cookie: open the QR URL with `?t=<current token>`. |
| Camera does not start on the phone | Not on HTTPS, permission denied, or an in-app browser. Use the HTTPS URL in Safari/Chrome; check the site's camera permission. |
| `403 bad_origin` on every upload/consent | The proxy rewrites the `Host` header. Pass it through or set `VB_ALLOWED_ORIGINS`. |
| Lots of `429` during the party | Guests share an IP: set `VB_FORWARDED_ALLOW_IPS` for your proxy, and raise the per-IP limits for venue Wi-Fi. |
| Cookies lack `Secure` behind HTTPS | Set `VB_PUBLIC_BASE_URL` to the https URL or `VB_COOKIE_SECURE=true`. |
| Container exits on start | `docker compose logs app`: a missing or too short `VB_*` secret is reported by name. |
| `.env` changes have no effect | Use `docker compose up -d`, not `restart`. |
| Admin login says "Zu viele Fehlversuche" | Someone guessed wrong 50+ times this hour. The correct password still works; restarting the container resets the counter. |
