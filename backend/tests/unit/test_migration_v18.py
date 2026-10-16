"""Migration 18 (categories v2): the old spec is kept in `spec_v1`, enabled
categories that read a switched-off or trashed property are switched off with a
reason, the switch „aktiv“ (`inactive_at`) goes, the comment cache appears, and
no object, score or fact table changes (row counts and contents hashed). Then
`presets.ensure_upgraded` converts the rows to spec version 2 (idempotent)."""

from __future__ import annotations

import hashlib
import json

from virtubooth.db import migrations as dbmod
from virtubooth.db.database import Database
from virtubooth.extensions.wall.enrich import engine, presets, presets_v1

FROZEN = (
    "photo_objects", "photo_source_objects", "photo_detection_runs", "wall_facts",
    "property_scores", "wall_category_verdicts", "llm_polls",
)  # fmt: skip
T = "2026-10-15T20:00:00.000+00:00"


def digest(db: Database, table: str) -> tuple[int, str]:
    rows = db.all(f"SELECT * FROM {table} ORDER BY rowid")
    raw = json.dumps([list(r) for r in rows], default=str)
    return len(rows), hashlib.sha256(raw.encode()).hexdigest()


def v1_prop_spec(name: str, title: str) -> dict:
    return {"emoji": "🏆", "title": title, "line": "", "where": [],
            "select": {"by": f"prop.{name}.max", "order": "top", "count": 1, "then_by": [],
                       "one_per_guest": True},
            "label": {"value": None, "style": "object", "one": "", "many": ""},
            "verdict": {"prompt": "Wer?"}}  # fmt: skip


def make_v17(path, monkeypatch) -> None:
    v17 = tuple(step for step in dbmod.MIGRATIONS if step[0] <= 17)
    monkeypatch.setattr(dbmod, "MIGRATIONS", v17)
    monkeypatch.setattr(dbmod, "SCHEMA_VERSION", 17)
    db = Database(path)
    try:
        with db.tx() as c:
            c.execute(
                "INSERT INTO users (id, public_id, name, created_at, last_seen_at, consent_at, "
                "consent_version) VALUES (1, 'u1', 'Otter', ?, ?, ?, '1')",
                (T, T, T),
            )
            c.execute(
                "INSERT INTO photos (id, public_id, extension, user_id, seq, filename, "
                "thumb_filename, width, height, bytes, meta, created_at) VALUES (1, 'p1', 'booth', "
                "1, 1, 'a.jpg', 't.jpg', 10, 10, 1, '{}', ?)",
                (T,),
            )
            c.execute("INSERT INTO wall_facts (photo_id, key, value) VALUES (1, 'people', 3)")
            c.execute(
                "INSERT INTO photo_objects (photo_id, idx, label, label_de, score, x, y, w, h, "
                "source, model, created_at) VALUES (1, 0, 'hat', 'Hut', 0.9, 0.1, 0.2, 0.3, 0.4, "
                "'local', 'm@1', ?)",
                (T,),
            )
            c.execute(
                "INSERT INTO photo_source_objects (photo_id, source, pos, label, label_de, score, "
                "model, merged_idx, created_at) VALUES (1, 'local', 0, 'hat', 'Hut', 0.9, 'm@1', "
                "0, ?)",
                (T,),
            )
            c.execute(
                "INSERT INTO photo_detection_runs (photo_id, source, state, model, error, "
                "objects, created_at) VALUES (1, 'local', 'done', 'm@1', NULL, 1, ?)",
                (T,),
            )
            c.execute(
                "INSERT INTO llm_properties (id, name, prompt, created_at, inactive_at, "
                "deleted_at) VALUES (1, 'coolness', 'p', ?, NULL, NULL), "
                "(2, 'old', 'q', ?, ?, NULL), (3, 'gone', 'r', ?, NULL, ?), "
                "(4, 'old_gone', 's', ?, ?, ?)",
                (T, T, T, T, T, T, T, T),
            )
            c.execute("INSERT INTO llm_polls (id, started_at, state) VALUES (1, ?, 'done')", (T,))
            c.execute("INSERT INTO property_scores VALUES (1, 1, '[0.8]', 1, ?)", (T,))
            c.execute(
                "INSERT INTO wall_category_verdicts VALUES ('cool', 'Hut!', '🎩', 1, 0, 1, ?)",
                (T,),
            )
            rows = [
                ("volles_haus", 0, 1, "volles_haus", presets_v1.BY_ID["volles_haus"]),
                ("prost", 1, 1, "prost", {**presets_v1.BY_ID["prost"], "title": "Prösterchen"}),
                ("cool", 2, 1, None, v1_prop_spec("coolness", "Cool")),
                ("old_on", 3, 1, None, v1_prop_spec("old", "Alt an")),
                ("old_off", 4, 0, None, v1_prop_spec("old", "Alt aus")),
                ("gone_on", 5, 1, None, v1_prop_spec("gone", "Weg an")),
                ("both_on", 6, 1, None, v1_prop_spec("old_gone", "Beides")),
                # `prop.old` must not match `prop.older`: the dot after the name
                ("older", 7, 1, None, v1_prop_spec("older", "Älter")),
                ("broken", 8, 1, None, {"title": "kaputt"}),
            ]
            for cid, pos, enabled, preset, spec in rows:
                c.execute(
                    "INSERT INTO wall_categories (id, position, enabled, preset, spec, updated_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (cid, pos, enabled, preset, json.dumps(spec, ensure_ascii=False), T),
                )
    finally:
        db.close()
    monkeypatch.undo()


def test_migration_18_follows_17():
    versions = [v for v, _ in dbmod.MIGRATIONS]
    assert versions.index(18) == versions.index(17) + 1 and versions[-1] == 18


def test_v17_to_v18(tmp_path, monkeypatch):
    path = tmp_path / "virtubooth.db"
    make_v17(path, monkeypatch)
    old = Database.__new__(Database)  # read the v17 state without migrating
    import sqlite3

    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    old.all = lambda sql, params=(): raw.execute(sql, params).fetchall()  # type: ignore[method-assign]
    before = {t: digest(old, t) for t in FROZEN}
    specs = {r[0]: r[1] for r in raw.execute("SELECT id, spec FROM wall_categories")}
    raw.close()

    db = Database(path)
    try:
        assert db.one("PRAGMA user_version")[0] == 18
        assert {t: digest(db, t) for t in FROZEN} == before
        cols = {r[1] for r in db.all("PRAGMA table_info(llm_properties)")}
        assert "inactive_at" not in cols and "deleted_at" in cols
        rows = {r["id"]: r for r in db.all("SELECT * FROM wall_categories")}
        assert {cid: r["spec_v1"] for cid, r in rows.items()} == specs
        assert all(r["spec_version"] == 1 for r in rows.values())
        state = {cid: (r["enabled"], r["off_reason"], r["off_detail"]) for cid, r in rows.items()}
        assert state == {
            "volles_haus": (1, None, None), "prost": (1, None, None), "cool": (1, None, None),
            "old_on": (0, "migrated_inactive", "old"), "old_off": (0, None, None),
            "gone_on": (0, "property_trashed", "gone"),
            "both_on": (0, "property_trashed", "old_gone"),
            "older": (1, None, None), "broken": (1, None, None),
        }  # fmt: skip
        assert rows["old_on"]["off_at"].endswith("+00:00")
        assert db.one("SELECT COUNT(*) FROM wall_category_comments")[0] == 0

        # then the conversion (at start): idempotent, the rest unchanged
        done = presets.ensure_upgraded(db)
        assert sorted(done) == sorted(set(rows) - {"broken"})
        assert presets.ensure_upgraded(db) == []
        rows = {r["id"]: r for r in db.all("SELECT * FROM wall_categories")}
        assert rows["broken"]["spec_version"] == 1  # invalid already: left as it was
        # an untouched preset gets the v2 preset, a changed one is converted
        assert json.loads(rows["volles_haus"]["spec"]) == engine.validate(
            presets.BY_ID["volles_haus"][0]
        )
        prost = json.loads(rows["prost"]["spec"])
        assert prost["version"] == 2 and prost["title"] == "Prösterchen"
        assert prost["rank"]["threshold"] == 2
        cool = json.loads(rows["cool"]["spec"])
        assert cool["rank"]["by"]["field"] == "prop:coolness" and cool["caption"]["show_object"]
        assert cool["verdict"] == {"prompt": "Wer?", "count": 1, "model": None, "effort": "low"}
        assert {t: digest(db, t) for t in FROZEN} == before
        assert [c.id for c in engine.stored(db)] == [
            "volles_haus", "prost", "cool", "old_on", "old_off", "gone_on", "both_on", "older",
        ]  # fmt: skip
    finally:
        db.close()
