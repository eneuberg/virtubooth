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
      virtubooth.db                      consistent SQLite copy (backup API), without
                                         admin sessions, export jobs and visitors
                                         (SCRUBBED_TABLES) and password hashes

Everything comes from one database snapshot, so the CSVs, the photo files and
the database copy agree even while the app keeps running.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import tarfile
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from ..core.clock import local_now
from ..db.database import Database
from ..domain.models import Photo, User
from ..repositories.container import Repositories
from ._common import (
    DB_NAME,
    ToolError,
    add_data_dir_arg,
    check_free_space,
    exports_dir,
    human_size,
    iter_photos,
    resolve_data_dir,
    run,
    scratch_parent,
    timestamp,
    tool_timezone,
)

PROG = "python -m virtubooth.tools.export"
PHOTO_COLUMNS = [
    "id", "extension", "seq", "created_at", "user", "instagram", "hidden", "hidden_reason",
    "width", "height", "meta", "file",
]  # fmt: skip
USER_COLUMNS = [
    "user", "instagram", "consent_at", "photo_count", "banned", "ban_reason",
    "online_seconds", "online_sessions", "code",
]  # fmt: skip
INSTAGRAM_COLUMNS = ["instagram", "user", "photo_count", "files"]
USERS_PAGE = 500  # UsersRepo.list caps a page at 500


@dataclass(frozen=True)
class Entry:
    photo: Photo
    source: Path
    arcname: str  # relative to the archive root, "" if the file is missing


@dataclass(frozen=True)
class Snapshot:
    """What an export packs, all from one consistent database copy."""

    db_file: Path  # the standalone copy (journal_mode=DELETE)
    entries: list[Entry]
    users: list[User]
    code_names: dict[int, str] = field(default_factory=dict)  # QR code number -> name

    @property
    def files(self) -> list[Entry]:
        return [e for e in self.entries if e.arcname]


# Emptied in every database copy that goes into an archive: admin sessions
# (token hashes, password tags, the admins' IPs and browsers), the export
# jobs (the server's own bookkeeping), the visitors (the dashboard's live
# counters: browser ids that are worth nothing after the party) and which of
# those browser ids opened which QR code (code_visitors). The tables stay, so
# the copy still opens as a virtubooth database (restoring it logs every admin
# out).
SCRUBBED_TABLES = ("admin_sessions", "export_jobs", "visitors", "code_visitors")
# Settings rows removed from the copy: password hashes (the admin password set
# in the admin, `admin.password`, and an extension's, e.g. the Live-Wall's
# `x.wall.password`). An archive must not hand out something to crack offline;
# restoring the copy falls back to VB_ADMIN_PASSWORD and a wall without one.
SCRUBBED_SETTINGS_SQL = "key = 'admin.password' OR key LIKE 'x.%.password'"


def scrub_snapshot(path: Path) -> None:
    """Empty SCRUBBED_TABLES and drop the password hashes
    (SCRUBBED_SETTINGS_SQL) in a database copy, then VACUUM: the backup API
    copies free pages too, so rows deleted earlier (also in the live database)
    could otherwise be recovered from the file. Leaves a standalone file
    (journal_mode=DELETE, no -wal/-shm companions)."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("BEGIN IMMEDIATE")
        for table in SCRUBBED_TABLES:
            conn.execute(f"DELETE FROM {table}")  # fixed names, never input
        conn.execute(f"DELETE FROM settings WHERE {SCRUBBED_SETTINGS_SQL}")
        conn.execute("COMMIT")
        conn.execute("VACUUM")
    finally:
        conn.close()


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


def all_users(repos: Repositories) -> list[User]:
    users: list[User] = []
    while True:
        page = repos.users.list(limit=USERS_PAGE, offset=len(users))
        users += page
        if len(page) < USERS_PAGE:
            return sorted(users, key=lambda u: u.id)


def take_snapshot(data_dir: Path, tmp: Path, *, include_hidden: bool) -> Snapshot:
    """Copy the live database into `tmp` (backup API) and plan the export from
    the copy; the photo files come from `data_dir`. The copy is scrubbed
    (`scrub_snapshot`) before anything packs it."""
    snap = tmp / DB_NAME
    snapshot_db(data_dir / DB_NAME, snap)
    db = Database(snap)  # reads the snapshot, photo files from data_dir
    try:
        repos = Repositories.create(db, data_dir)
        entries = plan_entries(repos, include_hidden=include_hidden)
        users = all_users(repos)
        code_names = {c.id: c.name for c in repos.codes.list()}
    finally:
        db.close()
    # also makes it a standalone file again (Database() switched it to WAL)
    scrub_snapshot(snap)
    return Snapshot(snap, entries, users, code_names)


def plan_entries(repos: Repositories, *, include_hidden: bool) -> list[Entry]:
    photos = list(iter_photos(repos, hidden=None if include_hidden else False))
    width: dict[str, int] = {}
    for p in photos:
        width[p.extension] = max(width.get(p.extension, 4), len(str(p.seq)))
    entries = []
    for p in photos:
        source = repos.photos.path(p.extension, p.filename)
        rel = Path(p.filename)
        # only files below <data_dir>/<extension>/ (lexically: the folder may be a symlink)
        inside = not rel.is_absolute() and ".." not in rel.parts and "/" not in p.extension
        arcname = ""
        if inside and source.is_file():
            folder = f"photos/{p.extension}/" + ("hidden/" if p.hidden else "")
            arcname = f"{folder}{p.seq:0{width[p.extension]}d}_{Path(p.filename).name}"
        entries.append(Entry(p, source, arcname))
    return entries


def _cell(value: object) -> object:
    # Excel/LibreOffice run cells starting with = + - @ as formulas
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _csv(header: list[str], rows: list[list[object]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows([_cell(v) for v in row] for row in rows)
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
        ]
        for e in entries
    ]
    return _csv(PHOTO_COLUMNS, rows)


def users_csv(users: list[User], code_names: dict[int, str] | None = None) -> bytes:
    """`code`: the name of the QR code the guest joined through ("" unknown)."""
    names = code_names or {}
    rows: list[list[object]] = [
        [
            u.name,
            u.instagram or "",
            u.consent_at,
            u.photo_count,
            int(u.banned),
            u.ban_reason or "",
            u.online_seconds,
            u.online_sessions,
            names.get(u.code_id, "") if u.code_id is not None else "",
        ]
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
        # without "@": spreadsheets read a leading @ as a formula
        [handle, name, len(paths), "; ".join(paths)]
        for handle, (name, paths) in sorted(tags.items())
    ]
    return _csv(INSTAGRAM_COLUMNS, rows)


def readme(
    *, data_dir: Path, entries: list[Entry], users: list[User], timezone: str,
    include_hidden: bool, include_db: bool, cli: bool = True,
) -> bytes:  # fmt: skip
    """README.txt. `cli` False: made by the admin UI (a zip with manifest.json).
    `timezone`: the "Created" line's zone (VB_TIMEZONE)."""
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
        f"Created {local_now(timezone):%Y-%m-%d %H:%M} ({timezone}) from {data_dir}",
        f"Photos: {counts or 'none'}. Guests: {len(users)}.",
        *(
            [f"{missing} photo(s) had no file on disk; their CSV rows have an empty 'file'."]
            if missing
            else []
        ),
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
        how = " (--no-hidden)" if cli else ""
        lines += [f"    Hidden photos were left out of this export{how}."]
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
    if not cli:
        lines += [
            "manifest.json",
            "    The same as photos.csv, machine-readable, plus what this export contains.",
        ]
    if include_db:
        lines += [
            "virtubooth.db",
            "    Consistent copy of the SQLite database: guests (pseudonyms, Instagram",
            "    handles, IP addresses, browsers, device fingerprints, bans), all photo",
            "    rows (hidden and deleted ones included), device bans, the admin audit",
            "    log (with the addresses admins logged in from), the upload settings and",
            "    the QR codes with their tokens. Admin sessions, export jobs and password",
            "    hashes are removed; nothing deleted earlier can be recovered from the",
            "    file. Open with `sqlite3 virtubooth.db` or DB Browser for SQLite.",
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


def file_size(path: Path) -> int:
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
        "(default: <data-dir>/exports/virtubooth-export-<timestamp>.tar.gz, "
        "the time in $VB_TIMEZONE, default Europe/Berlin)",
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
        print(f"Snapshotting {db_path} ...", flush=True)
        snapshot = take_snapshot(data_dir, Path(tmp), include_hidden=include_hidden)
        snap, entries, users = snapshot.db_file, snapshot.entries, snapshot.users

        files = snapshot.files
        missing = len(entries) - len(files)
        total = sum(file_size(e.source) for e in files)
        out.parent.mkdir(parents=True, exist_ok=True)
        check_free_space(out.parent, total)
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
                _add_bytes(tar, f"{root}/users.csv", users_csv(users, snapshot.code_names))
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
                        timezone=tool_timezone(),
                        include_hidden=include_hidden,
                        include_db=not args.no_db,
                    ),
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
