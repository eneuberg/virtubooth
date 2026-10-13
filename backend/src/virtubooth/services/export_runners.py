"""What each export job does. They reuse the CLI tools' functions
(`virtubooth.tools`) and write one file, `ctx.part`; the export service moves
it into place once the runner returned.

A runner reports progress through `ctx.progress(fraction)`, which also raises
`JobCancelled` when the server shuts down. Problems the admin can act on are
`JobFailed` (German message, shown as-is); a `ToolError` is shown with its
German `user_message`.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

from ..api.schemas.exports import ArchiveOptions, QrOptions, TimelapseOptions
from ..core.clock import now_iso
from ..domain.exports import ExportJob, ExportKind
from ..extensions.sdk import Extension
from ..repositories.container import Repositories
from ..settings import Settings
from ..tools import export as export_tool
from ..tools import qr as qr_tool
from ..tools import timelapse as timelapse_tool
from ..tools._common import DB_NAME, ToolError, check_free_space
from .host_settings import event_name

log = logging.getLogger("virtubooth.exports")

# the timelapse video: the Beer Cam's 3:4 at full size, x264's default speed
TIMELAPSE_SIZE = timelapse_tool.Size(1080, 1440)
TIMELAPSE_PRESET = "medium"
# a video of fewer frames per second than this plays badly in some players;
# with crossfade the video runs at this rate (or twice it for fast slideshows)
CROSSFADE_FPS = 30.0


class JobCancelled(Exception):
    """The server is shutting down: stop now."""


class JobFailed(Exception):
    """A problem the admin can understand; `message` is German."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class JobContext:
    job: ExportJob
    settings: Settings
    repos: Repositories
    extensions: Sequence[Extension]
    exports_dir: Path
    file_name: str  # the final name (the zips' top folder is named after it)
    part: Path  # write the output here
    progress: Callable[[float], None]

    @property
    def data_dir(self) -> Path:
        return self.settings.data_dir

    @property
    def root(self) -> str:
        """The folder everything inside a zip lives in."""
        return Path(self.file_name).stem

    @contextmanager
    def scratch(self) -> Iterator[Path]:
        """A temp dir on the data volume (never /tmp: a small tmpfs in the container)."""
        with tempfile.TemporaryDirectory(
            prefix=f".vb-job-{self.job.id}-", dir=self.exports_dir
        ) as tmp:
            yield Path(tmp)


Runner = Callable[[JobContext], None]


# ------------------------------------------------------------------ archive


def run_archive(ctx: JobContext) -> None:
    """photos/, photos.csv, users.csv, instagram.csv, manifest.json, README.txt
    and optionally the database copy, in one zip, from one database snapshot."""
    opts = ArchiveOptions.model_validate(ctx.job.options)
    root = ctx.root
    with ctx.scratch() as tmp:
        snapshot = export_tool.take_snapshot(ctx.data_dir, tmp, include_hidden=opts.include_hidden)
        ctx.progress(0.05)
        files = [(e, export_tool.file_size(e.source)) for e in snapshot.files]
        total = sum(size for _, size in files)
        check_free_space(ctx.exports_dir, total)
        entries = list(snapshot.entries)
        packed = 0
        with zipfile.ZipFile(ctx.part, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for entry, size in files:
                try:
                    # JPEGs don't shrink: stored, not deflated
                    zf.write(entry.source, f"{root}/{entry.arcname}", zipfile.ZIP_STORED)
                except FileNotFoundError:
                    # deleted by the admin while we pack: listed without a file
                    entries = [replace(x, arcname="") if x is entry else x for x in entries]
                packed += size
                ctx.progress(0.05 + 0.9 * packed / max(1, total))
            zf.writestr(f"{root}/photos.csv", export_tool.photos_csv(entries))
            zf.writestr(f"{root}/users.csv", export_tool.users_csv(snapshot.users))
            zf.writestr(f"{root}/instagram.csv", export_tool.instagram_csv(entries))
            zf.writestr(
                f"{root}/manifest.json",
                archive_manifest(ctx, opts, entries, guests=len(snapshot.users)),
            )
            if opts.include_db:
                zf.write(snapshot.db_file, f"{root}/{DB_NAME}")
            zf.writestr(
                f"{root}/README.txt",
                export_tool.readme(
                    data_dir=ctx.data_dir,
                    entries=entries,
                    users=snapshot.users,
                    timezone=ctx.settings.timezone,
                    include_hidden=opts.include_hidden,
                    include_db=opts.include_db,
                    cli=False,
                ),
            )


def archive_manifest(
    ctx: JobContext, opts: ArchiveOptions, entries: list[export_tool.Entry], *, guests: int
) -> bytes:
    packed = [e for e in entries if e.arcname]
    manifest = {
        "format": "virtubooth-archive/1",
        "created_at": now_iso(),
        "party_name": event_name(ctx.settings, ctx.repos),
        "include_hidden": opts.include_hidden,
        "include_db": opts.include_db,
        "photos": len(packed),
        "hidden": sum(1 for e in packed if e.photo.hidden),
        "missing_files": len(entries) - len(packed),
        "guests": guests,
        "files": [
            {
                "id": e.photo.public_id,
                "extension": e.photo.extension,
                "seq": e.photo.seq,
                "created_at": e.photo.created_at,
                "user": e.photo.user_name,
                "instagram": e.photo.user_instagram,
                "hidden": e.photo.hidden,
                "hidden_reason": e.photo.hidden_reason,
                "width": e.photo.width,
                "height": e.photo.height,
                "meta": e.photo.meta,
                "file": e.arcname or None,
            }
            for e in entries
        ],
    }
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


# ---------------------------------------------------------------- timelapse


def timelapse_options(opts: TimelapseOptions) -> timelapse_tool.Options:
    fps = float(opts.fps)
    if opts.crossfade:
        # crossfading needs more video frames than photos per second
        out_fps = CROSSFADE_FPS if fps < CROSSFADE_FPS else 2 * CROSSFADE_FPS
    else:
        out_fps = fps
    return timelapse_tool.Options(
        size=TIMELAPSE_SIZE,
        fps=fps,
        out_fps=out_fps,
        crossfade=opts.crossfade,
        preset=TIMELAPSE_PRESET,
    )


def run_timelapse(ctx: JobContext) -> None:
    opts = TimelapseOptions.model_validate(ctx.job.options)
    # looked up at run time (tests take it away); the CLI does the same check
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise JobFailed(
            "Für den Zeitraffer fehlt ffmpeg auf dem Server. Im Docker-Image ist es dabei; "
            "sonst bitte ffmpeg installieren."
        )
    o = timelapse_options(opts)
    got = timelapse_tool.collect(
        ctx.repos, opts.extension, include_hidden=opts.include_hidden, size=o.size
    )
    if not got.frames:
        ext = next((e for e in ctx.extensions if e.id == opts.extension), None)
        name = f"„{ext.title}“" if ext else f"„{opts.extension}“"
        hint = (
            ""
            if opts.include_hidden
            else " Ausgeblendete Fotos kommen nur mit „Ausgeblendete einbeziehen“ hinein."
        )
        raise JobFailed(f"Keine Fotos für den Zeitraffer: {name} hat keine sichtbaren Fotos.{hint}")
    ctx.progress(0.05)
    expected = o.expected_frames(len(got.frames))
    with ctx.scratch() as tmp:
        pattern = timelapse_tool.prepare_frames(got.frames, tmp, o.size)
        ctx.progress(0.1)
        cmd = timelapse_tool.build_command(ffmpeg, pattern, ctx.part, o)
        timelapse_tool.run_ffmpeg(
            cmd,
            expected,
            on_frames=lambda frames: ctx.progress(0.1 + 0.9 * min(1.0, frames / expected)),
            log=log.debug,
        )


# ----------------------------------------------------------------------- qr


def run_qr(ctx: JobContext) -> None:
    """qr-sheet.html (self-contained, one A4 page per code) plus every code as
    SVG and PNG, in one zip. The codes carry the party token."""
    opts = QrOptions.model_validate(ctx.job.options)
    if not opts.base_url:  # resolved when the job was created
        raise JobFailed("Keine öffentliche Adresse für die QR-Codes.")
    settings = ctx.settings
    party_name = event_name(settings, ctx.repos)
    cards = qr_tool.build_cards(
        opts.base_url,
        settings.party_token.get_secret_value(),
        [e for e in ctx.extensions if e.show_on_home],
        party_name=party_name,
    )
    root = ctx.root
    with zipfile.ZipFile(ctx.part, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{root}/{qr_tool.SHEET_NAME}", qr_tool.render_sheet(cards, party_name))
        for i, card in enumerate(cards, 1):
            for name, data in qr_tool.render_codes(card):
                zf.writestr(f"{root}/{name}", data)
            ctx.progress(i / len(cards))


RUNNERS: dict[ExportKind, Runner] = {
    "archive": run_archive,
    "timelapse": run_timelapse,
    "qr": run_qr,
}


def user_message(exc: ToolError) -> str:
    return exc.user_message or "Der Export ist fehlgeschlagen. Details stehen im Server-Log."
