# Deploying virtubooth

From a Linux server with Docker to a party-ready HTTPS site: Compose or
Coolify, the reverse proxy, every setting, the photo analysis, backups,
updates and troubleshooting. How the app works inside:
[ARCHITECTURE.md](ARCHITECTURE.md).

> **One container, one worker.** Rate limits and the live event bus live in
> process memory. Never scale the service, add replicas or run more workers.

Contents:
[Requirements](#requirements) ·
[The image](#the-image) ·
[Docker Compose](#docker-compose) ·
[Reverse proxy and HTTPS](#reverse-proxy-and-https) ·
[Coolify](#coolify) ·
[Settings](#settings) ·
[Live-Wall and photo analysis](#live-wall-and-photo-analysis) ·
[Command line](#command-line) ·
[Party-night checklist](#party-night-checklist) ·
[Backups](#backups) ·
[Updating](#updating) ·
[Secrets and the admin password](#secrets-and-the-admin-password) ·
[Teardown](#teardown) ·
[Troubleshooting](#troubleshooting)

## Requirements

- Linux with Docker Engine 25+ and the Compose plugin. 1 vCPU and 1 GB RAM
  carry about 50 guests; the photo analysis needs about 0.65 GB more
  ([below](#live-wall-and-photo-analysis)).
- About 1 GB of free RAM for a minute while the image builds (the frontend is
  built inside it). On a small server add swap, or build elsewhere and push
  to a registry (`VB_IMAGE`).
- Disk: the image (1 to 1.9 GB, see [the table](#image-sizes-and-memory)),
  up to about 0.5 MB per photo with its thumbnail, and the exports.
- A domain with an A/AAAA record to the server, ports 80 and 443 open for the
  proxy's certificates.

## The image

The root `Dockerfile` builds one self-contained image: a Node stage builds
the frontend, a uv stage the Python venv, and the runtime
(`python:3.14.8-slim-trixie` + ffmpeg) gets only the venv, the frontend in
`/app/web`, user 10001, the volume `/data` and a health check on `/healthz`.
The tool versions are pinned at the top of the `Dockerfile`. Build arguments: `VB_ML` (default `0`; `1` adds MediaPipe, ONNX Runtime and
OpenCV for the photo analysis) and `VB_BAKE_MODELS` (default `0`; `1` puts
the analysis models into the image at `/opt/vb-models`).
`docker-compose.coolify.yaml` builds with `VB_ML=1`; `compose.yaml` and a
plain `docker build` use the defaults. `.dockerignore` is an allowlist:
`.env`, data and local builds never enter the build context.

```bash
docker build -t virtubooth:local .     # what `docker compose build` does
make docker-smoke                      # build, run on 127.0.0.1:8180, check end to end
```

`make docker-smoke` talks to the container through the published port. A
host firewall that drops traffic to Docker's bridge networks (for example a
VPN kill switch) makes it fail although the container is healthy: allow
`172.16.0.0/12`. If the same firewall breaks `pnpm install` in the build, use
`make docker-smoke DOCKER_BUILD_FLAGS=--network=host`.

## Docker Compose

```bash
git clone <your repo url> ~/virtubooth && cd ~/virtubooth
docker compose run --rm -T app virtubooth gen-env > .env   # builds the image, prints fresh secrets
chmod 600 .env && $EDITOR .env
docker compose up -d --build
docker compose ps                          # "(healthy)" after a few seconds
curl -fsS http://127.0.0.1:8000/healthz    # {"ok":true}
```

The first `run` prints "pull access denied for virtubooth" before it builds;
that is expected. `gen-env` writes the secrets and the basics; add more from
[.env.example](../.env.example). Behind a proxy on the same host, set at least:

```dotenv
VB_PARTY_NAME=Sommerfest
VB_PUBLIC_BASE_URL=https://party.example.com
VB_COOKIE_SECURE=true
VB_FORWARDED_ALLOW_IPS=172.16.0.0/12
VB_PUBLISH_PORT=127.0.0.1:8000
```

Quote values with spaces (`VB_PARTY_NAME="Sommerfest 2026"`). Compose expands
`$` in `.env`, so keep `$` out of passwords or single-quote them.
`compose.yaml` pins `VB_DATA_DIR=/data`, `VB_HOST=0.0.0.0`, `VB_PORT=8000` and
`VB_WEB_DIR=/app/web` inside the container.

| Task | Command |
|---|---|
| Logs | `docker compose logs -f app` |
| Apply `.env` changes | `docker compose up -d` (`restart` does **not** re-read `.env`) |
| Stop, keep data | `docker compose stop` or `down` |
| Shell in the container | `docker compose exec app sh` |
| Delete everything, photos included | `docker compose down -v` |

The container runs as uid 10001 on a read-only root filesystem, without Linux
capabilities, with `no-new-privileges`, CPU/memory/PID limits, a small init
and rotated logs (5 × 10 MB). All data is in the named volume
`virtubooth_data` at `/data`; it survives `down`, rebuilds and updates.

## Reverse proxy and HTTPS

Phones only open the camera on HTTPS pages. The proxy must:

1. terminate TLS for your domain;
2. pass the original `Host` header (the CSRF check compares the browser's
   `Origin` with `VB_PUBLIC_BASE_URL` and with the request's own origin; a
   proxy that rewrites `Host` works through `VB_PUBLIC_BASE_URL` or
   `VB_ALLOWED_ORIGINS`);
3. send `X-Forwarded-For` and `X-Forwarded-Proto`, from an address listed in
   `VB_FORWARDED_ALLOW_IPS`; otherwise every guest looks like the proxy and
   the per-IP limits throttle the whole party at once;
4. not buffer Server-Sent Events (the app sends `X-Accel-Buffering: no` and a
   ping every 15 s);
5. accept request bodies of at least 8 MB.

Which address to trust: a proxy on the host reaches a `127.0.0.1` port
through the Docker bridge gateway, a proxy container from its address in the
shared network. `172.16.0.0/12` covers Docker's default networks. To be exact,
look at the client address of a proxied request in `docker compose logs app`,
or run `docker network inspect virtubooth_default --format '{{(index
.IPAM.Config 0).Gateway}}'`. Docker's published ports bypass ufw and
firewalld, so publish on `127.0.0.1`.

**Caddy on the host.** `/etc/caddy/Caddyfile`, then
`sudo systemctl reload caddy`. Don't add `encode`: assets are precompressed
and compressing the event stream delays live updates.

```caddyfile
party.example.com {
	request_body {
		max_size 10MB
	}
	reverse_proxy 127.0.0.1:8000
}
```

**Traefik** (Docker provider, entrypoint `websecure`, resolver `letsencrypt`,
external network `proxy`): a `compose.override.yaml` next to `compose.yaml`,
and `VB_FORWARDED_ALLOW_IPS` set to the `proxy` network's subnet.

```yaml
services:
  app:
    ports: !reset []
    networks: [default, proxy]
    labels:
      traefik.enable: "true"
      traefik.docker.network: proxy
      traefik.http.routers.virtubooth.rule: Host(`party.example.com`)
      traefik.http.routers.virtubooth.entrypoints: websecure
      traefik.http.routers.virtubooth.tls.certresolver: letsencrypt
      traefik.http.services.virtubooth.loadbalancer.server.port: "8000"

networks:
  proxy:
    external: true
```

**nginx:**

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name party.example.com;
    # ssl_certificate / ssl_certificate_key, e.g. from certbot

    client_max_body_size 10m;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        # $remote_addr, not $proxy_add_x_forwarded_for: the app trusts the first entry
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 1h;
    }
}
```

**Check it:**

```bash
curl -fsS https://party.example.com/healthz                                   # {"ok":true}
curl -s -o /dev/null -w '%{http_code}\n' https://party.example.com/          # 404, the gate
curl -s -o /dev/null -D - "https://party.example.com/?t=$TOKEN" | grep -i set-cookie   # vb_access=…; Secure
docker compose logs --tail 5 app    # real client addresses, not 172.x
```

Then open the link on an iPhone and an Android phone, join, take a photo in
each activity and watch it arrive at `/admin/live`. On a fresh install the
token is `VB_PARTY_TOKEN` from `.env` (it became QR code 1); later, copy a
code's link in Admin → QR-Codes.

## Coolify

[`docker-compose.coolify.yaml`](../docker-compose.coolify.yaml) is made for
Coolify's "Docker Compose" build pack. It publishes no port, takes the domain
from Coolify and lets Coolify generate the secrets. No `.env`, no proxy setup.

1. **Repository access.** A GitHub App (it can redeploy on push) or a
   read-only deploy key.
2. **Resource:** Project → `+ New` → repository and branch, Build Pack
   **Docker Compose**, Docker Compose Location `/docker-compose.coolify.yaml`.
3. **Domain:** in the service `app`, Domains =
   `https://party.example.com:8000` (`:8000` is the container port; guests
   open `https://party.example.com`). The app takes its public URL from it.
4. **Environment variables.** Coolify generates `VB_PARTY_TOKEN`,
   `VB_ADMIN_PASSWORD` and `VB_SECRET_KEY` on the first deploy and shows them
   there; log in with that admin password, then set your own in the admin.
   Editable: `VB_PARTY_NAME`, `VB_INSTAGRAM_ACCOUNT`, `VB_EXTENSIONS`,
   `VB_TIMEZONE`, `VB_UPLOADS_PER_IP_PER_MIN`, `VB_NEW_USERS_PER_IP_PER_10MIN`,
   `VB_SCANS_PER_IP_PER_10MIN`, `VB_MIN_FREE_MB`, `VB_MAX_PHOTOS_PER_GUEST`,
   `VB_FORWARDED_ALLOW_IPS` (default: all private ranges), and the build
   variables `VB_ML` (default `1`) and `VB_BAKE_MODELS` (default `0`), which
   need a redeploy.
5. **Storage:** the volume `virtubooth-data` at `/data` holds the database,
   photos, exports and downloaded models. Deleting it deletes the party. The
   container is limited to 2 CPUs and 1.5 GB RAM (`cpus`, `mem_limit` in the
   file; `cpus` must not exceed the server's CPU count).
6. **Deploy.** The build needs about 1 GB of free RAM; the app is healthy
   about 15 s after the start. Then, in the admin (`/admin`):
   Allgemeines → „Öffentliche Adresse“ should say „Erreichbar ✓“;
   ML-Pipeline → **„Modelle herunterladen“** once (about 15 s), then a test
   image in „Testbild“.

To narrow the trusted proxies, set `VB_FORWARDED_ALLOW_IPS` to the subnet of
`docker network inspect coolify --format '{{(index .IPAM.Config 0).Subnet}}'`;
otherwise other containers on Coolify's network could forge
`X-Forwarded-For`. If the admin's connection state stays at „nur Abfrage“, a
proxy buffers the event stream: turn off "Enable Gzip Compression" for the
resource.

Other PaaS: deploy either compose file the same way, route the domain to port
8000 of `app`, keep `/data` on a persistent volume and set the secrets
yourself (`virtubooth gen-env`).

## Settings

All settings are `VB_*` environment variables (Compose: `.env`; Coolify:
Environment Variables). Empty means the default. The app reads only the
process environment, never a `.env` file, and refuses to start with the
variable's name when one is missing or invalid. The event name, the public
address, the look, the admin password and the QR codes are set in the admin
and win over the environment.

| Variable | Default | Purpose |
|---|---|---|
| `VB_ADMIN_PASSWORD` | *required* | The first admin password, at least 12 characters (16+ random recommended; the log warns otherwise). Once changed in the admin, only that one works; `reset-admin-password --from-env` goes back. While none is set in the admin, changing it ends every admin session. |
| `VB_SECRET_KEY` | *required* | Signs cookies, at least 32 characters. Changing it forgets every guest device and makes a stored AI key unreadable. |
| `VB_PARTY_TOKEN` | empty | Read only while the database has no QR code: it becomes QR code 1's token (16–128 of `A-Za-z0-9_-`; empty: generated). Later changes only log a warning. |
| `VB_PARTY_NAME` | `Party` | Default event name; Allgemeines → „Eventname“ overrides it. |
| `VB_INSTAGRAM_ACCOUNT` | empty | The account you may post to, named in the join sheet and on Start. |
| `VB_PUBLIC_BASE_URL` | empty | Public URL without a trailing slash: QR codes and posters (unless „Öffentliche Adresse“ is set), the CSRF origin, `Secure` cookies with `auto`. |
| `VB_EXTENSIONS` | all | Extension ids in order, e.g. `beer,booth,wall`. `wall` is the Live-Wall: list it, or `/livewall` is gone. Unknown ids stop the start. |
| `VB_TIMEZONE` | `Europe/Berlin` | Time in photo and export file names. |
| `VB_CONSENT_VERSION` | `1` | Stored with each join. Bump it when the join texts' promise changes; joined devices are not asked again. |
| `VB_COOKIE_SECURE` | `auto` | `auto` (Secure over https), `true`, `false`. |
| `VB_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies (IPs or CIDR, comma-separated) whose `X-Forwarded-*` count. `*` is refused. |
| `VB_ALLOWED_ORIGINS` | empty | Extra origins for the CSRF check, compared exactly. The only way to allow an `http://` origin on an https deployment. |
| `VB_ADMIN_SESSION_HOURS` | `12` | Admin login lifetime. |
| `VB_MAX_UPLOAD_BYTES` | `8000000` | Size of one upload. |
| `VB_UPLOADS_PER_USER_PER_MIN` | `10` | Uploads per guest per minute (every attempt counts). |
| `VB_UPLOADS_PER_IP_PER_MIN` | `180` | Valid uploads per IP per minute. |
| `VB_UPLOADS_GLOBAL_PER_MIN` | `300` | Valid uploads per minute, whole party. |
| `VB_NEW_USERS_PER_IP_PER_10MIN` | `120` | New guests per IP per 10 minutes. |
| `VB_SCANS_PER_IP_PER_10MIN` | `120` | Counted QR scans per IP per 10 minutes from browsers without a visitor id. Over it they still get in, uncounted until they join. |
| `VB_MAX_PHOTOS_PER_GUEST` | `300` | Photos a guest may keep, all activities; then 403 `photo_limit` and the photo waits on the phone. `0` = no limit. |
| `VB_MIN_FREE_MB` | `2048` | Uploads answer 503 `storage_full` while less is free under `VB_DATA_DIR`. `0` = off. |
| `VB_API_REQUESTS_PER_GUEST_PER_MIN` | `300` | API requests per joined device. |
| `VB_API_REQUESTS_PER_IP_PER_MIN` | `1200` | API requests per IP from devices that have not joined. |
| `VB_DATA_DIR` | `./data` | Database, photos, exports. Docker: `/data`. |
| `VB_WEB_DIR` | `frontend/dist` | The built frontend. Docker: `/app/web`. |
| `VB_DEV` | off | `1`: placeholder pages without a frontend build (development only). |
| `VB_HOST`, `VB_PORT` | `127.0.0.1`, `8000` | Listen address of `virtubooth serve`. Docker: `0.0.0.0`, `8000`. |
| `VB_WALL_WORKER` | on | `off`: don't start the photo analysis worker. |
| `VB_WALL_MODELS_DIR` | empty | Where models are looked up first and fetched to (then `<data>/wall/models`, then `/opt/vb-models`). |
| `VB_WALL_THREADS` | `3` | Threads per inference (`0` = all cores). |
| `VB_PUBLISH_PORT`, `VB_IMAGE`, `VB_CPU_LIMIT`, `VB_MEM_LIMIT` | `127.0.0.1:8000`, `virtubooth:local`, `1.0`, `1g` | `compose.yaml` only: published port, image name, container limits (the Coolify file has fixed 2 CPUs, 1536 MB). |

Guests on one venue Wi-Fi share an IP: joined guests' API requests count per
device, admin sessions are never throttled, and the per-IP upload budget
counts only valid photos. For a big crowd on one network, raise
`VB_UPLOADS_PER_IP_PER_MIN` and `VB_NEW_USERS_PER_IP_PER_10MIN`. The fixed
limits are in [ARCHITECTURE.md → Limits](ARCHITECTURE.md#limits).

## Live-Wall and photo analysis

The Live-Wall works in every image: set its password in Admin → Live-Wall and
open `/livewall` on the TV. Keeping the TV awake (Wake Lock) needs https or
localhost; otherwise switch off the TV's screensaver.

Its categories come from a photo analysis in a worker process the app starts
and supervises. Without the ML packages it computes only brightness, colour
and sharpness. Faces, expressions, hands, gestures and objects need
`VB_ML=1` and the model files:

```bash
docker build --build-arg VB_ML=1 -t virtubooth:ml .                              # ML image
docker build --build-arg VB_ML=1 --build-arg VB_BAKE_MODELS=1 -t virtubooth:ml . # with the models
docker compose run --rm app virtubooth wall models fetch    # or: download into the volume once
```

**„Modelle herunterladen“** (Admin → ML-Pipeline → „Modelle“) does the same as
`models fetch` from the browser: versioned URLs, pinned SHA256, into
`$VB_WALL_MODELS_DIR` or `/data/wall/models`, where they survive redeploys.
It needs outgoing https to `huggingface.co` and `storage.googleapis.com`
(otherwise bake them in with `VB_BAKE_MODELS=1`) and refuses to start when it
would leave less than `VB_MIN_FREE_MB` free. The worker picks the models up
with its next photo. FairFace (age) downloads only once „Alter“ is switched
on, or with `models fetch --with-age`.

The worker runs on the read-only filesystem: the image points the ML caches
at the `/tmp` tmpfs and sets `ORT_DISABLE_TELEMETRY=1` (ONNX Runtime would
otherwise send usage events to Microsoft).

### Image sizes and memory

Measured on x86-64 with the hardening of `docker-compose.coolify.yaml`:

| Image | Pull (compressed) | `docker image ls` |
|---|---|---|
| `VB_ML=0` | 248 MB | 967 MB |
| `VB_ML=1` (Coolify default) | 427 MB | 1.66 GB |
| `VB_ML=1`, `VB_BAKE_MODELS=1` | 535 MB | 1.92 GB |

The standard models are 143.6 MB: CLIP ViT-B/32 int8 (88.6 MB), FER+ emotion
(35.0 MB), MediaPipe gesture recogniser (8.4 MB), EfficientDet-Lite2 int8
(7.5 MB), MediaPipe face landmarker and YuNet (4.0 MB). FairFace age adds
87.3 MB. `virtubooth wall models list` shows what is present.

Memory: the container idles at about 145 MiB without models and 640 MiB once
the worker has loaded them (worker about 0.5 GiB); the peak while analysing
was 660 MiB. The worker restarts itself after 200 photos or above 900 MB.
About 0.3 s per photo on that server; a Raspberry Pi 5 takes 0.4 to 2 s (raise
`VB_MEM_LIMIT` to `2g`, lower `VB_WALL_THREADS` if the booth lags). Licences:
YuNet, FER+ and CLIP MIT; MediaPipe and EfficientDet Apache-2.0; FairFace
Apache-2.0 with CC BY 4.0 data.

### External AI (optional)

Off by default. In Admin → ML-Pipeline → „Claude (KI-Dienst)“ the host enters
an API key (Anthropic, or Mistral AI for an EU service) and switches it on.
The server then needs outgoing https to `api.anthropic.com` or
`api.mistral.ai`. The key is stored encrypted with a key derived from
`VB_SECRET_KEY`, never shown, exported or logged. Set a budget: at the limit
every call stops. Prices are estimates from a table in the code. What is sent
and who is left out: [FEATURES.md → ML-Pipeline](FEATURES.md#ml-pipeline-und-externe-ki).

## Command line

| Command | What |
|---|---|
| `virtubooth serve` | the server (default): `--host`, `--port`, `--forwarded-allow-ips`, `--reload` |
| `virtubooth gen-env` | prints a `.env` with fresh secrets |
| `virtubooth reset-admin-password` | `--from-env`: back to `VB_ADMIN_PASSWORD`; without it asks twice for a new one (or `--password-stdin`). Logs every admin out |
| `virtubooth export-openapi -o FILE` | the OpenAPI schema for the frontend client |
| `virtubooth wall …` | photo analysis: `models fetch [--with-age]`, `models list`, `status`, `run-once`, `worker`, `bench DIR`, `burst` |
| `python -m virtubooth.tools.export` | everything as `.tar.gz`, also while running: `--no-hidden`, `--no-db`, `--out` |
| `python -m virtubooth.tools.timelapse` | the MP4, with more options than the admin (`--crossfade`, `--crf`, `--limit` for a preview, …) |
| `python -m virtubooth.tools.qr` | QR codes and an A4 sheet per activity: `--base-url`, `--code N` or `--token`, `--party-name`, … |

The tools take `--data-dir` and `--help`, write to `<data>/exports/` and keep
their files until you delete them. In Docker: `docker compose exec app …`
while the app runs, `docker compose run --rm app …` while it is stopped;
`docker compose cp app:/data/exports ./exports` copies the files off. In
Coolify, use the app's Terminal.

## Party-night checklist

- Tested on an iPhone and an Android phone on the real domain, also opened
  from inside Instagram or WhatsApp (the page tells guests to use the camera
  app instead).
- Admin → Live shows the test photos and says „verbunden“.
- Allgemeines: event name set, „Öffentliche Adresse“ says „Erreichbar ✓“,
  your own admin password set (not the generated one).
- QR-Codes: only the codes you hang up are active, with the right target.
  Posters printed from the deployed site, one printed code scanned.
- Admin logged in on every device you moderate from, shortly before the party
  (sessions last 12 h).
- Live-Wall: password set (12+ characters), `/livewall` in full screen on the
  TV, ML-Pipeline says the worker runs.
- External AI, if used: key „gesetzt“, budget set, a test image run.
- Free disk well above `VB_MIN_FREE_MB`: `df -h /var/lib/docker`.
- No updates or rebuilds on party night.

## Backups

The volume holds `virtubooth.db` (SQLite, WAL), one photo folder per
activity, `exports/`, `poster/` (the poster template) and `wall/` (models and
the wall's image cache).

**Hot, while running:** Admin → Export → „Archiv erstellen“ with „Datenbank
mitnehmen“, or `python -m virtubooth.tools.export`. The database copy is
consistent (SQLite backup API), without admin sessions, export jobs and
visitor ids, so admins log in again after a restore. The poster template is
not in it.

**Cold, complete** (a few seconds of downtime; on a clean stop the WAL is
written back into `virtubooth.db`):

```bash
docker compose stop
docker run --rm -v virtubooth_data:/data:ro -v "$PWD":/backup alpine:3.22 \
  tar czf /backup/virtubooth-data-$(date +%F).tar.gz -C /data .
docker compose start
```

**Restore** (replaces all current data):

```bash
docker compose down -v && docker compose create
docker run --rm -v virtubooth_data:/data -v "$PWD":/backup:ro alpine:3.22 \
  tar xzf /backup/virtubooth-data-YYYY-MM-DD.tar.gz -C /data
docker compose up -d
```

Backups and database copies hold every photo, the guests' IP addresses and
device traits, the QR tokens and the admin password's hash: keep them like
the printed codes.

## Updating

```bash
git pull
docker compose up -d --build     # rebuilds, then replaces the container
docker image prune -f
```

In Coolify: Redeploy. The volume stays; database migrations run by
themselves on start (numbered, append only). Upgrading a database from before
the QR codes turns `VB_PARTY_TOKEN` into QR code 1, so printed codes keep
working. The join texts gained the external-AI paragraph in migration 11:
when you upgrade an older deployment, bump `VB_CONSENT_VERSION`. Base image
security fixes: `docker compose build --pull`. No updates on party night.

## Secrets and the admin password

- **QR tokens** live in the database. A leaked code: „Token ändern…“ or
  „Löschen…“ in Admin → QR-Codes. It stops working at once; guests who
  already joined through it stay (ban them, or „Anmeldung stoppen“). Reprint
  afterwards. Printed codes are keys: anyone holding one is in.
- **Admin password:** change it in Allgemeines → „Admin-Passwort“; every
  other admin session ends at once. Forgotten:
  `docker compose exec app virtubooth reset-admin-password --from-env`
  (Coolify: the app's Terminal). Every admin is logged out.
- **`VB_SECRET_KEY`:** edit `.env`, `docker compose up -d` (Coolify:
  redeploy). Every guest scans and joins again with a new pseudonym (their
  photos stay), and a stored AI key must be entered again. Change it only if
  it leaked.

**Locked out of the login** („Zu viele Fehlversuche“): after 20 wrong
passwords in 15 minutes from anywhere, every login is refused for 5 minutes,
the correct one too. Logged-in admins keep working. Wait, or restart the
container (`docker compose restart app`): the counters live in memory. A
login sent from inside the container straight to the app's port is exempt;
this prints a session cookie to set as `vb_admin` in the browser:

```bash
docker compose exec app python -c "import json, os, urllib.request as u; r = u.urlopen(u.Request('http://127.0.0.1:8000/api/admin/login', json.dumps({'password': os.environ['VB_ADMIN_PASSWORD']}).encode(), {'Content-Type': 'application/json', 'Origin': 'http://127.0.0.1:8000'})); print(r.headers['Set-Cookie'].split(';')[0])"
```

It uses `VB_ADMIN_PASSWORD`: after a change in the admin, reset with
`--from-env` first. If the lock keeps coming back, someone is guessing: check
`docker compose logs app` for the addresses.

## Teardown

Export and copy off what you keep, then:

```bash
docker compose down -v                # container, network AND the data volume
docker image rm virtubooth:local
rm .env compose.override.yaml
```

Remove the site from the proxy and the DNS record, and delete backups you no
longer need. Hidden photos stay on disk until then.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Every page says „Scan den QR-Code“ | No or an outdated access cookie: open an active code's link (Admin → QR-Codes, „Link kopieren“). |
| The camera does not start | Not HTTPS, permission denied, or an in-app browser. The page names the problem. |
| `403 bad_origin` on join or upload | The proxy rewrites `Host`, or the scheme differs: set `VB_PUBLIC_BASE_URL=https://<host>` and trust the proxy (`VB_FORWARDED_ALLOW_IPS`). |
| Many `429` during the party | Guests share an IP: trust the proxy, raise the per-IP limits. |
| Cookies lack `Secure` behind HTTPS | `VB_COOKIE_SECURE=true`, or trust the proxy so `auto` sees https. |
| The container exits on start | `docker compose logs app` names the `VB_*` variable. "no built frontend was found": `VB_WEB_DIR` must be `/app/web` in Docker. |
| A guest sees „Die Seite startet nicht“ | A content blocker or an old browser; the page says what to do. |
| Admin shows „nur Abfrage“ or „getrennt“ | The proxy buffers the event stream (Coolify: gzip off). Updates still come every 5 s. |
| The log warns about `VB_ADMIN_PASSWORD` | Shorter than 16 characters or repetitive; replace it (`virtubooth gen-env`). |
| Timelapse: „fehlt ffmpeg“ | Outside Docker only: install ffmpeg with libx264. |
| Timelapse: „Keine Fotos für den Zeitraffer“ | The activity has no visible photos; tick „Ausgeblendete Fotos mitnehmen“ or pick another. |
| ML-Pipeline says the ML packages are missing | The image was built with `VB_ML=0`: set `VB_ML=1` and redeploy. |
