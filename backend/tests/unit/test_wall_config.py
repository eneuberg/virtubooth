"""WallConfig (PLAN-WALL §4.1): defaults, every range, the playlist rules,
colours, sources, strict types, and loading what is stored."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from virtubooth.core.errors import ApiError
from virtubooth.db.database import Database
from virtubooth.extensions.wall.config import (
    CONFIG_KEY,
    WallConfig,
    load_config,
    parse_settings,
)
from virtubooth.repositories.app_settings import AppSettingsRepo

DEFAULTS = {
    "rev": 0,
    "updated_at": None,
    "by": None,
    "playlist": [
        {"mode": "spotlight", "enabled": True, "duration_s": 120},
        {"mode": "gallery", "enabled": True, "duration_s": 45},
        {"mode": "categories", "enabled": True, "duration_s": 60},
    ],
    "spotlight": {
        "algorithm": "fresh_first",
        "n": 12,
        "interval_s": 8,
        "transition": "random",
        "transition_ms": 1200,
    },
    "gallery": {"speed": "medium", "rows": 3},
    "categories": {"per_category_s": 10, "disabled": []},
    "sources": [],
    "delay_s": 20,
    "show_instagram": False,
    "look": {
        "preset": "blobs",
        # null: wie Theme (Allgemeines → Erscheinungsbild)
        "primary": None,
        "secondary": None,
        "background": None,
        "fps": 30,
        "calm": False,
    },
    "overlay": {
        "event_name": True,
        "counter": True,
        "qr": False,
        "qr_code_id": None,
        "corner": "bottom-right",
    },
}
UPLOADS = ("beer", "booth")


def parse(data):
    return parse_settings(data, UPLOADS)


def with_value(path: str, value):
    data = copy.deepcopy(DEFAULTS)
    target = data
    *parents, last = path.split(".")
    for part in parents:
        target = target[int(part)] if part.isdigit() else target[part]
    target[int(last) if last.isdigit() else last] = value
    return data


def field_error(data) -> str:
    with pytest.raises(ApiError) as exc:
        parse(data)
    assert exc.value.status == 400 and exc.value.code == "invalid_wall_config"
    return exc.value.message


def test_defaults_match_the_contract():
    assert WallConfig().model_dump(mode="json") == DEFAULTS
    assert parse({}).model_dump(mode="json") == {
        k: v for k, v in DEFAULTS.items() if k not in ("rev", "updated_at", "by")
    }


RANGES = [
    ("playlist.0.duration_s", 10, 3600),
    ("spotlight.n", 1, 100),
    ("spotlight.interval_s", 3, 120),
    ("spotlight.transition_ms", 300, 4000),
    ("gallery.rows", 2, 6),
    ("categories.per_category_s", 4, 60),
    ("delay_s", 0, 600),
]


@pytest.mark.parametrize(("path", "low", "high"), RANGES)
def test_every_range(path, low, high):
    for ok in (low, high):
        parse(with_value(path, ok))
    field = ".".join(p for p in path.split(".") if not p.isdigit())
    for bad in (low - 1, high + 1):
        assert field_error(with_value(path, bad)) == f"Ungültige Einstellung: {field}."


@pytest.mark.parametrize(
    ("path", "value", "field"),
    [
        ("spotlight.algorithm", "best", "spotlight.algorithm"),
        ("spotlight.transition", "wipe", "spotlight.transition"),
        ("gallery.speed", "ludicrous", "gallery.speed"),
        ("look.preset", "lava", "look.preset"),
        ("look.fps", 45, "look.fps"),
        ("overlay.corner", "middle", "overlay.corner"),
        ("playlist.0.mode", "slideshow", "playlist.mode"),
        # strict: no strings for numbers, no numbers for booleans
        ("spotlight.n", "12", "spotlight.n"),
        ("delay_s", True, "delay_s"),
        ("show_instagram", 1, "show_instagram"),
        ("sources", ["Not An Id"], "sources"),
    ],
)
def test_bad_values_name_the_field(path, value, field):
    assert field_error(with_value(path, value)) == f"Ungültige Einstellung: {field}."


def test_playlist_needs_each_mode_once_and_one_enabled():
    playlist = copy.deepcopy(DEFAULTS["playlist"])
    assert "playlist" in field_error(with_value("playlist", playlist[:2]))
    twice = [*playlist[:2], {**playlist[0]}]
    assert "playlist" in field_error(with_value("playlist", twice))
    off = [{**e, "enabled": False} for e in playlist]
    assert "playlist" in field_error(with_value("playlist", off))
    one = [{**e, "enabled": e["mode"] == "gallery"} for e in playlist]
    reordered = list(reversed(one))
    assert [e.mode for e in parse(with_value("playlist", reordered)).playlist] == [
        "categories",
        "gallery",
        "spotlight",
    ]


def test_colours_are_lower_cased_and_checked():
    data = with_value("look.primary", "#A855F7")
    assert parse(data).look.primary == "#a855f7"
    for bad in ("#abc", "a855f7", "#a855f7ff", "#gggggg", "red"):
        assert field_error(with_value("look.secondary", bad)) == (
            "Ungültige Einstellung: look.secondary."
        )


def test_sources_must_be_upload_extensions():
    assert parse(with_value("sources", ["booth", "booth"])).sources == ["booth"]
    assert field_error(with_value("sources", ["booth", "wall"])) == (
        "Ungültige Einstellung: sources."
    )


def test_the_old_disabled_list_is_accepted_and_ignored():
    """Categories live in `wall_categories` now; an old client's list is no error."""
    data = with_value("categories.disabled", ["Volles Haus", 3])
    assert parse(data).categories.model_dump() == {"per_category_s": 10, "disabled": []}


def test_server_fields_and_unknown_keys_are_ignored():
    data = {**DEFAULTS, "rev": 99, "by": "hacker", "updated_at": "x", "extra": {"a": 1}}
    settings = parse(data)
    assert "rev" not in settings.model_dump() and "extra" not in settings.model_dump()


@pytest.mark.parametrize("data", [None, [], "config", 3])
def test_not_an_object(data):
    assert field_error(data) == "Ungültige Einstellung: config."


def test_load_config(tmp_path: Path):
    db = Database(tmp_path / "t.db")
    repo = AppSettingsRepo(db)
    try:
        assert load_config(repo) == WallConfig()
        stored = with_value("delay_s", 5) | {"rev": 3}
        repo.put(CONFIG_KEY, stored, at="2026-10-13T20:00:00.000+00:00")
        assert load_config(repo).delay_s == 5 and load_config(repo).rev == 3
        # a stored value that no longer validates falls back to the defaults
        repo.put(CONFIG_KEY, with_value("delay_s", -1), at="2026-10-13T20:00:00.000+00:00")
        assert load_config(repo) == WallConfig()
    finally:
        db.close()
