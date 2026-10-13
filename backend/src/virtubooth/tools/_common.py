"""Helpers shared by the CLI tools: data dir, database, time zone, photo iteration, errors."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.clock import DEFAULT_TIMEZONE, local_now
from ..db.database import Database
from ..domain.models import Photo, PhotoQuery
from ..repositories.container import Repositories

DB_NAME = "virtubooth.db"
EXPORTS_DIR = "exports"
# PhotosRepo.list caps a page at 1000 rows
PAGE_SIZE = 1000


class ToolError(Exception):
    """A problem the user can fix. Printed without a traceback.

    `user_message`: the same in German, for the admin UI's export jobs (which
    run these functions in the server); None = the job shows a generic text."""

    def __init__(self, message: str, code: int = 1, *, user_message: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = user_message


def run(fn: Callable[[argparse.Namespace], int], parser: argparse.ArgumentParser,
        argv: Sequence[str] | None) -> int:  # fmt: skip
    """Parse argv and run fn, turning ToolError/Ctrl+C into an exit code."""
    args = parser.parse_args(argv)
    try:
        return fn(args)
    except ToolError as exc:
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        print(f"\n{parser.prog}: aborted", file=sys.stderr)
        return 130


def add_data_dir_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--data-dir",
        metavar="DIR",
        help="virtubooth data directory with virtubooth.db and the photo folders "
        "(default: $VB_DATA_DIR, else ./data)",
    )


def resolve_data_dir(arg: str | None) -> Path:
    raw = arg or os.environ.get("VB_DATA_DIR", "").strip() or "./data"
    return Path(raw).expanduser().resolve()


def env_list(name: str) -> list[str] | None:
    """Comma-separated env var as a list, None when unset/empty."""
    items = [p.strip() for p in os.environ.get(name, "").split(",") if p.strip()]
    return items or None


def split_list(raw: str) -> list[str]:
    return [p.strip() for p in raw.split(",") if p.strip()]


def exports_dir(data_dir: Path) -> Path:
    return data_dir / EXPORTS_DIR


def scratch_parent(data_dir: Path, out: Path) -> Path:
    """Where a tool puts its temporary files: <data-dir>/exports/, else next to the output.

    Never the system temp dir: in the container /tmp is a small noexec tmpfs and
    the root file system is read-only. Temp dirs start with a dot and are removed
    when the tool finishes.
    """
    for candidate in (exports_dir(data_dir), out.parent):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if os.access(candidate, os.W_OK):
            return candidate
    raise ToolError(f"neither {exports_dir(data_dir)} nor {out.parent} is writable")


def check_free_space(folder: Path, needed: int) -> None:
    """Refuse to start writing `needed` bytes (plus a margin) into `folder`."""
    free = shutil.disk_usage(folder).free
    if free < needed * 1.05 + 10_000_000:
        raise ToolError(
            f"not enough disk space at {folder}: need ~{human_size(needed)}, "
            f"{human_size(free)} free (use --out elsewhere)",
            user_message=f"Nicht genug Speicherplatz auf dem Server: gebraucht etwa "
            f"{human_size(needed)}, frei {human_size(free)}.",
        )


def tool_timezone() -> str:
    """$VB_TIMEZONE (blank: Europe/Berlin), the zone the app's own exports use.

    The container's clock runs in UTC, so plain `datetime.now()` would name
    files an hour or two off from the admin UI's exports."""
    name = os.environ.get("VB_TIMEZONE", "").strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ToolError(f"unknown time zone VB_TIMEZONE={name!r} (e.g. Europe/Berlin)") from exc
    return name


def local_time() -> datetime:
    """Now, on the party's wall clock ($VB_TIMEZONE)."""
    return local_now(tool_timezone())


def timestamp() -> str:
    """For file names: 20261013-183000, party time."""
    return local_time().strftime("%Y%m%d-%H%M%S")


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    raise AssertionError("unreachable")


@contextmanager
def open_repos(data_dir: Path) -> Iterator[Repositories]:
    """Open <data_dir>/virtubooth.db without the app's Settings.

    Refuses to run on a directory without a database, so a typo in --data-dir
    doesn't silently create an empty one.
    """
    db_path = data_dir / DB_NAME
    if not db_path.is_file():
        raise ToolError(f"no virtubooth database at {db_path} (pass --data-dir or set VB_DATA_DIR)")
    db = Database(db_path)
    try:
        yield Repositories.create(db, data_dir)
    finally:
        db.close()


def iter_photos(
    repos: Repositories, *, extension: str | None = None, hidden: bool | None = None
) -> Iterator[Photo]:
    """All non-deleted photos in upload order, any number of them.

    hidden: None = visible and hidden, False = only visible, True = only hidden.
    """
    after: int | None = None
    while True:
        page = repos.photos.list(
            PhotoQuery(
                extension=extension, hidden=hidden, order="asc", after_id=after, limit=PAGE_SIZE
            )
        )
        yield from page
        if len(page) < PAGE_SIZE:
            return
        after = page[-1].id


def photo_counts(repos: Repositories) -> dict[str, int]:
    """Non-deleted photos per extension (for "did you mean" messages)."""
    return repos.photos.counts_by_extension()
