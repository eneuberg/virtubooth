"""The preset categories (spec version 2): the 19 classic Live-Wall categories
(same winners as before, `tests/unit/test_enrich_presets_golden.py`) plus five
that need the object list or an LLM property:

- „Das coolste Objekt“, „Das albernste Objekt“, „Am unerwartetsten“ rank the
  objects by the properties `coolness`, `goofiness`, `unexpectedness`;
- „Die meisten Gesichter“, „Die meisten Objekte“.

The new ones are off by default. Their properties are created on demand
(PRESET_PROPERTIES, `ensure_properties`): when a category that reads one is
switched on and it does not exist yet (not even in the Papierkorb). A property
is only polled while an enabled category reads it. Persons are not filtered
out: each property's prompt lets the AI decide whether a person counts (a guest
in costume may win).

`ensure_seeded()` writes the presets into `wall_categories` once (settings key
`x.wall.categories_seeded`), taking over the old `WallConfig.categories.
disabled` list; `restore()` („Vorlagen wiederherstellen“) adds the presets that
were deleted since; `ensure_upgraded()` converts v1 rows (migration 18).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

from ....core.clock import now_iso
from ....db.database import Database
from ....repositories.app_settings import AppSettingsRepo
from . import engine, presets_v1, spec_v1
from .measures import InvalidCategory

log = logging.getLogger("virtubooth.wall")

SEEDED_KEY = "x.wall.categories_seeded"
CONFIG_KEY = "x.wall.config"  # the wall's settings: its old `categories.disabled`

# action_shot: only photos this blurry qualify (Laplacian variance at 512 px;
# sharp photos are in the hundreds), and not nearly black or white
BLUR_MAX = 80.0
# dauerausloeser: at least this many visible photos
MIN_PHOTOS = 5

_PERSON_RULE = (
    "Bewerte vor allem Dinge; ob eine Person dazuzählt, entscheidest du – ein Mensch im "
    "Kostüm darf gewinnen."
)
PRESET_PROPERTIES: dict[str, str] = {
    "coolness": "Wie cool ist dieser Gegenstand auf einer Party (0 = langweilig, 1 = sehr "
    "cool)? " + _PERSON_RULE,
    "goofiness": "Wie albern oder verrückt wirkt das auf einer Party (0 = ganz normal, "
    "1 = herrlich albern)? " + _PERSON_RULE,
    "unexpectedness": "Wie unerwartet ist dieser Gegenstand auf einer Party? 0 = völlig "
    "normal (Glas, Handy), 1 = total überraschend. " + _PERSON_RULE,
}


def value(key: str) -> dict[str, Any]:
    return {"kind": "value", "key": key}


def objects(agg: str, field: str | None = None, *, labels: Iterable[str] = (),
            exclude: Iterable[str] = (), k: int | None = None, t: float | None = None
            ) -> dict[str, Any]:  # fmt: skip
    return {"kind": "objects",
            "where": {"labels": list(labels), "exclude": list(exclude), "min_confidence": None},
            "field": field, "agg": agg, "k": k, "t": t}  # fmt: skip


def _cond(measure: dict[str, Any], op: str, operand: Any = None) -> dict[str, Any]:
    return {"measure": measure, "op": op, "operand": operand}


def _spec(
    emoji: str, title: str, line: str, by: dict[str, Any], *, order: str = "desc",
    threshold: float | None = None, then: Iterable[dict[str, Any]] = (),
    pool: Iterable[dict[str, Any]] = (), count: int = 3, one_per_guest: bool = True,
    shown: dict[str, Any] | None = None, fmt: str = "count", one: str = "", many: str = "",
    show_object: bool = False, verdict: dict[str, Any] | None = None,
) -> dict[str, Any]:  # fmt: skip
    return {
        "version": 2, "emoji": emoji, "title": title, "line": line, "pool": list(pool),
        "rank": {"by": by, "order": order, "threshold": threshold,
                 "then_by": [{"by": t, "order": "desc"} for t in then]},
        "select": {"count": count, "one_per_guest": one_per_guest},
        "caption": {"value": shown, "format": fmt, "one": one, "many": many,
                    "show_object": show_object},
        "verdict": verdict,
    }  # fmt: skip


def _most(emoji: str, title: str, line: str, fact: str, at_least: float, one: str, many: str,
          **kw: Any) -> dict[str, Any]:  # fmt: skip
    return _spec(emoji, title, line, value(fact), threshold=at_least, one=one, many=many, **kw)


def _object_prop(emoji: str, title: str, line: str, prop: str, unit: str, **kw: Any
                 ) -> dict[str, Any]:  # fmt: skip
    return _spec(emoji, title, line, objects("max", f"prop:{prop}"), fmt="decimal", one=unit,
                 show_object=True, **kw)  # fmt: skip


# (id, spec, enabled by default), in the wall's order
PRESETS: tuple[tuple[str, dict[str, Any], bool], ...] = (
    ("volles_haus", _most("👥", "Volles Haus", "Die meisten Leute auf einem Foto", "people", 3,
                          "Person", "Personen"), True),
    ("haende_hoch", _most("🙌", "Hände hoch!", "Die meisten Hände in der Luft", "hands", 3,
                          "Hand", "Hände"), True),
    ("grinsekatzen", _most("😁", "Grinsekatzen", "Die meisten Lächeln auf einem Bild",
                           "smiles", 2, "Lächeln", "Lächeln"), True),
    ("herzschmerz", _most("🥺", "Herzschmerz-Pose", "Der dramatischste Schmollblick des Abends",
                          "sad_max", 0.5, "Drama", "Drama", fmt="percent"), True),
    ("ach_du_schreck", _most("😱", "Ach du Schreck!", "Das überraschteste Gesicht",
                             "surprise_max", 0.5, "Schreck", "Schreck", fmt="percent"), True),
    ("brillenbande", _most("🤓", "Brillenbande", "Die meisten Brillen auf einem Foto",
                           "glasses", 1, "Brille", "Brillen"), True),
    # ranked by the age spread (FairFace, when on) first, then by the age groups
    ("generationen", _spec("🎂", "Generationen-Foto", "Die größte Altersspanne auf einem Bild",
                           value("age_spread"), pool=[_cond(value("age_groups"), "gte", 2.0)],
                           then=[value("age_groups")], shown=value("age_groups"),
                           one="Generation", many="Generationen"), True),
    ("dream_team", _spec("👯", "Dream-Team", "Zwei Leute, doppelt gute Laune", value("happy_max"),
                         pool=[_cond(value("people"), "eq", 2.0),
                               _cond(value("smiles"), "eq", 2.0)],
                         then=[value("smiles")], shown=value("smiles"), fmt="text",
                         one="2 Leute, 2 Lächeln"), True),
    ("solo_star", _spec("🌟", "Solo-Star", "Ganz nah dran", value("face_area_max"),
                        pool=[_cond(value("faces"), "eq", 1.0)], threshold=0.12,
                        fmt="percent", one="Gesicht", many="Gesicht"), True),
    ("peace", _most("✌️", "Peace!", "Die meisten Victory-Zeichen", "peace", 1, "Peace-Zeichen",
                    "Peace-Zeichen"), True),
    ("rock", _most("🤘", "Rock'n'Roll", "Die meisten Pommesgabeln", "rock", 1, "Pommesgabel",
                   "Pommesgabeln"), True),
    ("daumen_hoch", _most("👍", "Daumen hoch", "Die meisten Daumen nach oben", "thumbs_up", 1,
                          "Daumen", "Daumen"), True),
    ("prost", _most("🥂", "Prost!", "Die meisten Gläser im Bild", "drinks", 2, "Glas", "Gläser"),
     True),
    ("hutparade", _most("🎩", "Hutparade", "Die meisten Hüte und Kappen", "hats", 1, "Hut",
                        "Hüte"), True),
    ("gesangseinlage", _most("🎤", "Gesangseinlage", "Die meisten offenen Münder", "mouth_open",
                             2, "offener Mund", "offene Münder"), True),
    ("farbexplosion", _most("🌈", "Farbexplosion", "Das bunteste Foto", "colorfulness", 40,
                            "Farbwert", "Farbwert", fmt="number"), True),
    ("action_shot", _spec("💨", "Action-Shot", "So viel Bewegung, die Kamera kam kaum mit",
                          value("sharpness"), order="asc", threshold=BLUR_MAX,
                          pool=[_cond(value("brightness"), "gte", 0.1),
                                _cond(value("brightness"), "lte", 0.92)],
                          fmt="text", one="volle Bewegung"), True),
    ("eroeffnung", _spec("🎬", "Eröffnungsfoto", "Das allererste Foto des Abends",
                         value("photo.created_at"), order="asc", count=1, one_per_guest=False,
                         fmt="time"), True),
    ("dauerausloeser", _most("📸", "Dauerauslöser",
                             "Die meisten Fotos von einer Person (hier das neueste)",
                             "photo.guest_photos", MIN_PHOTOS, "Foto", "Fotos"), True),
    ("coolstes_objekt", _object_prop("🏆", "Das coolste Objekt", "Was die KI am coolsten findet",
                                     "coolness", "Coolness", count=1,
                                     verdict={"prompt": None, "count": 1, "model": None,
                                              "effort": "low"}), False),
    ("albernstes_objekt", _object_prop("🤪", "Das albernste Objekt",
                                       "Was die KI am albernsten findet", "goofiness",
                                       "Albernheit"), False),
    ("am_unerwartetsten", _object_prop("🫨", "Am unerwartetsten",
                                       "Was hier keiner erwartet hätte", "unexpectedness",
                                       "Überraschung",
                                       then=[objects("top_k_mean", "prop:unexpectedness",
                                                     k=2)]), False),
    ("meiste_gesichter", _most("🧑‍🤝‍🧑", "Die meisten Gesichter", "Wer bringt die meisten mit?",
                               "faces", 2, "Gesicht", "Gesichter", then=[value("smiles")]),
     False),
    ("meiste_objekte", _spec("🧺", "Die meisten Objekte", "So viel los auf einem Bild",
                             objects("count"), threshold=3, then=[objects("mean", "confidence")],
                             one="Ding", many="Dinge"), False),
)  # fmt: skip
BY_ID = {pid: (spec, enabled) for pid, spec, enabled in PRESETS}
# the 19 classic ones (the golden test compares them with the old scoring)
CLASSIC = tuple(pid for pid, _, _ in PRESETS[:19])


def ensure_properties(db: Database, spec: dict[str, Any], *, by: str) -> list[str]:
    """Create the properties of PRESET_PROPERTIES the (validated) spec reads that
    do not exist yet (not even in the Papierkorb); returns the names created.
    Called when such a category is switched on."""
    created: list[str] = []
    with db.tx() as c:
        for name in engine.references(spec):
            prompt = PRESET_PROPERTIES.get(name)
            if prompt is None:
                continue
            if c.execute("SELECT 1 FROM llm_properties WHERE name=?", (name,)).fetchone():
                continue
            c.execute(
                "INSERT INTO llm_properties (name, prompt, created_at, created_by) "
                "VALUES (?,?,?,?)",
                (name, prompt, now_iso(), by),
            )
            created.append(name)
    return created


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


def _v1_preset(pid: str | None) -> dict[str, Any] | None:
    if pid is None or pid not in presets_v1.BY_ID:
        return None
    return spec_v1.validate(presets_v1.BY_ID[pid])


def ensure_upgraded(db: Database) -> list[str]:
    """Convert the rows still on spec version 1 (idempotent; migration 18 kept
    each old spec in `spec_v1`). A preset whose spec is exactly its v1 preset
    gets the v2 preset; any other row goes through `spec_v1.upgrade`. A row that
    does not validate stays on v1 (and stays out of `engine.stored`). Returns
    the ids converted."""
    done: list[str] = []
    rows = db.all("SELECT id, preset, spec FROM wall_categories WHERE spec_version = 1")
    if not rows:
        return done
    with db.tx() as c:
        for r in rows:
            try:
                raw = json.loads(r["spec"])
                if isinstance(raw, dict) and raw.get("version") == 2:
                    new = engine.validate(raw)  # written as v2 already
                    old = None
                else:
                    old = spec_v1.validate(raw)
            except (ValueError, InvalidCategory):
                log.warning("wall category %s: invalid spec, left as it is", r["id"])
                continue
            preset = r["preset"] if r["preset"] in BY_ID else None
            if old is None:
                pass
            elif preset is not None and old == _v1_preset(preset):
                new = engine.validate(BY_ID[preset][0])
            else:
                try:
                    new = engine.validate(spec_v1.upgrade(old))
                except InvalidCategory:
                    log.warning("wall category %s: v1 spec does not convert", r["id"])
                    continue
            c.execute(
                "UPDATE wall_categories SET spec=?, spec_version=2 WHERE id=? AND spec_version=1",
                (json.dumps(new, ensure_ascii=False), r["id"]),
            )
            done.append(r["id"])
    return done
