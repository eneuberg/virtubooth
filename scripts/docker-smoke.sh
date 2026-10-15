#!/usr/bin/env bash
# Smoke-test the container image: build it, run it like compose.yaml does
# (read-only root, no capabilities, a fresh named volume, fresh secrets from
# `virtubooth gen-env`), run scripts/smoke.py against it, run the CLI tools
# inside it, stop it (the stop must be clean and quick), remove everything.
#
#   scripts/docker-smoke.sh                       # build + smoke on 127.0.0.1:8180
#   VB_SMOKE_BUILD=0 VB_SMOKE_IMAGE=virtubooth:local scripts/docker-smoke.sh
#   VB_SMOKE_SCREENSHOTS=/tmp/shots scripts/docker-smoke.sh   # + Chromium screenshots
#
# Settings (environment): VB_SMOKE_PORT (8180), VB_SMOKE_IMAGE (virtubooth:smoke),
# VB_SMOKE_NAME (virtubooth-smoke-<port>), VB_SMOKE_BUILD (1), VB_SMOKE_SCREENSHOTS,
# DOCKER_BUILD_FLAGS (extra `docker build` arguments, e.g. --network=host).
# Needs Docker and uv (the checker runs in backend/'s environment).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${VB_SMOKE_PORT:-8180}"
IMAGE="${VB_SMOKE_IMAGE:-virtubooth:smoke}"
NAME="${VB_SMOKE_NAME:-virtubooth-smoke-$PORT}"
VOLUME="$NAME-data"
WORK="$(mktemp -d)"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker volume rm -f "$VOLUME" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT
cleanup_needed=$(docker ps -aq --filter "name=^${NAME}$")
if [ -n "$cleanup_needed" ]; then docker rm -f "$NAME" >/dev/null; fi

if [ "${VB_SMOKE_BUILD:-1}" = 1 ]; then
  echo "== docker build -t $IMAGE"
  # shellcheck disable=SC2086  # DOCKER_BUILD_FLAGS is a list of arguments
  docker build ${DOCKER_BUILD_FLAGS:-} -t "$IMAGE" "$ROOT"
fi
size=$(docker image inspect -f '{{.Size}}' "$IMAGE")
echo "== image $IMAGE: $((size / 1000000)) MB (compressed)"
# the image itself: unprivileged, no dev mode baked in (security review SEC-08)
[ "$(docker image inspect -f '{{.Config.User}}' "$IMAGE")" = 10001:10001 ] \
  || { echo "FAIL  the image must run as USER 10001:10001" >&2; exit 1; }
if grep -q '^VB_DEV=' <<<"$(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$IMAGE")"; then
  echo "FAIL  the image sets VB_DEV" >&2
  exit 1
fi
echo "  ok  image: USER 10001:10001, no VB_DEV"

# fresh secrets; the QR codes point at this test instance
docker run --rm "$IMAGE" virtubooth gen-env \
  | sed "s|^VB_PUBLIC_BASE_URL=.*|VB_PUBLIC_BASE_URL=http://127.0.0.1:$PORT|" >"$WORK/test.env"

echo "== docker run $NAME on 127.0.0.1:$PORT"
docker volume create "$VOLUME" >/dev/null
docker run -d --name "$NAME" --init \
  --env-file "$WORK/test.env" \
  -p "127.0.0.1:$PORT:8000" \
  -v "$VOLUME:/data" \
  --read-only --tmpfs /tmp:size=256m,mode=1777 \
  --cap-drop ALL --security-opt no-new-privileges:true \
  --memory 1g --pids-limit 512 \
  "$IMAGE" >/dev/null

for _ in $(seq 1 60); do
  health=$(docker inspect -f '{{.State.Health.Status}}' "$NAME")
  [ "$health" = healthy ] && break
  if [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" != true ]; then
    docker logs "$NAME" >&2
    echo "FAIL  the container exited" >&2
    exit 1
  fi
  sleep 1
done
[ "$health" = healthy ] || { docker logs "$NAME" >&2; echo "FAIL  never healthy ($health)" >&2; exit 1; }
echo "  ok  container healthy (Docker HEALTHCHECK)"
[ "$(docker exec "$NAME" id -u)" = 10001 ] || { echo "FAIL  not running as uid 10001" >&2; exit 1; }
echo "  ok  runs as uid 10001 on a read-only root filesystem"
[ "$(docker exec "$NAME" ls -A /app)" = web ] \
  || { echo "FAIL  /app holds more than the frontend build" >&2; exit 1; }
docker exec "$NAME" sh -c 'test -z "$(find /app /opt/venv -name .env -o -name "*.env" | head -1)"' \
  || { echo "FAIL  an .env file ended up in the image" >&2; exit 1; }
echo "  ok  /app holds only the frontend build; no .env in the image"

# The HEALTHCHECK runs inside the container's network namespace; smoke.py talks
# to the published port from the host. Check that path first, so a host that
# cannot reach Docker's bridge network fails here with a diagnosis instead of a
# bare timeout in smoke.py.
probe() {  # probe URL → 0 when it answers 200 within 3 s
  uv run --quiet --project "$ROOT/backend" python -c '
import sys, urllib.request
try:
    sys.exit(urllib.request.urlopen(sys.argv[1], timeout=3).status != 200)
except Exception as exc:
    print(f"      {sys.argv[1]}: {exc!r}", file=sys.stderr)
    sys.exit(1)' "$1"
}
reachable=0
for _ in 1 2 3; do
  if probe "http://127.0.0.1:$PORT/healthz" 2>"$WORK/probe.err"; then reachable=1; break; fi
  sleep 1
done
if [ "$reachable" != 1 ]; then
  cat "$WORK/probe.err" >&2
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$NAME" | awk '{print $1}')
  if [ -z "$ip" ]; then
    echo "FAIL  the container is healthy, but the host gets no answer on 127.0.0.1:$PORT" >&2
  elif ! probe "http://$ip:8000/healthz"; then
    echo "FAIL  the container is healthy (its HEALTHCHECK answers inside it), but the" \
      "host reaches neither 127.0.0.1:$PORT nor its bridge address $ip:8000. Most" \
      "likely a host firewall drops traffic to Docker's bridge networks, e.g. a VPN" \
      "kill switch with LAN access blocked (IVPN, Mullvad, ...): allow LAN traffic" \
      "or 172.16.0.0/12 and rerun." >&2
  else
    echo "FAIL  the container answers on its bridge address $ip:8000, but not on the" \
      "published port 127.0.0.1:$PORT (port publishing / docker-proxy)" >&2
  fi
  exit 1
fi
echo "  ok  the published port 127.0.0.1:$PORT answers from the host"

shots=()
if [ -n "${VB_SMOKE_SCREENSHOTS:-}" ]; then shots=(--screenshots "$VB_SMOKE_SCREENSHOTS"); fi
uv run --quiet --project "$ROOT/backend" python "$ROOT/scripts/smoke.py" \
  --url "http://127.0.0.1:$PORT" --env-file "$WORK/test.env" "${shots[@]}"

echo "cli tools inside the container"
docker exec "$NAME" python -m virtubooth.tools.qr --out /data/exports/qr-cli >/dev/null
docker exec "$NAME" test -f /data/exports/qr-cli/qr-sheet.html
echo "  ok  python -m virtubooth.tools.qr"
docker exec "$NAME" python -m virtubooth.tools.timelapse --dry-run >/dev/null
echo "  ok  python -m virtubooth.tools.timelapse --dry-run"
docker exec "$NAME" python -m virtubooth.tools.export --out /data/exports/cli.tar.gz >/dev/null
docker exec "$NAME" test -s /data/exports/cli.tar.gz
echo "  ok  python -m virtubooth.tools.export"

echo "stop"
start=$(date +%s)
docker stop -t 15 "$NAME" >/dev/null
took=$(($(date +%s) - start))
code=$(docker inspect -f '{{.State.ExitCode}}' "$NAME")
# uvicorn shuts down gracefully, then re-raises the SIGTERM: 143 (128 + 15) is
# the normal exit code of `docker stop`; 137 would mean it had to be killed
if { [ "$code" != 0 ] && [ "$code" != 143 ]; } || [ "$took" -ge 15 ]; then
  docker logs --tail 20 "$NAME" >&2
  echo "FAIL  stop: exit code $code after ${took}s" >&2
  exit 1
fi
# read the log first: `grep -q` stops at the first match, and with pipefail the
# SIGPIPE that `docker logs` gets then fails the pipe although the line is there
logs=$(docker logs "$NAME" 2>&1)
grep -q "Application shutdown complete" <<<"$logs" \
  || { tail -n 40 <<<"$logs" >&2; echo "FAIL  no clean shutdown in the log" >&2; exit 1; }
echo "  ok  stopped cleanly in ${took}s (exit code $code, application shutdown complete)"
echo "docker-smoke: all checks passed"
