"""„Exportieren / Importieren“ of categories (categories v2, PLAN §2 and §6).

The file:

    {"format": "virtubooth-categories", "version": 2, "exported_at": "…",
     "properties": [{"name": "coolness", "prompt": "…"}],
     "categories": [{"id": "coolstes_objekt", "enabled": false,
                     "preset": "coolstes_objekt", "spec": {…v2…}}]}

A category refers to a property only by name (`field: "prop:<name>"`); the export
puts each property it reads into `properties` with its prompt. Version 1 files
(no `format`, specs in the v1 shape) are read too: every spec goes through
`engine.validate`, which converts v1.

The import, per category (one transaction):

- an invalid entry (no spec, a spec that does not validate, a bad id) is skipped
  with its reason;
- an id that exists: `copy` takes it under a free id (`<id>_2`, `_3` …),
  `replace` overwrites the spec there (position stays);
- a property it reads that does not exist (not even in the Papierkorb) is
  created from the file's prompt; one with another prompt here keeps its own
  prompt (`prompt_conflicts`); a missing one the file has no prompt for: the
  presets' prompt when it is a preset property (created when the category is
  switched on, as everywhere), else the category stays off with
  `property_missing`;
- `enabled` as in the file, unless it is locked right now (a property missing or
  in the Papierkorb, the AI not ready): then it is stored off with that reason.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from ....core.clock import now_iso
from ....db.database import Database
from . import engine, lifecycle, presets
from .measures import InvalidCategory

FORMAT = "virtubooth-categories"
MAX_CATEGORIES = 200
MAX_PROPERTIES = 200
PROPERTY_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
PROMPT_MAX = 2000
CATEGORY_ID = re.compile(engine.CATEGORY_ID_RE_TEXT)

OnConflict = Literal["copy", "replace"]


class InvalidFile(ValueError):
    """The whole file is unusable (German message)."""


# ------------------------------------------------------------------ export


def export(db: Database, ids: Sequence[str] = ()) -> dict[str, Any]:
    """The file for `ids` (empty: every category), in position order."""
    wanted = set(ids)
    cats = [c for c in engine.stored(db) if not wanted or c.id in wanted]
    names: list[str] = []
    for c in cats:
        names += [n for n in lifecycle.references(c.spec) if n not in names]
    prompts = {r["name"]: r["prompt"] for r in db.all("SELECT name, prompt FROM llm_properties")}
    props = []
    for n in names:
        prompt = prompts.get(n) or presets.PRESET_PROPERTIES.get(n)
        if prompt:
            props.append({"name": n, "prompt": prompt})
    return {
        "format": FORMAT,
        "version": 2,
        "exported_at": now_iso(),
        "properties": props,
        "categories": [
            {"id": c.id, "enabled": c.enabled, "preset": c.preset, "spec": c.spec} for c in cats
        ],
    }


# ------------------------------------------------------------------ import


@dataclass
class Imported:
    id: str
    title: str
    enabled: bool
    from_id: str | None = None  # the id in the file, when it was taken as a copy
    replaced: bool = False


@dataclass
class Skipped:
    id: str
    reason: str


@dataclass
class SwitchedOff:
    id: str
    reason: str
    detail: str | None
    message: str


@dataclass
class ImportResult:
    imported: list[Imported] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    properties_created: list[str] = field(default_factory=list)
    prompt_conflicts: list[str] = field(default_factory=list)
    switched_off: list[SwitchedOff] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def slugify(title: str) -> str:
    """A category id from a title (as the editor's slugify): „Prost! Gläser“ → prost_glaeser."""
    base = title.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        base = base.replace(a, b)
    base = unicodedata.normalize("NFKD", base)
    base = "".join(ch for ch in base if not unicodedata.combining(ch))
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")[:36]
    if not base:
        return "kategorie"
    cid = base if base[0].isalpha() else f"k_{base}"
    return cid if len(cid) >= 2 else "kategorie"


def free_id(base: str, taken: set[str]) -> str:
    if base not in taken and base not in engine.RESERVED_IDS:
        return base
    stem = base[:36]
    for i in range(2, 10_000):
        cid = f"{stem}_{i}"
        if cid not in taken:
            return cid
    raise InvalidFile("Keine freie Kennung.")  # pragma: no cover


def _file_properties(raw: Any, result: ImportResult) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, list) or len(raw) > MAX_PROPERTIES:
        raise InvalidFile(f"„properties“ muss eine Liste mit höchstens {MAX_PROPERTIES} sein.")
    out: dict[str, str] = {}
    for i, p in enumerate(raw):
        name = p.get("name") if isinstance(p, dict) else None
        prompt = p.get("prompt") if isinstance(p, dict) else None
        if not isinstance(name, str) or not PROPERTY_NAME.match(name.strip()):
            result.notes.append(f"Eigenschaft {i + 1}: ungültiger Name, übergangen.")
            continue
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= PROMPT_MAX:
            result.notes.append(f"Eigenschaft „{name}“: ungültiger Prompt, übergangen.")
            continue
        if isinstance(p, dict) and "active" in p:
            # the switch „aktiv“ is gone (categories v2): read and ignored
            result.notes.append(f"Eigenschaft „{name}“: „active“ wird nicht mehr gebraucht.")
        out.setdefault(name.strip(), prompt.strip())
    return out


def parse_file(file: Any) -> tuple[list[Any], Any]:
    """(the category entries, the properties list) of a file; InvalidFile when
    it is not one."""
    if not isinstance(file, dict):
        raise InvalidFile("Die Datei ist kein JSON-Objekt.")
    fmt = file.get("format")
    version = file.get("version", 1)
    if fmt is not None and fmt != FORMAT:
        raise InvalidFile(f"Unbekanntes Format: erwartet „{FORMAT}“.")
    if isinstance(version, bool) or version not in (1, 2):
        raise InvalidFile("Unbekannte Version: erwartet 1 oder 2.")
    if version == 2 and fmt != FORMAT:
        raise InvalidFile(f"Unbekanntes Format: erwartet „{FORMAT}“.")
    cats = file.get("categories")
    if not isinstance(cats, list):
        raise InvalidFile("„categories“ fehlt oder ist keine Liste.")
    if len(cats) > MAX_CATEGORIES:
        raise InvalidFile(f"Höchstens {MAX_CATEGORIES} Kategorien pro Datei.")
    return cats, file.get("properties")


def run_import(
    db: Database, file: Any, on_conflict: OnConflict, *, ai_ready: bool, by: str,
    create_property: Callable[[str, str], None],
) -> ImportResult:  # fmt: skip
    """Import `file` (in the caller's transaction). `create_property(name,
    prompt)` makes a property (audited by the caller's service)."""
    result = ImportResult()
    cats, raw_props = parse_file(file)
    file_props = _file_properties(raw_props, result)
    existing = {c.id: c for c in engine.stored(db)}
    taken = {r[0] for r in db.all("SELECT id FROM wall_categories")}
    prompts: dict[str, str] = {
        r["name"]: r["prompt"] for r in db.all("SELECT name, prompt FROM llm_properties")
    }
    conflicts: list[str] = []

    for i, entry in enumerate(cats):
        label = f"Eintrag {i + 1}"
        if not isinstance(entry, dict):
            result.skipped.append(Skipped(label, "kein Objekt"))
            continue
        raw_id = entry.get("id")
        if raw_id is not None and isinstance(raw_id, str) and raw_id:
            label = raw_id
        try:
            spec = engine.validate(entry.get("spec"))
        except InvalidCategory as exc:
            result.skipped.append(Skipped(label, f"ungültig ({exc.field})"))
            continue
        if raw_id is None:
            cid = slugify(spec["title"])
        elif isinstance(raw_id, str) and CATEGORY_ID.match(raw_id) \
                and raw_id not in engine.RESERVED_IDS:  # fmt: skip
            cid = raw_id
        else:
            result.skipped.append(Skipped(label, "ungültige Kennung"))
            continue
        enabled = entry.get("enabled", False)
        if not isinstance(enabled, bool):
            enabled = False

        # the properties it reads
        missing: str | None = None
        for name in lifecycle.references(spec):
            if name in prompts:
                theirs = file_props.get(name)
                if theirs is not None and theirs != prompts[name] and name not in conflicts:
                    conflicts.append(name)
                continue
            prompt = file_props.get(name)
            if prompt is not None:
                create_property(name, prompt)
                prompts[name] = prompt
                result.properties_created.append(name)
            elif name not in presets.PRESET_PROPERTIES and missing is None:
                missing = name

        replace = cid in taken and on_conflict == "replace" and cid in existing
        final = cid if replace else free_id(cid, taken)
        preset = entry.get("preset")
        preset = preset if isinstance(preset, str) and preset == final \
            and preset in presets.BY_ID else None  # fmt: skip
        off: tuple[str, str | None] | None = None
        if missing is not None:
            off = ("property_missing", missing)
        elif enabled:
            lock = lifecycle.lock_of(spec, lifecycle.property_states(db), ai_ready)
            if lock is not None:
                off = (lock.reason, lock.detail)
        on = enabled and off is None
        if on:
            for name in presets.ensure_properties(db, spec, by=by):
                prompts[name] = presets.PRESET_PROPERTIES[name]
                result.properties_created.append(name)
        if replace:
            engine.update(db, final, spec, enabled=on, by=by)
            if off is not None:
                engine.mark_off(db, final, off[0], off[1])
        else:
            engine.insert(db, final, spec, enabled=on, preset=preset, by=by,
                          off_reason=off[0] if off else None,
                          off_detail=off[1] if off else None)  # fmt: skip
            taken.add(final)
        if off is not None:
            result.switched_off.append(SwitchedOff(final, off[0], off[1],
                                                   lifecycle.reason_text(off[0], off[1])))  # fmt: skip
        result.imported.append(Imported(final, spec["title"], on,
                                        from_id=cid if final != cid else None,
                                        replaced=replace))  # fmt: skip
    result.prompt_conflicts = conflicts
    return result


def summary(result: ImportResult) -> Mapping[str, Any]:
    """The audit details."""
    return {
        "imported": [i.id for i in result.imported],
        "skipped": [s.id for s in result.skipped],
        "properties_created": result.properties_created,
    }
