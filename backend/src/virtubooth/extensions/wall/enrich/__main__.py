"""`python -m virtubooth.extensions.wall.enrich …`: the analysis worker and its tools.

worker   [--data-dir DIR]                 the worker loop (the app starts it)
run-once [--data-dir DIR] [--limit N]      analyse what is pending, print timings
status   [--data-dir DIR]                 counts, worker heartbeat, analyzers
models fetch [--with-age] [--dest DIR]    download the models (SHA256-checked)
models list  [--data-dir DIR]             which models are present
"""

from __future__ import annotations

import os

# before numpy / onnxruntime / mediapipe load (the analyzers import them)
os.environ.setdefault("OMP_NUM_THREADS", "3")
os.environ.setdefault("MPLBACKEND", "Agg")

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from ....tools._common import (
    ToolError,
    add_data_dir_arg,
    open_repos,
    resolve_data_dir,
    run,
)
from . import jobs, models
from .analyzers import INFOS, ml_installed


def _worker(args: argparse.Namespace) -> int:
    from .worker import Worker, tune_process

    tune_process()
    return Worker(resolve_data_dir(args.data_dir)).run()


def _run_once(args: argparse.Namespace) -> int:
    from .worker import Worker, peak_rss_mb, tune_process

    tune_process()
    worker = Worker(resolve_data_dir(args.data_dir))
    worker.run(once=True, limit=args.limit, report=None if args.quiet else print)
    print(f"{worker.processed} photos, peak RSS {peak_rss_mb():.0f} MB")
    return 0


def _status(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    with open_repos(data_dir) as repos:
        counts = jobs.counts(repos.db)
        beat = repos.app_settings.get(jobs.WORKER_KEY)
        disabled = jobs.disabled_analyzers(repos.app_settings)
    print("photos: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    print(f"worker: {json.dumps(beat, ensure_ascii=False) if beat else 'no heartbeat yet'}")
    print(f"ml extra: {'installed' if ml_installed() else 'missing'}")
    missing = set(models.missing([m.name for m in models.REGISTRY], data_dir))
    for info in INFOS:
        lacking = [m for m in info.models if m in missing]
        state = "off" if info.name in disabled else "on"
        note = f" (missing: {', '.join(lacking)})" if lacking else ""
        print(f"  {info.name:9} {state:3} {info.kind:5} {info.title}{note}")
    return 0


def _models_fetch(args: argparse.Namespace) -> int:
    dest = (
        Path(args.dest).expanduser().resolve()
        if args.dest
        else models.default_dest(resolve_data_dir(args.data_dir))
    )
    try:
        models.fetch(dest, with_age=args.with_age)
    except models.FetchError as exc:
        raise ToolError(str(exc)) from exc
    return 0


def _models_list(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    dirs = models.search_dirs(data_dir)
    print("searched: " + ", ".join(str(d) for d in dirs))
    for m in models.REGISTRY:
        path = models.find(m.name, dirs)
        where = str(path) if path else "MISSING" + (" (optional, --with-age)" if m.optional else "")
        print(f"  {m.name:19} {m.size / 1e6:6.1f} MB  {m.license:12.12}  {where}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m virtubooth.extensions.wall.enrich",
        description="Live-Wall photo analysis: worker, models, status.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    w = sub.add_parser("worker", help="run the analysis worker loop")
    add_data_dir_arg(w)
    w.set_defaults(fn=_worker)
    o = sub.add_parser("run-once", help="analyse the pending photos now, print timings")
    add_data_dir_arg(o)
    o.add_argument("--limit", type=int, default=None, help="at most N photos")
    o.add_argument("--quiet", action="store_true", help="no line per photo")
    o.set_defaults(fn=_run_once)
    s = sub.add_parser("status", help="counts, heartbeat, analyzers")
    add_data_dir_arg(s)
    s.set_defaults(fn=_status)
    m = sub.add_parser("models", help="download or list the model files")
    msub = m.add_subparsers(dest="models_command", required=True)
    f = msub.add_parser("fetch", help="download the models (SHA256-checked)")
    add_data_dir_arg(f)
    f.add_argument("--with-age", action="store_true", help="also FairFace age (87 MB)")
    f.add_argument("--dest", metavar="DIR", help="target folder (default: $VB_WALL_MODELS_DIR, "
                   "else <data-dir>/wall/models)")  # fmt: skip
    f.set_defaults(fn=_models_fetch)
    ls = msub.add_parser("list", help="which models are present")
    add_data_dir_arg(ls)
    ls.set_defaults(fn=_models_list)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr,
        format="%(asctime)s wall-enrich[%(process)d] %(levelname)s %(message)s",
    )  # fmt: skip
    return run(lambda a: int(a.fn(a)), parser(), argv)


if __name__ == "__main__":
    sys.exit(main())
