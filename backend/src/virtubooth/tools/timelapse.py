"""Build a timelapse video from an extension's photos (default: the Beer Cam).

    python -m virtubooth.tools.timelapse                        # beer, 12 photos/s
    python -m virtubooth.tools.timelapse --fps 4 --crossfade    # slower, blended

Photos are used in upload order; hidden ones only with --include-hidden,
deleted ones never. Every frame is scaled to --size. Photos with another
aspect ratio (or an unusual JPEG flavour) are letterboxed with Pillow first,
so odd uploads can't break the encode. ffmpeg reads numbered symlinks from a
temp dir under <data-dir>/exports/ (never /tmp: a small tmpfs in the container),
which works for any number of photos.

How --crossfade works: each photo is repeated up to --out-fps (default 30) and
ffmpeg's `tmix` averages the last K frames. A moving average over held photos
is an exact linear crossfade, K frames long; the rest of each photo's time
stays sharp. K = --fade x frames per photo (at least 2), so --fade 1 blends
continuously (what ffmpeg's `framerate` interpolation does) and --fade 0.3
gives short dissolves between sharp photos. One filter pass, no per-photo
filters, so it scales to thousands of photos.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageOps

from ..repositories.container import Repositories
from ._common import (
    ToolError,
    add_data_dir_arg,
    exports_dir,
    human_size,
    iter_photos,
    open_repos,
    photo_counts,
    resolve_data_dir,
    run,
    scratch_parent,
    timestamp,
)

PROG = "python -m virtubooth.tools.timelapse"
# photos within 1 % of the target aspect ratio are stretched, not letterboxed
ASPECT_TOLERANCE = 0.01
X264_PRESETS = (
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
)  # fmt: skip


@dataclass(frozen=True)
class Size:
    width: int
    height: int

    @property
    def aspect(self) -> float:
        return self.width / self.height

    def __str__(self) -> str:
        return f"{self.width}x{self.height}"


def parse_size(raw: str) -> Size:
    m = re.fullmatch(r"\s*(\d+)\s*[xX]\s*(\d+)\s*", raw)
    if not m:
        raise argparse.ArgumentTypeError(f"{raw!r} is not WIDTHxHEIGHT, e.g. 1080x1440")
    size = Size(int(m[1]), int(m[2]))
    if not (16 <= size.width <= 4096 and 16 <= size.height <= 4096):
        raise argparse.ArgumentTypeError("width and height must be between 16 and 4096")
    if size.width % 2 or size.height % 2:
        raise argparse.ArgumentTypeError("width and height must be even (H.264, yuv420p)")
    return size


def rate(x: float) -> str:
    """ffmpeg frame rate syntax: 12 -> "12", 0.5 -> "1/2", 29.97 -> "2997/100"."""
    f = Fraction(x).limit_denominator(1001)
    return str(f.numerator) if f.denominator == 1 else f"{f.numerator}/{f.denominator}"


@dataclass(frozen=True)
class Options:
    size: Size = Size(1080, 1440)
    fps: float = 12.0
    out_fps: float = 12.0
    crossfade: bool = False
    fade: float = 0.5
    hold_last: float = 2.0
    crf: int = 20
    preset: str = "medium"

    @property
    def frames_per_photo(self) -> float:
        return self.out_fps / self.fps

    @property
    def mix_frames(self) -> int:
        """tmix window = length of each crossfade in output frames."""
        return max(2, int(self.fade * self.frames_per_photo + 0.5))

    def expected_frames(self, photos: int) -> int:
        return round(photos * self.frames_per_photo) + round(self.hold_last * self.out_fps)


def filter_chain(o: Options) -> str:
    w, h = o.size.width, o.size.height
    steps = [
        # JPEGs are BT.601 full range; phones/browsers expect BT.709 limited for HD video
        f"scale={w}:{h}:flags=lanczos:out_color_matrix=bt709:out_range=tv",
        "format=yuv420p",
        "setsar=1",
    ]
    if o.out_fps != o.fps:
        steps.append(f"fps={rate(o.out_fps)}")
    if o.hold_last > 0:
        steps.append(f"tpad=stop_mode=clone:stop_duration={o.hold_last:g}")
    if o.crossfade:
        # after tpad, so the held last photo ends sharp
        steps.append(f"tmix=frames={o.mix_frames}")
    return ",".join(steps)


def build_command(ffmpeg: str, pattern: str, out: Path, o: Options) -> list[str]:
    return [
        ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-framerate", rate(o.fps), "-start_number", "1",
        # photos of different sizes must not rebuild the filter graph mid-stream
        # (that resets fps/tpad/tmix); the scale filter adapts per frame instead
        "-reinit_filter", "0",
        "-i", pattern,
        "-vf", filter_chain(o),
        "-an", "-c:v", "libx264", "-preset", o.preset, "-crf", str(o.crf),
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-color_range", "tv",
        "-movflags", "+faststart", "-f", "mp4",
        "-progress", "pipe:1", "-nostats",
        str(out),
    ]  # fmt: skip


# ---------------------------------------------------------------- photos


@dataclass
class Collected:
    # (photo file, needs letterboxing) in upload order
    frames: list[tuple[Path, bool]] = field(default_factory=list)
    missing: int = 0
    unreadable: int = 0

    @property
    def letterboxed(self) -> int:
        return sum(1 for _, fix in self.frames if fix)


def needs_letterbox(path: Path, size: Size) -> bool | None:
    """False = ffmpeg can scale it directly, True = Pillow first, None = unreadable."""
    try:
        with Image.open(path) as im:
            fmt, mode, (w, h) = im.format, im.mode, im.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    if fmt != "JPEG" or mode != "RGB":
        return True
    return abs((w / h) / size.aspect - 1) > ASPECT_TOLERANCE


def collect(
    repos: Repositories,
    extension: str,
    *,
    include_hidden: bool,
    size: Size,
    limit: int | None = None,
) -> Collected:
    result = Collected()
    for photo in iter_photos(repos, extension=extension, hidden=None if include_hidden else False):
        if limit is not None and len(result.frames) >= limit:
            break
        path = repos.photos.path(photo.extension, photo.filename)
        if not path.is_file():
            result.missing += 1
            continue
        fix = needs_letterbox(path, size)
        if fix is None:
            result.unreadable += 1
            continue
        result.frames.append((path, fix))
    return result


def letterbox(src: Path, dst: Path, size: Size) -> None:
    """Scale to fit inside size, pad with black, save as a plain RGB JPEG."""
    with Image.open(src) as im:
        im.draft("RGB", (size.width, size.height))  # fast JPEG downscale while decoding
        img = ImageOps.exif_transpose(im).convert("RGB")
    framed = ImageOps.pad(
        img, (size.width, size.height), method=Image.Resampling.LANCZOS, color=(0, 0, 0)
    )
    framed.save(dst, "JPEG", quality=92)


def link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.symlink(src, dst)
    except OSError:
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)


def prepare_frames(frames: list[tuple[Path, bool]], tmp: Path, size: Size) -> str:
    """Numbered frame files in tmp; returns the ffmpeg input pattern."""
    digits = max(6, len(str(len(frames))))
    for i, (src, fix) in enumerate(frames, 1):
        dst = tmp / f"{i:0{digits}d}.jpg"
        if fix:
            letterbox(src, dst, size)
        else:
            link_or_copy(src.resolve(), dst)
    return str(tmp / f"%0{digits}d.jpg")


# ---------------------------------------------------------------- ffmpeg


def _print(line: str) -> None:
    print(line, flush=True)


def run_ffmpeg(
    cmd: list[str],
    expected: int,
    *,
    on_frames: Callable[[int], None] | None = None,
    log: Callable[[str], None] = _print,
) -> int:
    """Run ffmpeg, log progress now and then, return the number of frames written.

    `on_frames(frames)` runs on every progress report (about twice a second);
    whatever it raises kills ffmpeg and propagates (the export jobs cancel so)."""
    frames = 0
    last_pct, last_time = 0, time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True, bufsize=1
        )
    except FileNotFoundError as exc:
        raise ToolError(
            f"{cmd[0]} not found; install ffmpeg or pass --ffmpeg PATH",
            user_message="ffmpeg ist auf dem Server nicht installiert.",
        ) from exc
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key == "frame" and value.isdigit():
                frames = int(value)
            elif key == "progress":
                if on_frames is not None:
                    on_frames(frames)
                pct = min(100, frames * 100 // max(1, expected))
                now = time.monotonic()
                if value == "end" or pct >= last_pct + 10 or now - last_time >= 15:
                    log(f"  encoding: {frames}/{expected} frames ({pct}%)")
                    last_pct, last_time = pct, now
        rc = proc.wait()
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    if rc != 0:
        raise ToolError(
            f"ffmpeg failed (exit code {rc}), see its messages above",
            user_message=f"ffmpeg ist fehlgeschlagen (Exit-Code {rc}). "
            "Die Meldungen stehen im Server-Log.",
        )
    return frames


def fmt_duration(seconds: float) -> str:
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f} min" if m else f"{s:.1f} s"


# ------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=PROG,
        description="Build a timelapse video (H.264 .mp4) from an extension's photos, "
        "in upload order. Needs ffmpeg with libx264.",
        epilog="examples:\n"
        f"  {PROG}\n"
        f"  {PROG} --fps 8 --crossfade\n"
        f"  {PROG} --fps 2 --crossfade --fade 0.3 --hold-last 4\n"
        f"  {PROG} --limit 100 --preset veryfast   # quick preview\n\n"
        "--crossfade repeats every photo up to --out-fps and averages the last K frames\n"
        "(ffmpeg tmix): linear crossfades of K frames, K = --fade x frames per photo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_data_dir_arg(p)
    p.add_argument("--extension", default="beer", help="whose photos to use (default: beer)")
    p.add_argument(
        "--fps",
        type=float,
        default=12.0,
        help="photos per second (default: 12; 0.5 = two seconds per photo)",
    )
    p.add_argument(
        "--crossfade",
        action="store_true",
        help="blend smoothly from photo to photo (the video then runs at --out-fps)",
    )
    p.add_argument(
        "--fade",
        type=float,
        default=0.5,
        metavar="F",
        help="with --crossfade: share of each photo's time spent fading into the next, "
        "0 < F <= 1 (default: 0.5; 1 = never sharp, continuous blending)",
    )
    p.add_argument(
        "--out-fps",
        type=float,
        metavar="FPS",
        help="frame rate of the video (default: 30 with --crossfade, else --fps; "
        "30 also helps slow slideshows play everywhere)",
    )
    p.add_argument(
        "--size",
        type=parse_size,
        default="1080x1440",
        metavar="WxH",
        help="video size; photos are scaled to fit and padded with black "
        "(default: 1080x1440, the Beer Cam's 3:4)",
    )
    p.add_argument(
        "--hold-last",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="keep the last photo on screen this long at the end (default: 2)",
    )
    p.add_argument(
        "--crf",
        type=int,
        default=20,
        help="H.264 quality: lower = better and bigger, 18-28 is sensible (default: 20)",
    )
    p.add_argument(
        "--preset",
        default="medium",
        choices=X264_PRESETS,
        metavar="PRESET",
        help="x264 speed/size trade-off, ultrafast..veryslow (default: medium)",
    )
    p.add_argument(
        "--include-hidden",
        action="store_true",
        help="also use photos the admin hid (default: leave them out)",
    )
    p.add_argument("--limit", type=int, metavar="N", help="only the first N photos (preview)")
    p.add_argument(
        "--out",
        metavar="FILE",
        help="output .mp4 or directory "
        "(default: <data-dir>/exports/<extension>-timelapse-<timestamp>.mp4, "
        "the time in $VB_TIMEZONE, default Europe/Berlin)",
    )
    p.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg binary (default: from PATH)")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="check the photos and print the ffmpeg command without encoding",
    )
    return p


def options_from_args(args: argparse.Namespace) -> Options:
    if not 0 < args.fps <= 120:
        raise ToolError("--fps must be above 0 and at most 120")
    out_fps = args.out_fps if args.out_fps is not None else (30.0 if args.crossfade else args.fps)
    if not 0 < out_fps <= 120:
        raise ToolError("--out-fps must be above 0 and at most 120")
    if args.crossfade and out_fps <= args.fps:
        raise ToolError(
            f"--crossfade needs --fps below the video frame rate ({out_fps:g}); "
            "lower --fps or raise --out-fps (e.g. 60)"
        )
    if out_fps < args.fps:
        raise ToolError("--out-fps below --fps would drop photos")
    if not 0 < args.fade <= 1:
        raise ToolError("--fade must be above 0 and at most 1")
    if not 0 <= args.hold_last <= 600:
        raise ToolError("--hold-last must be between 0 and 600 seconds")
    if not 0 <= args.crf <= 51:
        raise ToolError("--crf must be between 0 and 51")
    if args.limit is not None and args.limit < 1:
        raise ToolError("--limit must be at least 1")
    return Options(
        size=args.size,
        fps=args.fps,
        out_fps=out_fps,
        crossfade=args.crossfade,
        fade=args.fade,
        hold_last=args.hold_last,
        crf=args.crf,
        preset=args.preset,
    )


def output_path(args: argparse.Namespace, data_dir: Path) -> Path:
    name = f"{args.extension}-timelapse-{timestamp()}.mp4"
    if not args.out:
        return exports_dir(data_dir) / name
    out = Path(args.out).expanduser()
    return (out / name if out.is_dir() else out).resolve()


def _main(args: argparse.Namespace) -> int:
    o = options_from_args(args)
    data_dir = resolve_data_dir(args.data_dir)
    out = output_path(args, data_dir)

    print(f"Collecting {args.extension} photos from {data_dir} ...", flush=True)
    with open_repos(data_dir) as repos:
        got = collect(
            repos, args.extension, include_hidden=args.include_hidden, size=o.size, limit=args.limit
        )
        hidden_left_out = (
            0
            if args.include_hidden
            else repos.photos.count(args.extension)
            - repos.photos.count(args.extension, hidden=False)
        )
        counts = photo_counts(repos)

    notes = []
    if hidden_left_out:
        notes.append(f"{hidden_left_out} hidden left out")
    if got.missing:
        notes.append(f"{got.missing} with missing files skipped")
    if got.unreadable:
        notes.append(f"{got.unreadable} unreadable skipped")
    if got.letterboxed:
        notes.append(f"{got.letterboxed} letterboxed to {o.size}")
    n = len(got.frames)
    print(f"  {n} photos" + (f" ({'; '.join(notes)})" if notes else ""))

    if n == 0:
        others = ", ".join(f"{ext} ({c})" for ext, c in counts.items() if ext != args.extension)
        hint = f" Photos exist for: {others}." if others else ""
        if hidden_left_out:
            hint += " Use --include-hidden to use hidden photos."
        print(f"No photos to make a timelapse from for {args.extension!r}.{hint}")
        return 1

    expected = o.expected_frames(n)
    blend = f", crossfade over {o.mix_frames} frames" if o.crossfade else ""
    print(
        f"Video: {n} photos at {o.fps:g}/s{blend}, {o.size} @ {o.out_fps:g} fps, "
        f"~{expected} frames, ~{fmt_duration(expected / o.out_fps)}"
    )

    if args.dry_run:
        pattern = str(exports_dir(data_dir) / ".vb-timelapse-XXXX" / "%06d.jpg")
        cmd = build_command(args.ffmpeg, pattern, out, o)
        print("Dry run, nothing encoded. ffmpeg command (input = numbered links to the photos):")
        print("  " + shlex.join(cmd))
        return 0

    if shutil.which(args.ffmpeg) is None:
        raise ToolError(f"{args.ffmpeg} not found; install ffmpeg or pass --ffmpeg PATH")
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    # frame links (and letterboxed copies) live on the data volume, not in /tmp
    with tempfile.TemporaryDirectory(
        prefix=".vb-timelapse-", dir=scratch_parent(data_dir, out)
    ) as tmp:
        if got.letterboxed:
            print(f"Letterboxing {got.letterboxed} odd-sized photos ...", flush=True)
        pattern = prepare_frames(got.frames, Path(tmp), o.size)
        print("Encoding ...", flush=True)
        try:
            frames = run_ffmpeg(build_command(args.ffmpeg, pattern, part, o), expected)
            os.replace(part, out)
        finally:
            part.unlink(missing_ok=True)

    duration = frames / o.out_fps
    print(f"Done: {out}")
    print(
        f"  {frames} frames, {fmt_duration(duration)}, {o.size} @ {o.out_fps:g} fps, "
        f"{human_size(out.stat().st_size)}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(_main, build_parser(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
