"""The preset categories: the 19 classic Live-Wall categories as CategorySpecs
(same winners as before, `tests/unit/test_enrich_presets_golden.py`) plus
„Das coolste Objekt“ (needs an LLM property `coolness`, off by default).

`ensure_seeded()` writes them into `wall_categories` once (settings key
`x.wall.categories_seeded`), taking over the old `WallConfig.categories.
disabled` list; `restore()` („Vorlagen wiederherstellen“) adds the presets
that were deleted since.
"""

from __future__ import annotations

from typing import Any

from ....core.clock import now_iso
from ....db.database import Database
from ....repositories.app_settings import AppSettingsRepo
from . import engine

SEEDED_KEY = "x.wall.categories_seeded"
CONFIG_KEY = "x.wall.config"  # the wall's settings: its old `categories.disabled`

# action_shot: only photos this blurry qualify (Laplacian variance at 512 px;
# sharp photos are in the hundreds), and not nearly black or white
BLUR_MAX = 80.0
# dauerausloeser: at least this many visible photos
MIN_PHOTOS = 5


def _w(value: str, op: str, operand: Any = None) -> dict[str, Any]:
    return {"value": value, "op": op, "operand": operand}


def _spec(
    emoji: str, title: str, line: str, where: list[dict[str, Any]], by: str, *,
    order: str = "top", count: int = 3, then_by: tuple[str, ...] = (), one_per_guest: bool = True,
    value: str | None = None, style: str = "count", one: str = "", many: str = "",
    verdict: str | None = None,
) -> dict[str, Any]:  # fmt: skip
    return {
        "emoji": emoji, "title": title, "line": line, "where": where,
        "select": {"by": by, "order": order, "count": count,
                   "then_by": [{"by": t, "order": "top"} for t in then_by],
                   "one_per_guest": one_per_guest},
        "label": {"value": value, "style": style, "one": one, "many": many},
        "verdict": {"prompt": verdict} if verdict else None,
    }  # fmt: skip


def _at_least(fact: str, n: float) -> list[dict[str, Any]]:
    return [_w(fact, "gte", n)]


# (id, spec, enabled by default), in the wall's order
PRESETS: tuple[tuple[str, dict[str, Any], bool], ...] = (
    ("volles_haus", _spec("👥", "Volles Haus", "Die meisten Leute auf einem Foto",
                          _at_least("people", 3), "people", one="Person", many="Personen"), True),
    ("haende_hoch", _spec("🙌", "Hände hoch!", "Die meisten Hände in der Luft",
                          _at_least("hands", 3), "hands", one="Hand", many="Hände"), True),
    ("grinsekatzen", _spec("😁", "Grinsekatzen", "Die meisten Lächeln auf einem Bild",
                           _at_least("smiles", 2), "smiles", one="Lächeln", many="Lächeln"), True),
    ("herzschmerz", _spec("🥺", "Herzschmerz-Pose", "Der dramatischste Schmollblick des Abends",
                          _at_least("sad_max", 0.5), "sad_max", style="percent", one="Drama",
                          many="Drama"), True),
    ("ach_du_schreck", _spec("😱", "Ach du Schreck!", "Das überraschteste Gesicht",
                             _at_least("surprise_max", 0.5), "surprise_max", style="percent",
                             one="Schreck", many="Schreck"), True),
    ("brillenbande", _spec("🤓", "Brillenbande", "Die meisten Brillen auf einem Foto",
                           _at_least("glasses", 1), "glasses", one="Brille", many="Brillen"), True),
    # ranked by the age spread (FairFace, when on) first, then by the age groups
    ("generationen", _spec("🎂", "Generationen-Foto", "Die größte Altersspanne auf einem Bild",
                           _at_least("age_groups", 2), "age_spread", then_by=("age_groups",),
                           value="age_groups", one="Generation", many="Generationen"), True),
    ("dream_team", _spec("👯", "Dream-Team", "Zwei Leute, doppelt gute Laune",
                         [_w("people", "eq", 2), _w("smiles", "eq", 2)], "happy_max",
                         then_by=("smiles",), value="smiles", style="fixed",
                         one="2 Leute, 2 Lächeln"), True),
    ("solo_star", _spec("🌟", "Solo-Star", "Ganz nah dran",
                        [_w("faces", "eq", 1), _w("face_area_max", "gte", 0.12)],
                        "face_area_max", style="percent", one="Gesicht", many="Gesicht"), True),
    ("peace", _spec("✌️", "Peace!", "Die meisten Victory-Zeichen", _at_least("peace", 1), "peace",
                    one="Peace-Zeichen", many="Peace-Zeichen"), True),
    ("rock", _spec("🤘", "Rock'n'Roll", "Die meisten Pommesgabeln", _at_least("rock", 1), "rock",
                   one="Pommesgabel", many="Pommesgabeln"), True),
    ("daumen_hoch", _spec("👍", "Daumen hoch", "Die meisten Daumen nach oben",
                          _at_least("thumbs_up", 1), "thumbs_up", one="Daumen", many="Daumen"),
     True),
    ("prost", _spec("🥂", "Prost!", "Die meisten Gläser im Bild", _at_least("drinks", 2), "drinks",
                    one="Glas", many="Gläser"), True),
    ("hutparade", _spec("🎩", "Hutparade", "Die meisten Hüte und Kappen", _at_least("hats", 1),
                        "hats", one="Hut", many="Hüte"), True),
    ("gesangseinlage", _spec("🎤", "Gesangseinlage", "Die meisten offenen Münder",
                             _at_least("mouth_open", 2), "mouth_open", one="offener Mund",
                             many="offene Münder"), True),
    ("farbexplosion", _spec("🌈", "Farbexplosion", "Das bunteste Foto",
                            _at_least("colorfulness", 40), "colorfulness", style="number",
                            one="Farbwert", many="Farbwert"), True),
    ("action_shot", _spec("💨", "Action-Shot", "So viel Bewegung, die Kamera kam kaum mit",
                          [_w("sharpness", "lte", BLUR_MAX), _w("brightness", "gte", 0.1),
                           _w("brightness", "lte", 0.92)], "sharpness", order="bottom",
                          style="fixed", one="volle Bewegung"), True),
    ("eroeffnung", _spec("🎬", "Eröffnungsfoto", "Das allererste Foto des Abends", [],
                         "photo.created_at", order="bottom", count=1, one_per_guest=False,
                         style="time"), True),
    ("dauerausloeser", _spec("📸", "Dauerauslöser",
                             "Die meisten Fotos von einer Person (hier das neueste)",
                             [_w("photo.guest_photos", "gte", MIN_PHOTOS)], "photo.guest_photos",
                             one="Foto", many="Fotos"), True),
    ("coolstes_objekt", _spec("🏆", "Das coolste Objekt", "Was die KI am coolsten findet",
                              [_w("prop.coolness.max", "exists")], "prop.coolness.max", count=1,
                              style="object",
                              verdict="Werte das coolste Objekt aus den Ergebnissen raus und sag "
                              "mir, von wem und was."), False),
)  # fmt: skip
BY_ID = {pid: (spec, enabled) for pid, spec, enabled in PRESETS}
# the 19 classic ones (the golden test compares them with the old scoring)
CLASSIC = tuple(pid for pid, _, _ in PRESETS if pid != "coolstes_objekt")


def _old_disabled(app_settings: AppSettingsRepo) -> list[str]:
    """`WallConfig.categories.disabled` as stored before categories moved
    into their own table (the config no longer reads it)."""
    raw = app_settings.get(CONFIG_KEY).get("categories")
    disabled = raw.get("disabled") if isinstance(raw, dict) else None
    if not isinstance(disabled, list):
        return []
    return [str(x) for x in disabled if isinstance(x, str)]


def ensure_seeded(db: Database, app_settings: AppSettingsRepo) -> list[str]:
    """Seed the presets once (first start); returns the ids added."""
    if app_settings.get(SEEDED_KEY):
        return []
    with db.tx():
        if app_settings.get(SEEDED_KEY):
            return []
        disabled = _old_disabled(app_settings)
        existing = {r[0] for r in db.all("SELECT id FROM wall_categories")}
        added: list[str] = []
        for pos, (pid, spec, enabled) in enumerate(PRESETS):
            if pid in existing:
                continue
            engine.insert(db, pid, engine.validate(spec), enabled=enabled and pid not in disabled,
                          preset=pid, by="system", position=pos)  # fmt: skip
            added.append(pid)
        app_settings.put(
            SEEDED_KEY,
            {"at": now_iso(), "from_disabled": [d for d in disabled if d in BY_ID]},
            at=now_iso(),
        )
    return added


def restore(db: Database, *, by: str) -> list[str]:
    """„Vorlagen wiederherstellen“: add the presets that are missing (at the
    end, with their default on/off)."""
    added: list[str] = []
    with db.tx():
        existing = {r[0] for r in db.all("SELECT id FROM wall_categories")}
        for pid, spec, enabled in PRESETS:
            if pid not in existing:
                engine.insert(db, pid, engine.validate(spec), enabled=enabled, preset=pid, by=by)
                added.append(pid)
    return added
