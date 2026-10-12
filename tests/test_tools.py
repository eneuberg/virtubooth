"""CLI tools: timelapse (real ffmpeg runs), qr (codes + sheet), export (tarball).

Every test builds a real data dir: virtubooth.db through Database/Repo plus
solid-colour JPEGs at the paths core would use, so pixel checks can tell the
photos apart in the finished video.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import segno
from PIL import Image

from virtubooth.db import Database
from virtubooth.extension import Extension, UploadPolicy
from virtubooth.repo import Photo, Repo, User
from virtubooth.tools import _common, export, qr, timelapse

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")

RED, GREEN, BLUE = (255, 0, 0), (0, 255, 0), (0, 0, 255)
MAGENTA, CYAN, WHITE, YELLOW = (255, 0, 255), (0, 255, 255), (255, 255, 255), (255, 255, 0)
TOKEN = "Party-Token_0123456789abcdef"
SMALL = ["--size", "120x160", "--preset", "ultrafast"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The developer's own VB_* variables must not leak into the tools."""
    for name in list(os.environ):
        if name.startswith("VB_"):
            monkeypatch.delenv(name)


# ------------------------------------------------------------ sample data


@dataclass
class DataDir:
    path: Path
    db: Database
    repo: Repo
    users: dict[str, User] = field(default_factory=dict)
    photos: dict[str, Photo] = field(default_factory=dict)
    _n: int = 0

    def user(self, key: str, instagram: str | None = None) -> User:
        u = self.repo.create_user(
            consent_version="1", instagram=instagram, fp_hash=None, fp_components={},
            ip="10.0.0.1", user_agent="pytest",
        )  # fmt: skip
        self.users[key] = u
        return u

    def photo(
        self,
        key: str,
        ext: str,
        user: str,
        color: tuple[int, int, int],
        size: tuple[int, int] = (120, 160),
        meta: dict | None = None,
    ) -> Photo:
        """Write a solid-colour JPEG where core would and insert its row."""
        self._n += 1
        stem = f"20261012-21{self._n // 60:02d}{self._n % 60:02d}-000_{self._n:06x}"
        folder = self.path / ext
        (folder / "thumbs").mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", size, color)
        img.save(folder / f"{stem}.jpg", quality=95)
        img.resize((max(1, size[0] // 4), max(1, size[1] // 4))).save(
            folder / "thumbs" / f"{stem}.jpg"
        )
        p = self.repo.insert_photo(
            extension=ext,
            user_id=self.users[user].id,
            filename=f"{stem}.jpg",
            thumb_filename=f"thumbs/{stem}.jpg",
            width=size[0],
            height=size[1],
            size=(folder / f"{stem}.jpg").stat().st_size,
            meta=meta or {},
        )
        self.photos[key] = p
        return p

    def file(self, key: str) -> Path:
        p = self.photos[key]
        return self.repo.photo_path(p.extension, p.filename)


@pytest.fixture
def empty(tmp_path: Path) -> Iterator[DataDir]:
    path = tmp_path / "data"
    db = Database(path / "virtubooth.db")
    yield DataDir(path, db, Repo(db, path))
    db.close()


@pytest.fixture
def party(empty: DataDir) -> DataDir:
    """beer: 1 red, 2 green, 3 blue (hidden), 4 yellow (deleted), 5 magenta 200x100
    (odd size), 6 cyan (owner banned -> hidden), 7 white; booth: 2 square photos."""
    d = empty
    d.user("lisa", "lisa.party")
    d.user("anon")
    d.user("max", "max_m")
    d.user("troll", "troll")
    d.photo("b1", "beer", "lisa", RED, meta={"vessel": "bottle"})
    d.photo("b2", "beer", "anon", GREEN, meta={"vessel": "cup"})
    d.photo("b3", "beer", "max", BLUE)
    d.photo("b4", "beer", "lisa", YELLOW)
    d.photo("b5", "beer", "anon", MAGENTA, size=(200, 100))
    d.photo("b6", "beer", "troll", CYAN)
    d.photo("b7", "beer", "max", WHITE)
    d.photo("s1", "booth", "lisa", RED, size=(100, 100))
    d.photo("s2", "booth", "max", GREEN, size=(100, 100))
    assert d.repo.hide_photo(d.photos["b3"].public_id, "admin")
    assert d.repo.delete_photo(d.photos["b4"].public_id, "admin")
    assert d.repo.ban_user(d.users["troll"].id, "spam", "admin")
    return d


# ------------------------------------------------------------ ffmpeg helpers


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=codec_name,width,height,pix_fmt,r_frame_rate,nb_read_frames"
         ":format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    data = json.loads(out)
    s = data["streams"][0]
    return {
        "codec": s["codec_name"],
        "width": s["width"],
        "height": s["height"],
        "pix_fmt": s["pix_fmt"],
        "fps": s["r_frame_rate"],
        "frames": int(s["nb_read_frames"]),
        "duration": float(data["format"]["duration"]),
    }


def frames_rgb(path: Path, w: int, h: int) -> list[bytes]:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    ).stdout  # fmt: skip
    size = w * h * 3
    return [raw[i : i + size] for i in range(0, len(raw), size)]


def pixel(frame: bytes, w: int, x: int, y: int) -> tuple[int, int, int]:
    i = (y * w + x) * 3
    return frame[i], frame[i + 1], frame[i + 2]


def close(a: tuple[int, ...], b: tuple[int, ...], tol: int = 12) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def centre_colours(path: Path, w: int = 120, h: int = 160) -> list[tuple[int, int, int]]:
    return [pixel(f, w, w // 2, h // 2) for f in frames_rgb(path, w, h)]


# ---------------------------------------------------------------- _common


def test_resolve_data_dir_flag_env_default(monkeypatch, tmp_path):
    assert _common.resolve_data_dir(str(tmp_path / "x")) == tmp_path / "x"
    monkeypatch.setenv("VB_DATA_DIR", str(tmp_path / "env"))
    assert _common.resolve_data_dir(None) == tmp_path / "env"
    monkeypatch.delenv("VB_DATA_DIR")
    monkeypatch.chdir(tmp_path)
    assert _common.resolve_data_dir(None) == tmp_path / "data"


def test_open_repo_refuses_dir_without_db(tmp_path):
    with (
        pytest.raises(_common.ToolError, match="no virtubooth database"),
        _common.open_repo(tmp_path / "typo"),
    ):
        pass
    assert not (tmp_path / "typo").exists()  # no empty DB created by accident


def test_iter_photos_order_and_filters(party):
    keys = {p.public_id: k for k, p in party.photos.items()}
    visible = [
        keys[p.public_id] for p in _common.iter_photos(party.repo, extension="beer", hidden=False)
    ]
    both = [keys[p.public_id] for p in _common.iter_photos(party.repo, extension="beer")]
    assert visible == ["b1", "b2", "b5", "b7"]
    assert both == ["b1", "b2", "b3", "b5", "b6", "b7"]
    assert len(list(_common.iter_photos(party.repo))) == 8


@pytest.mark.parametrize("cli", ["timelapse", "qr", "export"])
def test_modules_run_as_scripts(cli):
    r = subprocess.run(
        [sys.executable, "-m", f"virtubooth.tools.{cli}", "--help"],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    assert f"python -m virtubooth.tools.{cli}" in r.stdout


# -------------------------------------------------------------- timelapse


def test_timelapse_options_and_filters():
    o = timelapse.Options(fps=2, out_fps=30, crossfade=True, fade=0.5, hold_last=0)
    assert o.mix_frames == 8  # half of the 15 frames each photo lasts
    assert timelapse.Options(fps=12, out_fps=30, crossfade=True, fade=0.1).mix_frames == 2
    assert o.expected_frames(10) == 150
    chain = timelapse.filter_chain(o)
    assert "fps=30" in chain and "tmix=frames=8" in chain and "tpad" not in chain
    plain = timelapse.filter_chain(timelapse.Options(fps=12, out_fps=12, hold_last=2))
    assert "tmix" not in plain and "fps=" not in plain
    assert "tpad=stop_mode=clone:stop_duration=2" in plain
    assert plain.startswith("scale=1080:1440:")
    assert timelapse.rate(12) == "12" and timelapse.rate(0.5) == "1/2"


def test_timelapse_parse_size():
    assert timelapse.parse_size("720x960") == timelapse.Size(720, 960)
    for bad in ("720", "721x960", "8x8", "abcxdef", "99999x100"):
        with pytest.raises(argparse.ArgumentTypeError):
            timelapse.parse_size(bad)


def test_needs_letterbox(tmp_path):
    size = timelapse.Size(120, 160)
    cases = {
        "same.jpg": ("RGB", (240, 320), "JPEG", False),
        "nearly.jpg": ("RGB", (241, 320), "JPEG", False),  # within 1 %: stretched
        "wide.jpg": ("RGB", (200, 100), "JPEG", True),
        "gray.jpg": ("L", (120, 160), "JPEG", True),
        "cmyk.jpg": ("CMYK", (120, 160), "JPEG", True),
        "png.jpg": ("RGB", (120, 160), "PNG", True),
    }
    for name, (mode, dims, fmt, expected) in cases.items():
        Image.new(mode, dims).save(tmp_path / name, fmt)
        assert timelapse.needs_letterbox(tmp_path / name, size) is expected, name
    (tmp_path / "broken.jpg").write_bytes(b"\xff\xd8\xffnot really")
    assert timelapse.needs_letterbox(tmp_path / "broken.jpg", size) is None


@needs_ffmpeg
def test_timelapse_video_frames_order_and_letterbox(party, tmp_path, capsys):
    out = tmp_path / "tl.mp4"
    rc = timelapse.main(
        ["--data-dir", str(party.path), "--fps", "4", "--hold-last", "1", "--out", str(out), *SMALL]
    )
    assert rc == 0
    info = probe(out)
    # 4 visible photos + 1 s of the last one at 4 fps
    assert info | {"duration": round(info["duration"], 2)} == {
        "codec": "h264", "width": 120, "height": 160, "pix_fmt": "yuv420p",
        "fps": "4/1", "frames": 8, "duration": 2.0,
    }  # fmt: skip
    colours = centre_colours(out)
    # upload order, hidden (blue, cyan) and deleted (yellow) left out, last one held
    for got, want in zip(colours, [RED, GREEN, MAGENTA, *[WHITE] * 5], strict=True):
        assert close(got, want), colours
    # the 200x100 photo is letterboxed: black bars above and below, not stretched
    frame = frames_rgb(out, 120, 160)[2]
    assert close(pixel(frame, 120, 60, 10), (0, 0, 0))
    assert close(pixel(frame, 120, 60, 150), (0, 0, 0))
    assert close(pixel(frame, 120, 5, 80), MAGENTA)
    text = capsys.readouterr().out
    assert "4 photos (2 hidden left out; 1 letterboxed to 120x160)" in text
    assert f"Done: {out}" in text and "8 frames" in text
    assert not out.with_name(out.name + ".part").exists()


@needs_ffmpeg
def test_timelapse_include_hidden(party, tmp_path):
    out = tmp_path / "all.mp4"
    args = ["--data-dir", str(party.path), "--hold-last", "0", "--include-hidden", *SMALL]
    assert timelapse.main([*args, "--out", str(out)]) == 0
    assert probe(out)["frames"] == 6
    colours = centre_colours(out)
    for got, want in zip(colours, [RED, GREEN, BLUE, MAGENTA, CYAN, WHITE], strict=True):
        assert close(got, want), colours


@needs_ffmpeg
def test_timelapse_default_size_and_output_path(empty, capsys):
    empty.user("u")
    empty.photo("a", "beer", "u", RED, size=(1080, 1440))
    empty.photo("b", "beer", "u", BLUE, size=(1080, 1440))
    assert timelapse.main(["--data-dir", str(empty.path), "--preset", "ultrafast"]) == 0
    videos = list((empty.path / "exports").glob("beer-timelapse-*.mp4"))
    assert len(videos) == 1
    info = probe(videos[0])
    # 2 photos + the default 2 s hold at the default 12 fps
    assert (info["width"], info["height"], info["fps"], info["frames"]) == (1080, 1440, "12/1", 26)
    assert list((empty.path / "exports").iterdir()) == videos  # no .part left behind


@needs_ffmpeg
def test_timelapse_crossfade_blends(empty, tmp_path):
    empty.user("u")
    empty.photo("a", "beer", "u", RED)
    empty.photo("b", "beer", "u", BLUE)
    out = tmp_path / "fade.mp4"
    rc = timelapse.main(
        ["--data-dir", str(empty.path), "--fps", "1", "--crossfade", "--fade", "0.5",
         "--hold-last", "1", "--out", str(out), *SMALL]
    )  # fmt: skip
    assert rc == 0
    info = probe(out)
    assert info["fps"] == "30/1"
    assert info["frames"] == 90  # 2 photos x 30 frames + 1 s hold
    colours = centre_colours(out)
    assert close(colours[10], RED) and close(colours[-1], BLUE)
    # 15-frame linear crossfade starting where the second photo starts (frame 30)
    mid = colours[37]
    assert 100 <= mid[0] <= 155 and 100 <= mid[2] <= 155 and mid[1] < 20, mid
    blended = [c for c in colours if not close(c, RED, 20) and not close(c, BLUE, 20)]
    assert 10 <= len(blended) <= 15, colours
    reds = [c[0] for c in colours[29:46]]
    assert reds == sorted(reds, reverse=True)  # monotonic fade, no jumps back


@needs_ffmpeg
def test_timelapse_thousands_of_photos(empty, tmp_path):
    empty.user("u")
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), GREEN).save(buf, "JPEG")
    folder = empty.path / "beer"
    folder.mkdir(parents=True)
    for i in range(2000):
        name = f"20261012-220000-000_{i:06x}.jpg"
        (folder / name).write_bytes(buf.getvalue())
        empty.repo.insert_photo(
            extension="beer", user_id=empty.users["u"].id, filename=name,
            thumb_filename=f"thumbs/{name}", width=32, height=32, size=len(buf.getvalue()), meta={},
        )  # fmt: skip
    out = tmp_path / "many.mp4"
    rc = timelapse.main(
        ["--data-dir", str(empty.path), "--fps", "100", "--hold-last", "0", "--size", "32x32",
         "--preset", "ultrafast", "--out", str(out)]
    )  # fmt: skip
    assert rc == 0
    info = probe(out)
    assert info["frames"] == 2000 and round(info["duration"], 2) == 20.0


def test_timelapse_no_photos_exit_1(empty, tmp_path, capsys):
    out = tmp_path / "none.mp4"
    assert timelapse.main(["--data-dir", str(empty.path), "--out", str(out)]) == 1
    assert "No photos" in capsys.readouterr().out
    assert not out.exists()


def test_timelapse_unknown_extension_hints(party, capsys):
    assert timelapse.main(["--data-dir", str(party.path), "--extension", "bier"]) == 1
    assert "Photos exist for: beer (6), booth (2)" in capsys.readouterr().out


def test_timelapse_only_hidden_suggests_flag(empty, capsys):
    empty.user("u")
    p = empty.photo("a", "beer", "u", RED)
    empty.repo.hide_photo(p.public_id, "admin")
    assert timelapse.main(["--data-dir", str(empty.path)]) == 1
    assert "--include-hidden" in capsys.readouterr().out


def test_timelapse_dry_run_runs_no_ffmpeg(party, tmp_path, monkeypatch, capsys):
    def boom(*a, **kw):
        raise AssertionError("ffmpeg must not run in a dry run")

    monkeypatch.setattr(subprocess, "Popen", boom)
    out = tmp_path / "dry.mp4"
    rc = timelapse.main(
        ["--data-dir", str(party.path), "--crossfade", "--fps", "6", "--dry-run",
         "--ffmpeg", "/nonexistent/ffmpeg", "--out", str(out)]
    )  # fmt: skip
    assert rc == 0
    text = capsys.readouterr().out
    assert "/nonexistent/ffmpeg -hide_banner" in text
    assert "-reinit_filter 0" in text and "tmix=frames=" in text and "+faststart" in text
    assert "4 photos" in text and "Dry run" in text
    assert not out.exists() and not (party.path / "exports").exists()


def test_timelapse_skips_missing_and_broken_files(party, capsys):
    party.file("b2").unlink()
    party.file("b7").write_bytes(b"garbage")
    assert timelapse.main(["--data-dir", str(party.path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "2 photos (" in out and "1 with missing files skipped" in out
    assert "1 unreadable skipped" in out


@pytest.mark.parametrize(
    "args, message",
    [
        (["--crossfade", "--fps", "30"], "--crossfade needs --fps below"),
        (["--fps", "0"], "--fps must be above 0"),
        (["--fade", "1.5", "--crossfade", "--fps", "2"], "--fade must be"),
        (["--out-fps", "5", "--fps", "10"], "would drop photos"),
        (["--crf", "60"], "--crf must be"),
    ],
)
def test_timelapse_rejects_bad_options(party, capsys, args, message):
    assert timelapse.main(["--data-dir", str(party.path), *args]) == 1
    assert message in capsys.readouterr().err


def test_timelapse_without_ffmpeg_binary(party, tmp_path, capsys):
    out = tmp_path / "x.mp4"
    rc = timelapse.main(["--data-dir", str(party.path), "--ffmpeg", "/nonexistent/ffmpeg",
                         "--out", str(out)])  # fmt: skip
    assert rc == 1
    assert "/nonexistent/ffmpeg not found" in capsys.readouterr().err
    assert not out.exists()


def test_timelapse_missing_db(tmp_path, capsys):
    assert timelapse.main(["--data-dir", str(tmp_path / "nope")]) == 1
    assert "no virtubooth database" in capsys.readouterr().err


@pytest.fixture
def no_system_temp(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Fail on any use of the system temp dir (a 256 MB noexec tmpfs in the
    container) and record every TemporaryDirectory the tools create."""
    created: list[Path] = []
    real = tempfile.TemporaryDirectory

    def spy(*args, **kwargs):
        assert kwargs.get("dir"), "TemporaryDirectory without dir= would land in /tmp"
        td = real(*args, **kwargs)
        created.append(Path(td.name))
        return td

    def forbidden() -> str:
        raise AssertionError("the system temp dir must not be used")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", spy)
    monkeypatch.setattr(tempfile, "gettempdir", forbidden)
    monkeypatch.setattr(tempfile, "tempdir", "/nonexistent-system-tmp")
    return created


@needs_ffmpeg
def test_timelapse_stages_frames_under_data_dir(party, tmp_path, no_system_temp, monkeypatch):
    seen: dict = {}
    real_run = timelapse.run_ffmpeg

    def spy_run(cmd, expected):
        stage = Path(cmd[cmd.index("-i") + 1]).parent
        seen["stage"] = stage
        seen["files"] = {f.name: (f.is_symlink(), f.resolve()) for f in stage.iterdir()}
        return real_run(cmd, expected)

    monkeypatch.setattr(timelapse, "run_ffmpeg", spy_run)
    out = tmp_path / "elsewhere" / "tl.mp4"  # output outside the data dir on purpose
    assert timelapse.main(["--data-dir", str(party.path), "--out", str(out), *SMALL]) == 0
    stage = seen["stage"]
    assert no_system_temp == [stage]
    assert stage.parent == party.path / "exports" and stage.name.startswith(".vb-timelapse-")
    assert not stage.exists()  # cleaned up
    # the originals are linked, only the odd-sized photo got a (letterboxed) copy
    assert seen["files"] == {
        "000001.jpg": (True, party.file("b1")),
        "000002.jpg": (True, party.file("b2")),
        "000003.jpg": (False, stage / "000003.jpg"),
        "000004.jpg": (True, party.file("b7")),
    }
    assert out.is_file() and list((party.path / "exports").iterdir()) == []


def test_export_stages_under_data_dir(party, tmp_path, no_system_temp, monkeypatch):
    opened: list[Path] = []
    real_open = tarfile.open

    def spy_open(name, *args, **kwargs):
        opened.append(Path(name))
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr(tarfile, "open", spy_open)
    assert export.main(["--data-dir", str(party.path)]) == 0
    exports = party.path / "exports"
    (snapshot_dir,) = no_system_temp
    assert snapshot_dir.parent == exports and snapshot_dir.name.startswith(".vb-export-")
    assert not snapshot_dir.exists()
    # the tarball is written in place (as .part, then renamed), not copied from /tmp
    (archive,) = exports.iterdir()
    assert opened == [archive.with_name(archive.name + ".part")]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_scratch_parent_falls_back_to_output_dir(tmp_path):
    data = tmp_path / "data"
    (data / "exports").mkdir(parents=True)
    out = tmp_path / "out" / "x.mp4"
    out.parent.mkdir()
    assert _common.scratch_parent(data, out) == data / "exports"
    (data / "exports").chmod(0o555)  # e.g. a read-only copy of the data dir
    try:
        assert _common.scratch_parent(data, out) == out.parent
    finally:
        (data / "exports").chmod(0o755)


# --------------------------------------------------------------------- qr


@pytest.fixture
def fake_exts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Extension]:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html>")
    exts = [
        Extension(id="beer", title="Beer Cam", emoji="🍺", tagline="Prost & <Zeitraffer>",
                  static_dir=static, upload=UploadPolicy(), order=10),
        Extension(id="booth", title="Fotobox", emoji="📸", tagline="Filter, Countdown, Selfie",
                  static_dir=static, upload=UploadPolicy(), order=20),
        Extension(id="wall", title="Live Wall", emoji="🖼️", tagline="Für den Beamer",
                  static_dir=static, show_on_home=False, order=30),
    ]  # fmt: skip

    def discover(enabled=None):  # like the real one: filter, then sort by `order`
        return [e for e in exts if enabled is None or e.id in enabled]

    monkeypatch.setattr(qr, "discover_extensions", discover)
    return exts


def qr_main(out: Path, *extra: str) -> int:
    return qr.main(["--base-url", "https://party.example.com/", "--token", TOKEN,
                    "--out", str(out), *extra])  # fmt: skip


def test_qr_urls():
    base = qr.normalize_base_url("https://party.example.com/ ")
    assert base == "https://party.example.com"
    assert qr.home_url(base, TOKEN) == f"https://party.example.com/?t={TOKEN}"
    assert qr.extension_url(base, TOKEN, "beer") == f"https://party.example.com/x/beer/?t={TOKEN}"
    sub = qr.normalize_base_url("https://example.com/party/")
    assert qr.extension_url(sub, TOKEN, "booth") == f"https://example.com/party/x/booth/?t={TOKEN}"
    for bad in ("party.example.com", "ftp://x", "https://x/?a=1", "https://"):
        with pytest.raises(_common.ToolError):
            qr.normalize_base_url(bad)


def test_qr_writes_codes_and_sheet(fake_exts, tmp_path, capsys):
    out = tmp_path / "qr"
    assert qr_main(out, "--party-name", "Eriks Party") == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == [
        "qr-beer.png",
        "qr-beer.svg",
        "qr-booth.png",
        "qr-booth.svg",
        "qr-home.png",
        "qr-home.svg",
        "qr-sheet.html",
    ]  # fmt: skip  (wall is not on the home page, so no code by default)
    sheet = (out / "qr-sheet.html").read_text()
    assert sheet.count('<section class="card"') == 3
    for text in (
        "🍺",
        "Beer Cam",
        "Prost &amp; &lt;Zeitraffer&gt;",
        "📸",
        "Fotobox",
        "Eriks Party",
        "🎉",
        qr.INSTRUCTION,
        "@page",
        "size: A4",
        "break-after: page",
    ):
        assert text in sheet, text  # fmt: skip
    # the token is only inside the codes: not as text in the sheet or the SVGs
    assert TOKEN not in sheet and "?t=" not in sheet
    for svg in out.glob("*.svg"):
        assert TOKEN not in svg.read_text()
    # the sheet's inline codes are exactly the codes for the right URLs
    for url in (qr.home_url("https://party.example.com", TOKEN),
                qr.extension_url("https://party.example.com", TOKEN, "beer")):  # fmt: skip
        inline = qr.make_qr(url).svg_inline(scale=1, border=4, dark="#000", light="#fff",
                                            omitsize=True)  # fmt: skip
        assert inline in sheet
    printed = capsys.readouterr().out
    assert TOKEN not in printed and "?t=<token>" in printed


def read_png_matrix(path: Path, modules: int, border: int = 4) -> list[list[int]]:
    img = Image.open(path).convert("L")
    scale = img.width / modules
    assert img.width == img.height and scale == int(scale)
    return [
        [int(img.getpixel((int((x + 0.5) * scale), int((y + 0.5) * scale))) < 128)
         for x in range(border, modules - border)]
        for y in range(border, modules - border)
    ]  # fmt: skip


def test_qr_pngs_encode_the_urls_with_high_error_correction(fake_exts, tmp_path):
    out = tmp_path / "qr"
    assert qr_main(out, "--extensions", "booth,beer") == 0
    for key, url in {
        "home": f"https://party.example.com/?t={TOKEN}",
        "beer": f"https://party.example.com/x/beer/?t={TOKEN}",
        "booth": f"https://party.example.com/x/booth/?t={TOKEN}",
    }.items():
        code = segno.make_qr(url, error="h", boost_error=False)
        assert code.error == "H"
        modules = code.symbol_size(scale=1, border=4)[0]
        expected = [[int(bool(v)) for v in row] for row in code.matrix]
        assert read_png_matrix(out / f"qr-{key}.png", modules) == expected, key
        assert Image.open(out / f"qr-{key}.png").width >= qr.PNG_MIN_PX
    sheet = (out / "qr-sheet.html").read_text()
    # home first, then extensions in their `order`
    assert (
        sheet.index('id="card-home"')
        < sheet.index('id="card-beer"')
        < sheet.index('id="card-booth"')
    )


def test_qr_named_extensions_include_hidden_ones_and_no_home(fake_exts, tmp_path):
    out = tmp_path / "qr"
    assert qr_main(out, "--extensions", "wall", "--no-home") == 0
    assert sorted(p.name for p in out.iterdir()) == ["qr-sheet.html", "qr-wall.png", "qr-wall.svg"]


def test_qr_env_defaults(fake_exts, tmp_path, monkeypatch):
    monkeypatch.setenv("VB_PUBLIC_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("VB_PARTY_TOKEN", TOKEN)
    monkeypatch.setenv("VB_EXTENSIONS", "beer")
    monkeypatch.setenv("VB_PARTY_NAME", "Envparty")
    monkeypatch.setenv("VB_DATA_DIR", str(tmp_path / "data"))
    assert qr.main([]) == 0
    out = tmp_path / "data" / "exports" / "qr"
    assert sorted(p.name for p in out.glob("*.svg")) == ["qr-beer.svg", "qr-home.svg"]
    assert "Envparty" in (out / "qr-sheet.html").read_text()


def test_qr_missing_or_bad_token(fake_exts, tmp_path, capsys):
    base = ["--base-url", "https://party.example.com", "--out", str(tmp_path / "qr")]
    assert qr.main(base) == 1
    assert "no party token" in capsys.readouterr().err
    assert qr.main([*base, "--token", "short"]) == 1
    assert "16-128 chars" in capsys.readouterr().err
    assert not (tmp_path / "qr").exists()


def test_qr_missing_base_url(fake_exts, tmp_path, capsys):
    assert qr.main(["--token", TOKEN, "--out", str(tmp_path / "qr")]) == 1
    assert "no base URL" in capsys.readouterr().err


def test_qr_unknown_extension_with_real_discovery(tmp_path, capsys):
    rc = qr.main(["--base-url", "https://x.example", "--token", TOKEN,
                  "--extensions", "does-not-exist", "--out", str(tmp_path / "qr")])  # fmt: skip
    assert rc == 1
    assert "unknown extensions" in capsys.readouterr().err


def test_qr_warns_about_plain_http(fake_exts, tmp_path, capsys):
    assert qr.main(["--base-url", "http://party.example.com", "--token", TOKEN,
                    "--out", str(tmp_path / "qr")]) == 0  # fmt: skip
    assert "https" in capsys.readouterr().out


# ----------------------------------------------------------------- export


def read_tar(path: Path) -> tuple[str, dict[str, bytes]]:
    with tarfile.open(path, "r:gz") as tar:
        files = {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}
    roots = {name.split("/", 1)[0] for name in files}
    assert len(roots) == 1, roots
    root = roots.pop()
    return root, {name[len(root) + 1 :]: data for name, data in files.items()}


def read_csv(data: bytes) -> list[dict[str, str]]:
    assert data.startswith(b"\xef\xbb\xbf")  # BOM for Excel
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def run_export(party: DataDir, tmp_path: Path, *extra: str) -> tuple[str, dict[str, bytes]]:
    out = tmp_path / "party-export.tar.gz"
    assert export.main(["--data-dir", str(party.path), "--out", str(out), *extra]) == 0
    assert not out.with_name(out.name + ".part").exists()
    return read_tar(out)


def test_export_layout(party, tmp_path):
    # leftovers of earlier tool runs must never end up in the archive
    (party.path / "exports").mkdir()
    (party.path / "exports" / "old-export.tar.gz").write_bytes(b"x")
    root, files = run_export(party, tmp_path)
    assert root == "party-export"
    photos = sorted(n for n in files if n.startswith("photos/"))
    name = {k: Path(p.filename).name for k, p in party.photos.items()}
    assert photos == sorted([
        f"photos/beer/0001_{name['b1']}", f"photos/beer/0002_{name['b2']}",
        f"photos/beer/hidden/0003_{name['b3']}", f"photos/beer/0005_{name['b5']}",
        f"photos/beer/hidden/0006_{name['b6']}", f"photos/beer/0007_{name['b7']}",
        f"photos/booth/0001_{name['s1']}", f"photos/booth/0002_{name['s2']}",
    ])  # fmt: skip
    assert set(files) - set(photos) == {
        "README.txt", "photos.csv", "users.csv", "instagram.csv", "virtubooth.db",
    }  # fmt: skip
    assert files[f"photos/beer/0005_{name['b5']}"] == party.file("b5").read_bytes()
    readme = files["README.txt"].decode()
    assert "photos/<activity>/hidden/" in readme and "virtubooth.db" in readme
    assert "beer 4 + 2 hidden, booth 2" in readme


def test_export_photos_csv(party, tmp_path):
    _, files = run_export(party, tmp_path)
    rows = read_csv(files["photos.csv"])
    assert list(rows[0]) == export.PHOTO_COLUMNS
    by_id = {r["id"]: r for r in rows}
    assert len(rows) == 8 and party.photos["b4"].public_id not in by_id  # deleted
    b1 = by_id[party.photos["b1"].public_id]
    assert b1 == b1 | {
        "extension": "beer", "seq": "1", "user": party.users["lisa"].name,
        "instagram": "lisa.party", "hidden": "0", "hidden_reason": "", "width": "120",
        "height": "160", "file": f"photos/beer/0001_{Path(party.photos['b1'].filename).name}",
    }  # fmt: skip
    assert json.loads(b1["meta"]) == {"vessel": "bottle"}
    assert b1["created_at"] == party.photos["b1"].created_at
    b6 = by_id[party.photos["b6"].public_id]
    assert (b6["hidden"], b6["hidden_reason"]) == ("1", "ban")
    assert b6["file"].startswith("photos/beer/hidden/")
    for r in rows:
        assert r["file"] in files  # every listed path is in the archive


def test_export_users_and_instagram_csv(party, tmp_path):
    _, files = run_export(party, tmp_path)
    users = {r["user"]: r for r in read_csv(files["users.csv"])}
    assert list(next(iter(users.values()))) == export.USER_COLUMNS
    assert len(users) == 4
    lisa, troll = users[party.users["lisa"].name], users[party.users["troll"].name]
    assert (lisa["instagram"], lisa["photo_count"], lisa["banned"]) == ("lisa.party", "2", "0")
    assert (troll["banned"], troll["ban_reason"], troll["photo_count"]) == ("1", "spam", "1")
    assert lisa["consent_at"] == party.users["lisa"].consent_at

    insta = {r["instagram"]: r for r in read_csv(files["instagram.csv"])}
    # anon has no handle, troll is banned; max's hidden beer photo is not taggable
    assert sorted(insta) == ["lisa.party", "max_m"]
    max_files = insta["max_m"]["files"].split("; ")
    assert insta["max_m"]["photo_count"] == "2" and len(max_files) == 2
    assert all(f in files and "/hidden/" not in f for f in max_files)
    assert insta["lisa.party"]["user"] == party.users["lisa"].name


def test_export_no_hidden(party, tmp_path):
    _, files = run_export(party, tmp_path, "--no-hidden")
    assert not [n for n in files if "/hidden/" in n]
    rows = read_csv(files["photos.csv"])
    assert len(rows) == 6 and {r["hidden"] for r in rows} == {"0"}
    assert "left out of this export (--no-hidden)" in files["README.txt"].decode()


def test_export_db_copy(party, tmp_path):
    _, files = run_export(party, tmp_path)
    assert "virtubooth.db-wal" not in files and "virtubooth.db-shm" not in files
    db_file = tmp_path / "copy.db"
    db_file.write_bytes(files["virtubooth.db"])
    conn = sqlite3.connect(db_file)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        # the full database: deleted tombstone and hidden rows included
        assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 9
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 4
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] >= 3
    finally:
        conn.close()


def test_export_no_db(party, tmp_path):
    _, files = run_export(party, tmp_path, "--no-db")
    assert "virtubooth.db" not in files
    assert "virtubooth.db" not in files["README.txt"].decode()


def test_export_default_path_and_missing_file(party, capsys):
    party.file("b2").unlink()
    assert export.main(["--data-dir", str(party.path)]) == 0
    archives = list((party.path / "exports").glob("virtubooth-export-*.tar.gz"))
    assert len(archives) == 1 and list((party.path / "exports").iterdir()) == archives
    root, files = read_tar(archives[0])
    assert root == archives[0].name.removesuffix(".tar.gz")
    rows = {r["id"]: r for r in read_csv(files["photos.csv"])}
    assert rows[party.photos["b2"].public_id]["file"] == ""
    printed = capsys.readouterr().out
    assert "1 photo(s) have no file" in printed
    assert "2 Instagram handles to tag" in printed  # same rule as instagram.csv


def test_export_survives_photo_deleted_while_packing(party, tmp_path, monkeypatch):
    real_add = tarfile.TarFile.add
    victim = party.file("b7")

    def flaky_add(self, name, *args, **kwargs):
        if Path(name) == victim:
            raise FileNotFoundError(name)
        return real_add(self, name, *args, **kwargs)

    monkeypatch.setattr(tarfile.TarFile, "add", flaky_add)
    _, files = run_export(party, tmp_path)
    rows = {r["id"]: r for r in read_csv(files["photos.csv"])}
    assert rows[party.photos["b7"].public_id]["file"] == ""
    assert all(r["file"] in files for r in rows.values() if r["file"])
    insta = {r["instagram"]: r for r in read_csv(files["instagram.csv"])}
    assert insta["max_m"]["photo_count"] == "1"


def test_export_snapshot_while_app_holds_the_db(party, tmp_path):
    """The live app keeps its connection open (WAL); the export must still be consistent."""
    party.user("late", "late.one")
    party.photo("late", "beer", "late", RED)  # committed through the app's connection
    _, files = run_export(party, tmp_path)
    assert any(r["instagram"] == "late.one" for r in read_csv(files["instagram.csv"]))


def test_export_missing_db(tmp_path, capsys):
    assert export.main(["--data-dir", str(tmp_path / "nope")]) == 1
    assert "no virtubooth database" in capsys.readouterr().err
    assert not (tmp_path / "nope").exists()


def test_export_archive_root_names():
    assert export.archive_root(Path("a/b/party.tar.gz")) == "party"
    assert export.archive_root(Path("party.tgz")) == "party"
    assert export.archive_root(Path("party.zip")) == "party.zip"


def test_csv_cells_never_become_formulas():
    assert export._cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert export._cell("@x") == "'@x"
    assert export._cell("-1") == "'-1"
    assert export._cell("Durstige Giraffe #3") == "Durstige Giraffe #3"
    assert export._cell(5) == 5
