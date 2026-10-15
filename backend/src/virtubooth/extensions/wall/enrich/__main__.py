"""`virtubooth wall …` (or `python -m virtubooth.extensions.wall.enrich …`): the
analysis worker and its tools.

worker   [--data-dir DIR]                 the worker loop (the app starts it)
run-once [--data-dir DIR] [--limit N]      analyse what is pending, print timings
status   [--data-dir DIR]                 counts, worker heartbeat, analyzers
models fetch [--with-age] [--dest DIR]    download the models (SHA256-checked)
models list  [--data-dir DIR]             which models are present
bench PHOTO_DIR [--age] [--passes N]      timings and memory on this machine
burst [--clients N] [--photos N]          upload burst with and without the worker

The ML libraries are imported lazily (after `tune_process` has set the thread
limits), never by these top-level imports.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
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


def _bench(args: argparse.Namespace) -> int:
    from .bench import render, run_bench
    from .worker import tune_process

    tune_process(nice=not args.no_nice)
    folder = Path(args.photos)
    photos = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg"))
    if not photos:
        raise ToolError(f"no JPEGs in {folder}")
    data_dir = resolve_data_dir(args.data_dir) if args.data_dir else None
    result = run_bench(photos, with_age=args.age, passes=args.passes, data_dir=data_dir)
    print(json.dumps(result, ensure_ascii=False) if args.json else render(result))
    return 0


def _burst(args: argparse.Namespace) -> int:
    from .burst import compare, render

    if args.clients < 1 or args.photos < args.clients:
        raise ToolError("--photos must be at least --clients (≥ 1)")
    result = compare(args.clients, args.photos, log=lambda m: print(m, file=sys.stderr))
    print(json.dumps(result, ensure_ascii=False) if args.json else render(result))
    return 0 if result["p95_ok"] else 1


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


def parser(prog: str = "python -m virtubooth.extensions.wall.enrich") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=prog,
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
    b = sub.add_parser("bench", help="time the analyzers on the JPEGs in a folder (no database)")
    b.add_argument("photos", metavar="PHOTO_DIR")
    b.add_argument("--age", action="store_true", help="also FairFace age (opt-in analyzer)")
    b.add_argument("--passes", type=int, default=2, help="runs over the folder (first = cold)")
    b.add_argument("--no-nice", action="store_true", help="normal priority (worker: nice 10)")
    b.add_argument("--json", action="store_true", help="machine-readable output")
    b.add_argument("--data-dir", metavar="DIR", help="also look for models in DIR/wall/models")
    b.set_defaults(fn=_bench)
    u = sub.add_parser("burst", help="upload burst on a throwaway party, with and without "
                       "the worker (numbers for the queue behaviour)")  # fmt: skip
    u.add_argument("--clients", type=int, default=20, help="guests uploading at once")
    u.add_argument("--photos", type=int, default=60, help="uploads in total")
    u.add_argument("--json", action="store_true", help="machine-readable output")
    u.set_defaults(fn=_burst)
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


def main(argv: Sequence[str] | None = None, prog: str | None = None) -> int:
    os.environ.setdefault("MPLBACKEND", "Agg")
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr,
        format="%(asctime)s wall-enrich[%(process)d] %(levelname)s %(message)s",
    )  # fmt: skip
    return run(lambda a: int(a.fn(a)), parser(prog) if prog else parser(), argv)


if __name__ == "__main__":
    sys.exit(main())
