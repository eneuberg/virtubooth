"""Export everything after the party as one .tar.gz.

    python -m virtubooth.tools.export

Archive layout (everything inside one folder named like the archive):

    virtubooth-export-<timestamp>/
      README.txt                         what is what
      photos/<ext>/<seq>_<file>.jpg      visible photos, per activity in upload order
      photos/<ext>/hidden/<seq>_<file>   photos the admin hid (not with --no-hidden)
      photos.csv                         one row per exported photo
      users.csv                          one row per guest
      instagram.csv                      Instagram handle -> photos to tag
      virtubooth.db                      consistent SQLite copy (backup API)

Everything comes from one database snapshot, so the CSVs, the photo files and
the database copy agree even while the app keeps running.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import sqlite3
import tarfile
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from ..db import Database
from ..repo import Photo, Repo, User
from ._common import (
    DB_NAME,
    ToolError,
    add_data_dir_arg,
    exports_dir,
    human_size,
    iter_photos,
    resolve_data_dir,
    run,
    scratch_parent,
    timestamp,
)

PROG = "python -m virtubooth.tools.export"
PHOTO_COLUMNS = [
    "id", "extension", "seq", "created_at", "user", "instagram", "hidden", "hidden_reason",
    "width", "height", "meta", "file",
]  # fmt: skip
USER_COLUMNS = ["user", "instagram", "consent_at", "photo_count", "banned", "ban_reason"]
INSTAGRAM_COLUMNS = ["instagram", "user", "photo_count", "files"]
USERS_PAGE = 500  # Repo.list_users caps a page at 500


@dataclass(frozen=True)
class Entry:
    photo: Photo
    source: Path
    arcname: str  # relative to the archive root, "" if the file is missing


def snapshot_db(db_path: Path, dest: Path) -> None:
    """Consistent copy via SQLite's online backup API (safe while the app writes)."""
    src = sqlite3.connect(db_path, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        # a standalone file: no -wal/-shm companions when someone opens the copy
        dst.execute("PRAGMA journal_mode=DELETE")
    finally:
        dst.close()
        src.close()


def all_users(repo: Repo) -> list[User]:
    users: list[User] = []
    while True:
        page = repo.list_users(limit=USERS_PAGE, offset=len(users))
        users += page
        if len(page) < USERS_PAGE:
            return sorted(users, key=lambda u: u.id)


def plan_entries(repo: Repo, *, include_hidden: bool) -> list[Entry]:
    photos = list(iter_photos(repo, hidden=None if include_hidden else False))
    width: dict[str, int] = {}
    for p in photos:
        width[p.extension] = max(width.get(p.extension, 4), len(str(p.seq)))
    entries = []
    for p in photos:
        source = repo.photo_path(p.extension, p.filename)
        rel = Path(p.filename)
        # only files below <data_dir>/<extension>/ (lexically: the folder may be a symlink)
        inside = not rel.is_absolute() and ".." not in rel.parts and "/" not in p.extension
        arcname = ""
        if inside and source.is_file():
            folder = f"photos/{p.extension}/" + ("hidden/" if p.hidden else "")
            arcname = f"{folder}{p.seq:0{width[p.extension]}d}_{Path(p.filename).name}"
        entries.append(Entry(p, source, arcname))
    return entries


def _csv(header: list[str], rows: list[list[object]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    # BOM so Excel reads the umlauts in the pseudonyms right
    return buf.getvalue().encode("utf-8-sig")


def photos_csv(entries: list[Entry]) -> bytes:
    rows: list[list[object]] = [
        [
            e.photo.public_id,
            e.photo.extension,
            e.photo.seq,
            e.photo.created_at,
            e.photo.user_name,
            e.photo.user_instagram or "",
            int(e.photo.hidden),
            e.photo.hidden_reason or "",
            e.photo.width,
            e.photo.height,
            json.dumps(e.photo.meta, ensure_ascii=False, sort_keys=True),
            e.arcname,
        ]  # fmt: skip
        for e in entries
    ]
    return _csv(PHOTO_COLUMNS, rows)


def users_csv(users: list[User]) -> bytes:
    rows: list[list[object]] = [
        [u.name, u.instagram or "", u.consent_at, u.photo_count, int(u.banned), u.ban_reason or ""]
        for u in users
    ]
    return _csv(USER_COLUMNS, rows)


def taggable(entries: list[Entry]) -> dict[str, tuple[str, list[str]]]:
    """handle -> (pseudonym, archive paths): visible photos of guests who gave a
    handle and aren't banned."""
    tags: dict[str, tuple[str, list[str]]] = {}
    for e in entries:
        p = e.photo
        if p.user_instagram and e.arcname and not p.hidden and not p.user_banned:
            tags.setdefault(p.user_instagram, (p.user_name, []))[1].append(e.arcname)
    return tags


def instagram_csv(entries: list[Entry]) -> bytes:
    tags = taggable(entries)
    rows: list[list[object]] = [
        [f"@{handle}", name, len(paths), "; ".join(paths)]
        for handle, (name, paths) in sorted(tags.items())
    ]
    return _csv(INSTAGRAM_COLUMNS, rows)


def readme(
    *, data_dir: Path, entries: list[Entry], users: list[User],
    include_hidden: bool, include_db: bool,
) -> bytes:  # fmt: skip
    per_ext: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for e in entries:
        if e.arcname:
            per_ext[e.photo.extension][int(e.photo.hidden)] += 1
    counts = ", ".join(
        f"{ext} {v}" + (f" + {h} hidden" if h else "") for ext, (v, h) in sorted(per_ext.items())
    )
    missing = sum(1 for e in entries if not e.arcname)
    lines = [
        "virtubooth export",
        "=================",
        "",
        f"Created {datetime.now():%Y-%m-%d %H:%M} (local time) from {data_dir}",
        f"Photos: {counts or 'none'}. Guests: {len(users)}.",
        *(
            [f"{missing} photo(s) had no file on disk; their CSV rows have an empty 'file'."]
            if missing
            else []
        ),  # fmt: skip
        "",
        "Contents",
        "--------",
        "photos/<activity>/<seq>_<original file>.jpg",
        "    Visible photos. <seq> is the photo number within the activity",
        "    (Beer #127 = photos/beer/0127_...), so sorting by name = upload order.",
    ]
    if include_hidden:
        lines += [
            "photos/<activity>/hidden/<seq>_<original file>.jpg",
            "    Photos the admin hid (moderation or banned guest). Do not post these.",
        ]
    else:
        lines += ["    Hidden photos were left out of this export (--no-hidden)."]
    lines += [
        "photos.csv",
        "    One row per exported photo: id, extension, seq, created_at (UTC),",
        "    user (pseudonym), instagram, hidden (1/0), hidden_reason (admin|ban),",
        '    width, height, meta (JSON, e.g. {"vessel": "cup"}),',
        "    file (path inside this folder).",
        "users.csv",
        "    One row per guest: user (pseudonym), instagram, consent_at (UTC),",
        "    photo_count (photos not deleted, hidden included), banned (1/0), ban_reason.",
        "instagram.csv",
        "    Who to tag: one row per Instagram handle with the visible photos of",
        "    that guest (banned guests and hidden photos are left out).",
        "    files = paths separated by '; '.",
    ]
    if include_db:
        lines += [
            "virtubooth.db",
            "    Consistent copy of the SQLite database: all tables, including hidden",
            "    and deleted photo rows, IP addresses, browser fingerprints and the",
            "    admin audit log. Open with `sqlite3 virtubooth.db` or DB Browser for SQLite.",
        ]
    lines += [
        "",
        "Notes",
        "-----",
        "- CSV files: UTF-8 with BOM, comma separated. If Excel puts everything into",
        "  one column, use Data > From Text/CSV.",
        "- Deleted photos are gone for good; they are not in this export.",
        "- Guests agreed to their photos being stored and posted on Instagram, nothing",
        "  more. This archive holds personal data: keep it private and delete it when",
        "  you no longer need it.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _normalize(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    ti.mode = 0o644
    return ti


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    ti = tarfile.TarInfo(name)
    ti.size = len(data)
    ti.mtime = int(time.time())
    tar.addfile(_normalize(ti), io.BytesIO(data))


def archive_root(out: Path) -> str:
    name = out.name
    for suffix in (".tar.gz", ".tgz", ".tar"):
        if name.endswith(suffix):
            return name[: -len(suffix)] or "virtubooth-export"
    return name


# ------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Export all photos, CSV lists (photos, guests, Instagram tags) and a "
        "consistent database copy into one .tar.gz. Safe while the app is running.",
        epilog="example:\n"
        f"  {PROG}\n"
        f"  {PROG} --no-hidden --out ~/party-photos.tar.gz\n\n"
        "The archive contains one folder with README.txt explaining every file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_data_dir_arg(p)
    p.add_argument(
        "--out",
        metavar="FILE",
        help="output .tar.gz or directory "
        "(default: <data-dir>/exports/virtubooth-export-<timestamp>.tar.gz)",
    )
    p.add_argument(
        "--no-hidden",
        action="store_true",
        help="leave out photos the admin hid (default: include them under photos/<ext>/hidden/)",
    )
    p.add_argument(
        "--no-db",
        action="store_true",
        help="leave out the database copy (it holds IP addresses and browser fingerprints)",
    )
    return p


def output_path(arg: str | None, data_dir: Path) -> Path:
    name = f"virtubooth-export-{timestamp()}.tar.gz"
    if not arg:
        return exports_dir(data_dir) / name
    out = Path(arg).expanduser()
    return (out / name if out.is_dir() else out).resolve()


def _main(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    db_path = data_dir / DB_NAME
    if not db_path.is_file():
        raise ToolError(f"no virtubooth database at {db_path} (pass --data-dir or set VB_DATA_DIR)")
    out = output_path(args.out, data_dir)
    root = archive_root(out)
    include_hidden = not args.no_hidden

    # the snapshot lives on the data volume (or next to the output), never in /tmp
    with tempfile.TemporaryDirectory(
        prefix=".vb-export-", dir=scratch_parent(data_dir, out)
    ) as tmp:
        snap = Path(tmp) / DB_NAME
        print(f"Snapshotting {db_path} ...", flush=True)
        snapshot_db(db_path, snap)
        db = Database(snap)  # reads the snapshot, photo files from data_dir
        try:
            repo = Repo(db, data_dir)
            entries = plan_entries(repo, include_hidden=include_hidden)
            users = all_users(repo)
        finally:
            db.close()
        # Database() switched the snapshot to WAL; make it a standalone file again
        conn = sqlite3.connect(snap)
        try:
            conn.execute("PRAGMA journal_mode=DELETE")
        finally:
            conn.close()

        files = [e for e in entries if e.arcname]
        missing = len(entries) - len(files)
        total = sum(_size(e.source) for e in files)
        out.parent.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(out.parent).free
        if free < total * 1.05 + 10_000_000:
            raise ToolError(
                f"not enough disk space at {out.parent}: need ~{human_size(total)}, "
                f"{human_size(free)} free (use --out elsewhere)"
            )
        print(f"Packing {len(files)} photos ({human_size(total)}) into {out} ...", flush=True)
        if missing:
            print(f"  warning: {missing} photo(s) have no file on disk, listed without one")

        part = out.with_name(out.name + ".part")
        try:
            with tarfile.open(part, "w:gz", compresslevel=6, dereference=True) as tar:
                step = max(100, len(files) // 10)
                for i, e in enumerate(files, 1):
                    try:
                        tar.add(e.source, arcname=f"{root}/{e.arcname}", recursive=False,
                                filter=_normalize)  # fmt: skip
                    except FileNotFoundError:
                        # deleted by the admin while we pack: list it without a file
                        print(f"  warning: {e.source} vanished during the export")
                        entries = [replace(x, arcname="") if x is e else x for x in entries]
                    if i % step == 0 or i == len(files):
                        print(f"  {i}/{len(files)} photos", flush=True)
                _add_bytes(tar, f"{root}/photos.csv", photos_csv(entries))
                _add_bytes(tar, f"{root}/users.csv", users_csv(users))
                _add_bytes(tar, f"{root}/instagram.csv", instagram_csv(entries))
                if not args.no_db:
                    tar.add(snap, arcname=f"{root}/{DB_NAME}", filter=_normalize)
                _add_bytes(
                    tar,
                    f"{root}/README.txt",
                    readme(
                        data_dir=data_dir,
                        entries=entries,
                        users=users,
                        include_hidden=include_hidden,
                        include_db=not args.no_db,
                    ),  # fmt: skip
                )
            part.replace(out)
        finally:
            part.unlink(missing_ok=True)

    packed = [e for e in entries if e.arcname]
    hidden = sum(1 for e in packed if e.photo.hidden)
    tagged = len(taggable(entries))
    print(f"Done: {out} ({human_size(out.stat().st_size)})")
    print(
        f"  {len(packed)} photos ({hidden} hidden), {len(users)} guests, "
        f"{tagged} Instagram handles to tag; unpack with: tar xzf {out.name}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_main, build_parser(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
