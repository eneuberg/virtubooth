"""The Live Wall's fun categories (PLAN §5): definitions, labels, winners.

Each category ranks photos by one fact (`wall_facts`), optionally with more
conditions, or is special (the first photo, the most photos of one guest).
Winners are visible photos only (not hidden, not deleted, within the sources,
taken no later than `not_after`), at most one per guest and category (their
best); ties go to the newer photo. Labels are German
and gender-neutral; nothing ranks a single person in a mean way.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from ....db.database import Database
from . import clock
from .analyzers import BY_NAME
from .engine import PhotoFilter

LabelStyle = Literal["count", "percent", "number", "time", "fixed"]

# action_shot: only photos this blurry qualify (Laplacian variance at 512 px;
# sharp photos are in the hundreds), and not nearly black or white
BLUR_MAX = 80.0
ACTION_BRIGHTNESS = (0.1, 0.92)


@dataclass(frozen=True)
class CategoryDef:
    id: str
    emoji: str
    title: str
    line: str
    needs: tuple[str, ...]  # analyzer names
    # scoring: `rank` is the fact whose value is returned; `where` must all
    # hold; `order` ranks (desc) before `rank`, missing values last
    rank: str | None = None
    descending: bool = True
    where: tuple[tuple[str, str, float], ...] = ()
    order: tuple[str, ...] = ()
    special: Literal["first", "most_photos"] | None = None
    max_winners: int = 3
    # label: count → „1 Person“ / „7 Personen“; percent → „82 % Drama“;
    # number → „Farbwert 73“; time → „um 19:42“; fixed → `words[0]`
    style: LabelStyle = "count"
    words: tuple[str, str] = ("", "")

    def label(self, value: float) -> str:
        one, many = self.words
        if self.style == "count":
            n = round(value)
            return f"{n} {one if n == 1 else many}"
        if self.style == "percent":
            return f"{round(value * 100)} % {one}"
        if self.style == "number":
            return f"{one} {value:.0f}"
        if self.style == "time":
            return f"um {clock.local(value):%H:%M}"
        return one

    def available(self, enabled_analyzers: Collection[str]) -> str | None:
        """None when every analyzer it needs is on, else a German reason."""
        for name in self.needs:
            if name not in enabled_analyzers:
                title = BY_NAME[name].title if name in BY_NAME else name
                return f"Braucht die Analyse „{title}“."
        return None


@dataclass(frozen=True)
class CategoryWinners:
    category: CategoryDef
    winners: list[tuple[int, float]]  # (photo id, value), best first


def _at_least(fact: str, n: float) -> tuple[tuple[str, str, float], ...]:
    return ((fact, ">=", n),)


CATALOGUE: tuple[CategoryDef, ...] = (
    CategoryDef("volles_haus", "👥", "Volles Haus", "Die meisten Leute auf einem Foto",
                ("faces",), rank="people", where=_at_least("people", 3),
                words=("Person", "Personen")),
    CategoryDef("haende_hoch", "🙌", "Hände hoch!", "Die meisten Hände in der Luft",
                ("gestures",), rank="hands", where=_at_least("hands", 3), words=("Hand", "Hände")),
    CategoryDef("grinsekatzen", "😁", "Grinsekatzen", "Die meisten Lächeln auf einem Bild",
                ("faces",), rank="smiles", where=_at_least("smiles", 2),
                words=("Lächeln", "Lächeln")),
    CategoryDef("herzschmerz", "🥺", "Herzschmerz-Pose", "Der dramatischste Schmollblick des Abends",
                ("emotion",), rank="sad_max", where=_at_least("sad_max", 0.5), style="percent",
                words=("Drama", "Drama")),
    CategoryDef("ach_du_schreck", "😱", "Ach du Schreck!", "Das überraschteste Gesicht",
                ("emotion",), rank="surprise_max", where=_at_least("surprise_max", 0.5),
                style="percent", words=("Schreck", "Schreck")),
    CategoryDef("brillenbande", "🤓", "Brillenbande", "Die meisten Brillen auf einem Foto",
                ("tags",), rank="glasses", where=_at_least("glasses", 1),
                words=("Brille", "Brillen")),
    CategoryDef("generationen", "🎂", "Generationen-Foto", "Die größte Altersspanne auf einem Bild",
                ("tags",), rank="age_groups", where=_at_least("age_groups", 2),
                order=("age_spread",), words=("Generation", "Generationen")),
    CategoryDef("dream_team", "👯", "Dream-Team", "Zwei Leute, doppelt gute Laune",
                ("faces",), rank="smiles", where=(("people", "=", 2), ("smiles", "=", 2)),
                order=("happy_max",), style="fixed", words=("2 Leute, 2 Lächeln", "")),
    CategoryDef("solo_star", "🌟", "Solo-Star", "Ganz nah dran",
                ("faces",), rank="face_area_max",
                where=(("faces", "=", 1), ("face_area_max", ">=", 0.12)), style="percent",
                words=("Gesicht", "Gesicht")),
    CategoryDef("peace", "✌️", "Peace!", "Die meisten Victory-Zeichen",
                ("gestures",), rank="peace", where=_at_least("peace", 1),
                words=("Peace-Zeichen", "Peace-Zeichen")),
    CategoryDef("rock", "🤘", "Rock'n'Roll", "Die meisten Pommesgabeln",
                ("gestures",), rank="rock", where=_at_least("rock", 1),
                words=("Pommesgabel", "Pommesgabeln")),
    CategoryDef("daumen_hoch", "👍", "Daumen hoch", "Die meisten Daumen nach oben",
                ("gestures",), rank="thumbs_up", where=_at_least("thumbs_up", 1),
                words=("Daumen", "Daumen")),
    CategoryDef("prost", "🥂", "Prost!", "Die meisten Gläser im Bild",
                ("objects",), rank="drinks", where=_at_least("drinks", 2), words=("Glas", "Gläser")),
    CategoryDef("hutparade", "🎩", "Hutparade", "Die meisten Hüte und Kappen",
                ("tags",), rank="hats", where=_at_least("hats", 1), words=("Hut", "Hüte")),
    CategoryDef("gesangseinlage", "🎤", "Gesangseinlage", "Die meisten offenen Münder",
                ("faces",), rank="mouth_open", where=_at_least("mouth_open", 2),
                words=("offener Mund", "offene Münder")),
    CategoryDef("farbexplosion", "🌈", "Farbexplosion", "Das bunteste Foto",
                ("basic",), rank="colorfulness", where=_at_least("colorfulness", 40),
                style="number", words=("Farbwert", "Farbwert")),
    CategoryDef("action_shot", "💨", "Action-Shot", "So viel Bewegung, die Kamera kam kaum mit",
                ("basic",), rank="sharpness", descending=False,
                where=(("sharpness", "<=", BLUR_MAX), ("brightness", ">=", ACTION_BRIGHTNESS[0]),
                       ("brightness", "<=", ACTION_BRIGHTNESS[1])),
                style="fixed", words=("volle Bewegung", "")),
    CategoryDef("eroeffnung", "🎬", "Eröffnungsfoto", "Das allererste Foto des Abends",
                (), special="first", max_winners=1, style="time"),
    CategoryDef("dauerausloeser", "📸", "Dauerauslöser",
                "Die meisten Fotos von einer Person (hier das neueste)",
                (), special="most_photos", words=("Foto", "Fotos")),
)  # fmt: skip
BY_ID = {c.id: c for c in CATALOGUE}
# dauerausloeser: at least this many visible photos
MIN_PHOTOS = 5

_OPS = {">=", "<=", "=", ">", "<"}


def _visible(flt: PhotoFilter) -> tuple[str, list[Any]]:
    sql = "p.hidden_at IS NULL AND p.deleted_at IS NULL AND p.created_at <= ?"
    params: list[Any] = [flt.not_after]
    if flt.sources:
        sql += f" AND p.extension IN ({', '.join('?' for _ in flt.sources)})"
        params += list(flt.sources)
    return sql, params


def _by_facts(
    db: Database, cat: CategoryDef, flt: PhotoFilter, limit: int
) -> list[tuple[int, float]]:
    assert cat.rank is not None
    keys = list(dict.fromkeys([cat.rank, *(w[0] for w in cat.where), *cat.order]))
    required = {cat.rank, *(w[0] for w in cat.where)}
    alias = {k: f"f{i}" for i, k in enumerate(keys)}
    joins: list[str] = []
    params: list[Any] = []
    for key in keys:
        kind = "JOIN" if key in required else "LEFT JOIN"
        joins.append(f"{kind} wall_facts {alias[key]} ON {alias[key]}.photo_id = p.id "
                     f"AND {alias[key]}.key = ?")  # fmt: skip
        params.append(key)
    visible, vparams = _visible(flt)
    conds = [visible]
    params += vparams
    if any(BY_NAME[n].kind == "ml" for n in cat.needs if n in BY_NAME):
        # „Meine Fotos nicht automatisch auswerten“: never by faces, hands, ...
        conds.append("p.user_id NOT IN (SELECT id FROM users WHERE analysis_opt_out = 1)")
    for key, op, value in cat.where:
        assert op in _OPS
        conds.append(f"{alias[key]}.value {op} ?")
        params.append(value)
    order = [f"COALESCE({alias[k]}.value, -1) DESC" for k in cat.order if k != cat.rank]
    order.append(f"{alias[cat.rank]}.value {'DESC' if cat.descending else 'ASC'}")
    order += ["p.created_at DESC", "p.id DESC"]
    ranking = ", ".join(order)
    # one photo per guest: each guest's best (`mine` = 1), then the best of those
    sql = (
        "SELECT id, value FROM ("
        f"SELECT p.id, {alias[cat.rank]}.value AS value, "
        f"ROW_NUMBER() OVER (PARTITION BY p.user_id ORDER BY {ranking}) AS mine, "
        f"ROW_NUMBER() OVER (ORDER BY {ranking}) AS pos "
        f"FROM photos p {' '.join(joins)} WHERE {' AND '.join(conds)}"
        ") WHERE mine = 1 ORDER BY pos LIMIT ?"
    )
    return [(int(r[0]), float(r[1])) for r in db.all(sql, [*params, limit])]


def _first(db: Database, flt: PhotoFilter, limit: int) -> list[tuple[int, float]]:
    visible, params = _visible(flt)
    rows = db.all(
        f"SELECT p.id, p.created_at FROM photos p WHERE {visible} "
        "ORDER BY p.created_at ASC, p.id ASC LIMIT ?",
        [*params, limit],
    )
    return [(int(r[0]), clock.unix(r[1])) for r in rows]


def _most_photos(db: Database, flt: PhotoFilter, limit: int) -> list[tuple[int, float]]:
    visible, params = _visible(flt)
    rows = db.all(
        f"WITH v AS (SELECT p.id, p.user_id, p.created_at FROM photos p WHERE {visible}) "
        "SELECT (SELECT v2.id FROM v v2 WHERE v2.user_id = v.user_id "
        "        ORDER BY v2.created_at DESC, v2.id DESC LIMIT 1) AS id, "
        "       COUNT(*) AS n, MAX(v.created_at) AS last "
        "FROM v GROUP BY v.user_id HAVING COUNT(*) >= ? ORDER BY n DESC, last DESC LIMIT ?",
        [*params, MIN_PHOTOS, limit],
    )
    return [(int(r["id"]), float(r["n"])) for r in rows]


def winners_of(
    db: Database, cat: CategoryDef, flt: PhotoFilter, limit: int = 3
) -> list[tuple[int, float]]:
    limit = max(0, min(limit, cat.max_winners))
    if limit == 0:
        return []
    if cat.special == "first":
        return _first(db, flt, limit)
    if cat.special == "most_photos":
        return _most_photos(db, flt, limit)
    return _by_facts(db, cat, flt, limit)


def winners(
    db: Database, ids: Sequence[str], flt: PhotoFilter, per_category: int = 3
) -> list[CategoryWinners]:
    """The categories named in `ids` (unknown ids ignored), catalogue order,
    each with its best visible photos (possibly none)."""
    wanted = set(ids)
    return [
        CategoryWinners(cat, winners_of(db, cat, flt, per_category))
        for cat in CATALOGUE
        if cat.id in wanted
    ]
