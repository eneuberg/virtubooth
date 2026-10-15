"""Keeps the analysis worker process running (inside the app process).

`start()` spawns `python -m virtubooth.extensions.wall.enrich worker --data-dir …`
with stdin a pipe (the worker exits on EOF, so it never outlives the app) and a
thread that restarts it: exit 75 (recycling) at once, anything else after a
backoff of 2 s doubling to 60 s (reset after a minute of running).
`VB_WALL_WORKER=off` never spawns (tests, or a worker in another container).
`stop()`: close stdin, SIGTERM, wait 5 s, SIGKILL.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from .analyzers import thread_limit
from .worker import EXIT_RECYCLE

log = logging.getLogger("virtubooth.wall.enrich")

WORKER_ENV = "VB_WALL_WORKER"
SupervisorState = Literal["starting", "running", "stopped", "crashed", "off"]
# alive this long → "running"
RUNNING_AFTER_S = 2.0
STABLE_AFTER_S = 60.0
# never handed to the worker: it reads stored photos with native ML code (the
# app's biggest decoder surface) and needs none of the app's secrets. Without
# VB_SECRET_KEY it can't forge cookies or decrypt what the app encrypts with
# it (security review 3, ENV-01). Plus every *_API_KEY / *_SECRET variable.
SECRET_ENV = frozenset({"VB_SECRET_KEY", "VB_ADMIN_PASSWORD", "VB_PARTY_TOKEN"})


def worker_disabled() -> bool:
    return os.environ.get(WORKER_ENV, "").strip().lower() in ("off", "0", "false", "no")


def is_secret_env(name: str) -> bool:
    """A variable the worker must not inherit (SECRET_ENV, *_API_KEY, *_SECRET)."""
    upper = name.upper()
    return upper in SECRET_ENV or upper.endswith(("_API_KEY", "_SECRET"))


def worker_command(data_dir: Path) -> list[str]:
    return [sys.executable, "-m", "virtubooth.extensions.wall.enrich", "worker",
            "--data-dir", str(data_dir)]  # fmt: skip


class Supervisor:
    def __init__(
        self,
        data_dir: Path,
        *,
        cmd: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        min_backoff: float = 2.0,
        max_backoff: float = 60.0,
        stop_timeout: float = 5.0,
    ) -> None:
        self.cmd = list(cmd) if cmd is not None else worker_command(data_dir)
        self.env = dict(env) if env is not None else None
        self.min_backoff = min_backoff
        self.max_backoff = max_backoff
        self.stop_timeout = stop_timeout
        self.state: SupervisorState = "off" if worker_disabled() else "stopped"
        self.message: str | None = None
        self.pid: int | None = None
        self.restarts = 0
        self.last_exit: int | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._lock = threading.Lock()

    def _child_env(self) -> dict[str, str]:
        env = {
            k: v
            for k, v in (os.environ if self.env is None else self.env).items()
            if not is_secret_env(k)
        }
        if threads := thread_limit():
            env.setdefault("OMP_NUM_THREADS", str(threads))
        env.setdefault("MPLBACKEND", "Agg")
        env.setdefault("PYTHONUNBUFFERED", "1")
        return env

    def start(self) -> None:
        if worker_disabled():
            self.state = "off"
            self.message = None
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="wall-enrich", daemon=True)
        self._thread.start()

    def _spawn(self) -> subprocess.Popen[bytes] | None:
        try:
            proc = subprocess.Popen(self.cmd, stdin=subprocess.PIPE, env=self._child_env())
        except OSError as exc:
            log.error("cannot start the analysis worker: %s", exc)
            self.message = f"Analyse-Prozess startet nicht: {exc.strerror or exc}"
            return None
        with self._lock:
            self._proc = proc
            self.pid = proc.pid
        return proc

    def _loop(self) -> None:
        backoff = self.min_backoff
        while not self._stopping.is_set():
            self.state = "starting"
            started = time.monotonic()
            proc = self._spawn()
            code: int | None = None
            if proc is not None:
                while code is None:
                    try:
                        code = proc.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        if (
                            self.state == "starting"
                            and time.monotonic() - started >= RUNNING_AFTER_S
                        ):
                            self.state = "running"
                            self.message = None
            if self._stopping.is_set():
                break
            self.last_exit = code
            self.restarts += 1
            if code == EXIT_RECYCLE:
                log.info("analysis worker recycled itself, restarting")
                backoff = self.min_backoff
                continue
            if time.monotonic() - started >= STABLE_AFTER_S:
                backoff = self.min_backoff
            log.warning("analysis worker exited with %s, restarting in %.0f s", code, backoff)
            self.state = "crashed"
            self.message = (
                f"Analyse-Prozess beendet (Code {code}), Neustart in {backoff:.0f} s."
                if code is not None
                else self.message or "Analyse-Prozess startet nicht."
            )
            self._stopping.wait(backoff)
            backoff = min(backoff * 2, self.max_backoff)
        self.state = "stopped"

    def stop(self) -> None:
        self._stopping.set()
        with self._lock:
            proc = self._proc
        if proc is not None and proc.poll() is None:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=self.stop_timeout)
            except subprocess.TimeoutExpired:
                log.warning("analysis worker ignored SIGTERM, killing it")
                proc.kill()
                proc.wait()
        if self._thread is not None:
            self._thread.join(timeout=self.stop_timeout)
            self._thread = None
        self.state = "off" if worker_disabled() else "stopped"

    @property
    def process(self) -> subprocess.Popen[bytes] | None:
        with self._lock:
            return self._proc
