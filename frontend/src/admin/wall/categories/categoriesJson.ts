/**
 * „Exportieren“ / „Importieren“ of categories (categoriesJson.test.ts). The file is the
 * server's (GET /categories/export, PLAN §2): `{format: "virtubooth-categories",
 * version: 2, properties: [{name, prompt}], categories: [{id, enabled, preset, spec}]}`;
 * properties are referenced only by name. Older files (`version: 1`, specs in the v1
 * shape) are taken too: the server converts them.
 *
 * Here: read a file before it goes up (JSON, size, the envelope), which of its ids exist
 * already (the dialog asks: as a copy `_2`, or replace), and the result in one line.
 */
import type { CategoryImportResult } from '../types';
import { slugify } from './spec';

export const CATEGORIES_FILE = 'kategorien.json';
export const FORMAT = 'virtubooth-categories';
export const IMPORT_MAX_BYTES = 1_000_000;
export const IMPORT_MAX_ENTRIES = 200;

export interface ParsedFile {
  ok: true;
  /** the parsed JSON, sent as it is */
  file: Record<string, unknown>;
  version: 1 | 2;
  /** the categories' ids (a missing id: the server's slug of the title) */
  ids: string[];
  titles: string[];
  properties: string[];
}

export type ParsedCategories = ParsedFile | { ok: false; error: string };

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

/** Reads a file's text: fails on bad JSON, size, format or version; single bad entries are the server's to skip. */
export function parseCategoriesFile(text: string, bytes: number = new Blob([text]).size): ParsedCategories {
  if (bytes > IMPORT_MAX_BYTES) return { ok: false, error: 'Die Datei ist größer als 1 MB.' };
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { ok: false, error: 'Die Datei ist kein gültiges JSON.' };
  }
  if (!isRecord(data)) return { ok: false, error: 'Die Datei ist kein JSON-Objekt.' };
  const version = data.version ?? 1;
  if (version !== 1 && version !== 2) return { ok: false, error: 'Unbekannte Version: erwartet 1 oder 2.' };
  if ((version === 2 || data.format !== undefined) && data.format !== FORMAT) {
    return { ok: false, error: `Unbekanntes Format: erwartet „${FORMAT}“ (eine Datei von „Exportieren“).` };
  }
  if (!Array.isArray(data.categories)) return { ok: false, error: 'Die Datei enthält keine Kategorien.' };
  const list: unknown[] = data.categories;
  if (list.length > IMPORT_MAX_ENTRIES) return { ok: false, error: `Höchstens ${IMPORT_MAX_ENTRIES} Kategorien pro Datei.` };
  const ids: string[] = [];
  const titles: string[] = [];
  for (const entry of list) {
    if (!isRecord(entry)) continue;
    const spec = isRecord(entry.spec) ? entry.spec : {};
    const title = typeof spec.title === 'string' ? spec.title : '';
    const id = typeof entry.id === 'string' && entry.id ? entry.id : slugify(title);
    ids.push(id);
    titles.push(title || id);
  }
  const props = Array.isArray(data.properties) ? data.properties : [];
  const properties = props.flatMap((p) => (isRecord(p) && typeof p.name === 'string' ? [p.name] : []));
  return { ok: true, file: data, version, ids, titles, properties };
}

/** The file's ids that exist already (they come in as a copy `_2`, or replace them). */
export function conflicts(ids: readonly string[], existing: Iterable<string>): string[] {
  const have = new Set(existing);
  return [...new Set(ids.filter((id) => have.has(id)))];
}

/** A file name for an export of `ids` (one category: its id). */
export function exportName(ids: readonly string[]): string {
  return ids.length === 1 ? `kategorie-${ids[0]}.json` : CATEGORIES_FILE;
}

/**
 * „2 importiert (1 als Kopie, 1 ersetzt), 1 übersprungen. Eigenschaft angelegt: coolness.
 * Prompt weicht ab, eure bleibt: glitzer. 1 aus (Externe KI ist aus …).“
 */
export function importSummary(r: CategoryImportResult): string {
  const copies = r.imported.filter((i) => i.from_id !== null).length;
  const replaced = r.imported.filter((i) => i.replaced).length;
  const extra = [copies ? `${copies} als Kopie` : '', replaced ? `${replaced} ersetzt` : ''].filter(Boolean);
  const parts = [`${r.imported.length} importiert${extra.length ? ` (${extra.join(', ')})` : ''}`];
  if (r.skipped.length) parts.push(`${r.skipped.length} übersprungen`);
  let text = `${parts.join(', ')}.`;
  if (r.properties_created.length) {
    text += ` ${r.properties_created.length === 1 ? 'Eigenschaft' : 'Eigenschaften'} angelegt: ${r.properties_created.join(', ')}.`;
  }
  if (r.prompt_conflicts.length) {
    text += ` Prompt weicht ab, eure bleibt: ${r.prompt_conflicts.join(', ')}.`;
  }
  if (r.switched_off.length) text += ` ${r.switched_off.length} ausgeschaltet.`;
  return text;
}

/** The lines under the summary: what was skipped or switched off, and why. */
export function importProblems(r: CategoryImportResult): string[] {
  return [
    ...r.skipped.map((s) => `${s.id}: übersprungen, ${s.reason}`),
    ...r.switched_off.map((s) => `${s.id}: aus, ${s.message}`),
    ...r.notes,
  ];
}
