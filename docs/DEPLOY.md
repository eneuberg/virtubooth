# Deploying virtubooth on a server

This guide takes virtubooth from a fresh Linux server with Docker to a
party-ready HTTPS site, and covers backups, updates, token rotation and
teardown. Settings are documented in [.env.example](../.env.example), the
architecture in [ARCHITECTURE.md](ARCHITECTURE.md).

```
phone ──HTTPS──▶ reverse proxy (TLS, your domain) ──HTTP──▶ app container :8000 ──▶ volume virtubooth_data (/data)
                 Caddy / Traefik / nginx / Coolify          one process, one worker      SQLite + photos
```

> **One container, one worker.** Rate limits and the live event bus are kept
> in memory. Never scale the service, add replicas or run more workers; a
> PaaS "scale" button would break the live screens and rate limiting.

## 1. Requirements

- A Linux server with **Docker Engine 25+** and the **Compose plugin**
  (`docker compose version`). 1 vCPU and 1 GB RAM are plenty for ~50 guests.
- Disk: up to about 0.5 MB per photo (full size + thumbnail), so 1 GB
  holds at least 2000 photos. The image is about 900 MB (230 MB download), mostly
  ffmpeg.
- A domain (e.g. `party.example.com`) with an A/AAAA record pointing at the
  server, and ports 80 and 443 open for the reverse proxy's certificates.

## 2. Get the code onto the server

```bash
git clone <your repo url> ~/virtubooth && cd ~/virtubooth
```

Or copy it from your machine without local junk:

```bash
rsync -a --exclude .git --exclude .venv --exclude .worktrees --exclude data \
  --exclude .env ./ server:virtubooth/
```

## 3. Configure

```bash
cd ~/virtubooth
docker compose run --rm -T app virtubooth gen-env > .env   # builds the image, prints fresh secrets
chmod 600 .env
$EDITOR .env
```

Set at least:

```dotenv
VB_PARTY_NAME="Lenas 30."
VB_INSTAGRAM_ACCOUNT=@lenas30
VB_PUBLIC_BASE_URL=https://party.example.com
VB_COOKIE_SECURE=true
VB_FORWARDED_ALLOW_IPS=172.16.0.0/12   # see step 5
VB_PUBLISH_PORT=127.0.0.1:8000         # proxy on this host; omit for a proxy in Docker (step 5.2)
```

`VB_DATA_DIR=./data` from `gen-env` is harmless: `compose.yaml` pins
`VB_DATA_DIR=/data`, `VB_HOST=0.0.0.0` and `VB_PORT=8000` inside the
container. Quote values with spaces (`"Lenas 30."`). Compose expands `$` in
`.env` values, so keep `$` out of passwords or wrap the value in single
quotes.

## 4. Start

```bash
docker compose up -d --build
docker compose ps                         # STATUS shows "(healthy)" after a few seconds
curl -fsS http://127.0.0.1:8000/healthz   # {"ok":true}
docker compose logs -f app                # Ctrl-C to stop following
```

The container restarts automatically after crashes and reboots
(`restart: unless-stopped`). Data lives in the named volume
`virtubooth_data`, owned by the container user (uid 10001).

## 5. Put a reverse proxy in front

Phones only allow the camera on HTTPS, so the proxy is not optional. Whatever
you use, it must:

1. **Terminate TLS** for your domain.
2. **Pass the original `Host` header** (the CSRF check compares `Origin` with
   `Host`; otherwise every POST gets `403 bad_origin`). If you cannot, set
   `VB_ALLOWED_ORIGINS=https://party.example.com`.
3. **Send `X-Forwarded-For` and `X-Forwarded-Proto`**, and the app must
   trust them: `VB_FORWARDED_ALLOW_IPS` lists the proxy's address as the
   container sees it. Otherwise every guest looks like the proxy, so the
   per-IP rate limits throttle the whole party together.
4. **Not buffer Server-Sent Events** (live screens). The app sends
   `X-Accel-Buffering: no` and a heartbeat every 15 s.
5. **Allow request bodies of at least 8 MB** (`VB_MAX_UPLOAD_BYTES`).

Which address to trust: a proxy on the host reaches a `127.0.0.1` published
port through Docker's bridge gateway (e.g. `172.19.0.1`); a proxy container
connects from its address in the shared network. `172.16.0.0/12` covers
Docker's default networks. To be exact, run one proxied request and read the
client address in `docker compose logs app`, or:

```bash
docker network inspect virtubooth_default --format '{{(index .IPAM.Config 0).Gateway}}'   # proxy on the host
docker network inspect proxy --format '{{(index .IPAM.Config 0).Subnet}}'                 # proxy in network "proxy"
```

Docker's published ports bypass ufw and firewalld: publish on `127.0.0.1`
(or not at all) so the plain-HTTP port is not reachable from the internet.

### 5.1 Caddy on the host (simplest)

Install Caddy from your distribution or [caddyserver.com](https://caddyserver.com/docs/install),
then `/etc/caddy/Caddyfile`:

```caddyfile
party.example.com {
	reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

Caddy gets and renews the certificate, keeps the `Host` header, sets
`X-Forwarded-For`/`-Proto`, streams SSE and has no body size limit. Do not add
`encode` for this site (compressing the event stream can delay live
updates; photos are JPEG anyway). In `.env`:
`VB_PUBLISH_PORT=127.0.0.1:8000` and `VB_FORWARDED_ALLOW_IPS=172.16.0.0/12`
(or the gateway address from above), then `docker compose up -d`.

### 5.2 Traefik (container, Docker labels)

Assuming Traefik already runs with the Docker provider, an entrypoint
`websecure` (443), a certificate resolver `letsencrypt` and an external
network `proxy`. Create `compose.override.yaml` next to `compose.yaml`
(Compose loads it automatically):

```yaml
services:
  app:
    ports: !reset []          # no host port: only Traefik can reach the app
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

Traefik keeps the `Host` header, sets the forwarded headers and streams SSE.
In `.env` set `VB_FORWARDED_ALLOW_IPS` to the `proxy` network's subnet (see
above). Then `docker compose up -d`.

### 5.3 nginx

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name party.example.com;
    # ssl_certificate / ssl_certificate_key: e.g. from certbot

    client_max_body_size 10m;            # uploads up to 8 MB

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;     # required for the CSRF origin check
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 1h;           # long-lived live streams (SSE)
    }
}
```

The app's `X-Accel-Buffering: no` header turns off nginx buffering for the
event streams. nginx's default 1 MB body limit would reject photo uploads
with `413`, hence `client_max_body_size`.

### 5.4 Coolify and other PaaS

Deploy the repository as a Docker Compose application, set the domain to
port `8000` of service `app`, and put the variables from `.env` into the
environment settings. Keep the `data` volume, do not enable replicas or
horizontal scaling, and set `VB_FORWARDED_ALLOW_IPS` to the subnet of the
network the platform's proxy shares with the app (`docker network inspect`
on the server).

### 5.5 Check the setup

```bash
curl -fsS https://party.example.com/healthz                                # {"ok":true}
curl -s -o /dev/null -w '%{http_code}\n' https://party.example.com/       # 404 (the "Scan den QR-Code" page)
curl -s -o /dev/null -D - "https://party.example.com/?t=$TOKEN" | grep -i set-cookie   # vb_access=...; Secure
docker compose logs --tail 5 app    # client addresses are your own public IP, not 172.x
```

Then open `https://party.example.com/?t=<token>` on a phone and walk through
consent, Beer Cam and Fotobox ([testing on a real phone](../README.md#testing-on-a-real-phone-before-party-night)),
and log in at `https://party.example.com/admin`.

## 6. Party-night checklist

- Tested on an iPhone and an Android phone on the real domain, and the
  admin live screen shows the test uploads.
- QR codes [printed](../README.md#printing-the-qr-codes) from the deployed
  config; scan one printed code before the guests arrive.
- Admin logged in on a laptop or tablet; the password is not on any
  printout.
- Enough disk space: `df -h /var/lib/docker`.
- No updates or rebuilds on party night.

## 7. Backups

Everything is in the `virtubooth_data` volume: `virtubooth.db` (SQLite, WAL
mode) plus one folder of photos per activity.

**Hot, while the app runs.** A consistent copy of the database (SQLite's
backup API) plus the export tool for the photos:

```bash
docker compose exec app python -c "import os, sqlite3; os.makedirs('/data/exports', exist_ok=True); sqlite3.connect('/data/virtubooth.db').backup(sqlite3.connect('/data/exports/virtubooth-backup.db'))"
docker compose exec app python -m virtubooth.tools.export
docker compose cp app:/data/exports ./backup-$(date +%F)
```

**Cold, complete.** Stop the app so the SQLite files are consistent, archive
the volume, start again (a few seconds of downtime):

```bash
docker compose stop
docker run --rm -v virtubooth_data:/data:ro -v "$PWD":/backup alpine:3.22 \
  tar czf /backup/virtubooth-data-$(date +%F).tar.gz -C /data .
docker compose start
```

**Restore** from a cold backup (replaces all current data; the archive
keeps the uid 10001 ownership):

```bash
docker compose down -v                    # deletes the current data volume!
docker compose create                     # new, empty volume + container
docker run --rm -v virtubooth_data:/data -v "$PWD":/backup:ro alpine:3.22 \
  tar xzf /backup/virtubooth-data-YYYY-MM-DD.tar.gz -C /data
docker compose up -d
```

Copy backups off the server (`scp`/`rsync`): they contain every photo and
guest record, so store them like the photos themselves.

## 8. Updating

```bash
cd ~/virtubooth
git pull                                  # or rsync the new code
docker compose up -d --build              # rebuilds, then replaces the container (seconds of downtime)
docker compose ps                         # healthy again?
docker image prune -f                     # drop the old, now untagged image
```

The data volume is untouched by updates. To pick up security fixes of the
base image and ffmpeg, rebuild with `docker compose build --pull` and then
`docker compose up -d`. The Python and uv versions are pinned at the top of
the `Dockerfile`.

## 9. Rotating the party token

Rotate it when a QR code leaked, or after the party to close the booth.

```bash
docker compose run --rm -T app python -c "import secrets; print(secrets.token_urlsafe(18))"
$EDITOR .env                              # VB_PARTY_TOKEN=<new value>
docker compose up -d                      # recreates the container with the new env
```

`docker compose restart` does **not** re-read `.env`; `up -d` does. Every
guest has to scan a new QR code (their pseudonym and photos stay theirs, as
that cookie is signed with `VB_SECRET_KEY`, not the token). Print new codes
afterwards.

Other secrets work the same way:

- `VB_ADMIN_PASSWORD`: ends all admin sessions.
- `VB_SECRET_KEY`: forgets every guest device and access cookie (everyone
  scans again, accepts the consent again and gets a new pseudonym; existing
  photos stay but are no longer linked to a device). Only change it if it
  leaked.

## 10. Logs and monitoring

```bash
docker compose ps                     # health status
docker compose logs -f --since 10m app
docker stats                          # CPU / memory against the limits in compose.yaml
```

Logs rotate at 5 x 10 MB. The access log contains the `?t=<token>` of every
QR scan, so share logs as carefully as `.env`. Limits (`VB_CPU_LIMIT`,
`VB_MEM_LIMIT`) are set in `.env`; the CPU limit must not exceed the
server's CPU count or Docker refuses to start the container.

## 11. Teardown

After the party, once you have exported and copied off what you want to keep
([after the party](../README.md#after-the-party)):

```bash
docker compose down -v                # container, network, logs AND the data volume: irreversible
docker image rm virtubooth:local      # or your VB_IMAGE
rm .env compose.override.yaml         # secrets, proxy override
```

Then remove the site from the reverse proxy, delete the DNS record, and
delete backups and exports you no longer need. Guests' access cookies become
useless once the domain is gone.
