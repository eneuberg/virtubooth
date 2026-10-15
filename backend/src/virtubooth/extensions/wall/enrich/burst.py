"""Upload burst (REQUIREMENTS §4 „queue behaviour“): many guests upload at once
while the analysis worker runs. Does the low-priority, one-photo-at-a-time
queue keep uploads fast, and is every photo analysed exactly once?

Each phase starts a fresh party: the app in this process (uvicorn on a free
127.0.0.1 port, a plain upload activity plus the Live-Wall), with the real
worker process the wall's supervisor spawns (`with_worker`) or none
(`VB_WALL_WORKER=off`). `clients` guests join and each uploads
`photos / clients` JPEGs in parallel; a sampler records the most rows that
were `running` at once. `compare()` runs both phases and waits for the
queue to drain.

CLI: `python -m virtubooth.extensions.wall.enrich burst --clients 20 --photos 60`.
"""

from __future__ import annotations

import http.cookiejar
import io
import json
import os
import random
import socket
import statistics
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ....db.database import Database

TOKEN = "burst-party-token-0123456789"
SECRET = "burst-secret-key-0123456789abcdef0123456789"
PASSWORD = "burst-admin-password-123"
EXT = "burst"


@dataclass
class Phase:
    with_worker: bool
    uploads: int
    errors: int
    wall_s: float  # the whole burst, first request to last answer
    p50_ms: float
    p95_ms: float
    max_ms: float
    max_running: int  # most `running` rows seen at once
    analysed: int = 0  # photos done/failed/skipped at the end
    drain_s: float | None = None  # last upload → queue empty
    attempts: dict[int, int] = field(default_factory=dict)  # attempts → photos
    local_runs: int = 0  # `local` rows in photo_detection_runs
    ml: bool = False  # the worker ran ML analyzers (models present)
    analysis_ms: float | None = None  # mean pipeline time per photo (sum of the analyzers)


def party_jpeg(rnd: random.Random, size: tuple[int, int] = (1280, 960)) -> bytes:
    """A colourful synthetic party photo (shapes on a gradient), ~150-300 KB."""
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(0, h, 8):
        c = int(255 * y / h)
        draw.rectangle([0, y, w, y + 8], fill=(c, 40 + rnd.randrange(60), 255 - c))
    for _ in range(25):
        x0, y0 = rnd.randrange(w), rnd.randrange(h)
        x1, y1 = x0 + rnd.randrange(30, 300), y0 + rnd.randrange(30, 300)
        fill = (rnd.randrange(256), rnd.randrange(256), rnd.randrange(256))
        if rnd.random() < 0.5:
            draw.ellipse([x0, y0, x1, y1], fill=fill)
        else:
            draw.rectangle([x0, y0, x1, y1], fill=fill)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Guest:
    """One phone: its own cookie jar."""

    def __init__(self, base: str, n: int) -> None:
        self.base = base
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()), _NoRedirect()
        )
        self.n = n

    def _req(self, method: str, path: str, body: bytes | None, headers: dict[str, str]) -> int:
        req = urllib.request.Request(self.base + path, data=body, method=method,
                                     headers={"Origin": self.base, **headers})  # fmt: skip
        try:
            with self.opener.open(req, timeout=60) as resp:
                resp.read()
                return int(resp.status)
        except urllib.error.HTTPError as exc:
            exc.read()
            return int(exc.code)

    def join(self) -> None:
        self._req("GET", f"/?t={TOKEN}", None, {})
        fp = {"hash": f"{self.n:064x}", "components": {"ua": "burst", "screen": "390x844@3"}}
        body = json.dumps({"accept": True, "version": "1", "fp": fp}).encode()
        status = self._req("POST", "/api/join", body, {"Content-Type": "application/json"})
        if status not in (200, 201):
            raise RuntimeError(f"join failed: {status}")

    def upload(self, jpeg: bytes) -> tuple[int, float]:
        started = time.perf_counter()
        status = self._req("POST", f"/api/x/{EXT}/upload", jpeg, {"Content-Type": "image/jpeg"})
        return status, (time.perf_counter() - started) * 1000


@contextmanager
def _server(data_dir: Path, *, with_worker: bool) -> Iterator[str]:
    import uvicorn

    from ....app import create_app
    from ....extensions.sdk import Extension, UploadPolicy
    from ....settings import Settings
    from .. import make_extension

    old = os.environ.get("VB_WALL_WORKER")
    os.environ["VB_WALL_WORKER"] = "on" if with_worker else "off"
    settings = Settings(
        _env_file=None, party_token=TOKEN, admin_password=PASSWORD, secret_key=SECRET,
        data_dir=data_dir, web_dir=None, dev=True, uploads_per_user_per_min=100,
        uploads_per_ip_per_min=10_000, uploads_global_per_min=10_000,
        new_users_per_ip_per_10min=10_000, api_requests_per_ip_per_min=100_000,
        api_requests_per_guest_per_min=10_000,
    )  # fmt: skip
    upload_ext = Extension(id=EXT, title="Burst", emoji="📷", tagline="Lasttest",
                           upload=UploadPolicy())  # fmt: skip
    app = create_app(settings, extensions=[upload_ext, make_extension()])
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           timeout_graceful_shutdown=2))  # fmt: skip
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.02)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(15)
        app.state.core.db.close()
        if old is None:
            os.environ.pop("VB_WALL_WORKER", None)
        else:
            os.environ["VB_WALL_WORKER"] = old


class _Sampler:
    """Polls the database for rows in `running` (a second connection)."""

    def __init__(self, db_path: Path, every_s: float = 0.02) -> None:
        self.db_path = db_path
        self.every_s = every_s
        self.max_running = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        db = Database(self.db_path)
        try:
            while not self._stop.is_set():
                row = db.one("SELECT COUNT(*) FROM wall_analysis WHERE state='running'")
                self.max_running = max(self.max_running, int(row[0]) if row else 0)
                self._stop.wait(self.every_s)
        finally:
            db.close()

    def __enter__(self) -> _Sampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(5)


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return ordered[k]


def run_phase(
    clients: int, photos: int, *, with_worker: bool, drain_timeout_s: float = 600,
    data_dir: Path | None = None, log: Callable[[str], None] = lambda _m: None,
) -> Phase:  # fmt: skip
    """One burst on a fresh party; with the worker, waits for the queue to
    drain (at most `drain_timeout_s`) and checks every photo's analysis."""
    rnd = random.Random(15)
    per = max(1, photos // clients)
    images = [party_jpeg(rnd) for _ in range(min(per * clients, 12))]
    with tempfile.TemporaryDirectory(dir=data_dir) as tmp:
        data = Path(tmp) / "data"
        with _server(data, with_worker=with_worker) as base:
            guests = [Guest(base, i + 1) for i in range(clients)]
            for g in guests:
                g.join()
            if with_worker:  # the worker is up before the burst starts
                _wait_for_worker(data / "virtubooth.db", 30)
            latencies: list[float] = []
            errors = [0]
            lock = threading.Lock()
            go = threading.Barrier(clients + 1)

            def client(g: Guest, k: int) -> None:
                go.wait()
                for j in range(per):
                    status, ms = g.upload(images[(k * per + j) % len(images)])
                    with lock:
                        if status == 201:
                            latencies.append(ms)
                        else:
                            errors[0] += 1

            db_path = data / "virtubooth.db"
            with _Sampler(db_path) as sampler:
                threads = [threading.Thread(target=client, args=(g, k))
                           for k, g in enumerate(guests)]  # fmt: skip
                for t in threads:
                    t.start()
                go.wait()
                started = time.perf_counter()
                for t in threads:
                    t.join()
                wall_s = time.perf_counter() - started
                log(f"{'with' if with_worker else 'without'} worker: {len(latencies)} uploads "
                    f"in {wall_s:.1f} s")  # fmt: skip
                drain_s = None
                if with_worker:
                    drain_s = _drain(db_path, drain_timeout_s)
                    log(f"queue drained {drain_s:.1f} s after the last upload"
                        if drain_s is not None else "queue NOT drained")  # fmt: skip
            phase = Phase(
                with_worker=with_worker, uploads=len(latencies), errors=errors[0],
                wall_s=round(wall_s, 2), p50_ms=round(statistics.median(latencies or [0]), 1),
                p95_ms=round(_pct(latencies, 0.95), 1), max_ms=round(max(latencies or [0]), 1),
                max_running=sampler.max_running,
                drain_s=round(drain_s, 1) if drain_s is not None else None,
            )  # fmt: skip
            _check(db_path, phase)
    return phase


def _wait_for_worker(db_path: Path, timeout_s: float) -> None:
    db = Database(db_path)
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if db.one("SELECT 1 FROM settings WHERE key='x.wall.worker'"):
                return
            time.sleep(0.1)
        raise RuntimeError("the analysis worker did not start")
    finally:
        db.close()


def _drain(db_path: Path, timeout_s: float) -> float | None:
    db = Database(db_path)
    started = time.perf_counter()
    try:
        while time.perf_counter() - started < timeout_s:
            row = db.one(
                "SELECT COUNT(*) FROM photos p LEFT JOIN wall_analysis a ON a.photo_id = p.id "
                "WHERE p.deleted_at IS NULL AND (a.photo_id IS NULL OR a.state IN "
                "('pending', 'running'))"
            )
            if row is not None and int(row[0]) == 0:
                return time.perf_counter() - started
            time.sleep(0.1)
        return None
    finally:
        db.close()


def _check(db_path: Path, phase: Phase) -> None:
    db = Database(db_path)
    try:
        phase.analysed = int(db.one(
            "SELECT COUNT(*) FROM wall_analysis WHERE state IN ('done', 'failed', 'skipped')"
        )[0])  # fmt: skip
        phase.attempts = {int(r[0]): int(r[1]) for r in db.all(
            "SELECT attempts, COUNT(*) FROM wall_analysis GROUP BY attempts"
        )}  # fmt: skip
        phase.local_runs = int(db.one(
            "SELECT COUNT(*) FROM photo_detection_runs WHERE source='local'"
        )[0])  # fmt: skip
        totals: list[float] = []
        for row in db.all("SELECT versions, data FROM wall_analysis WHERE state='done'"):
            if any(k != "basic" for k in json.loads(row[0] or "{}")):
                phase.ml = True
            durations = json.loads(row[1] or "{}").get("durations_ms") or {}
            totals.append(float(sum(durations.values())))
        phase.analysis_ms = round(statistics.mean(totals), 1) if totals else None
    finally:
        db.close()


def compare(clients: int, photos: int, *, log: Callable[[str], None] = lambda _m: None,
            data_dir: Path | None = None) -> dict[str, Any]:  # fmt: skip
    without = run_phase(clients, photos, with_worker=False, log=log, data_dir=data_dir)
    with_ = run_phase(clients, photos, with_worker=True, log=log, data_dir=data_dir)
    limit = 1.5 * without.p95_ms + 100
    return {
        "clients": clients,
        "photos": clients * max(1, photos // clients),
        "without_worker": asdict(without),
        "with_worker": asdict(with_),
        "p95_limit_ms": round(limit, 1),
        "p95_ok": with_.p95_ms <= limit,
    }


def render(result: dict[str, Any]) -> str:
    a, b = result["without_worker"], result["with_worker"]
    lines = [
        f"{result['clients']} clients, {result['photos']} uploads",
        f"{'':18}{'without worker':>16}{'with worker':>16}",
    ]
    for key, title in [("uploads", "uploads ok"), ("errors", "errors"), ("wall_s", "burst (s)"),
                       ("p50_ms", "p50 (ms)"), ("p95_ms", "p95 (ms)"), ("max_ms", "max (ms)"),
                       ("max_running", "max running")]:  # fmt: skip
        lines.append(f"{title:18}{a[key]!s:>16}{b[key]!s:>16}")
    lines += [
        f"p95 limit (1.5 x p95 without + 100 ms): {result['p95_limit_ms']} ms -> "
        f"{'OK' if result['p95_ok'] else 'TOO SLOW'}",
        f"with worker: {b['analysed']} analysed, attempts {b['attempts']}, "
        f"{b['local_runs']} local runs, drained {b['drain_s']} s after the burst, "
        f"ML analyzers: {'yes' if b['ml'] else 'no (basic only)'}, "
        f"{b['analysis_ms']} ms analysis per photo",
    ]
    return "\n".join(lines)
