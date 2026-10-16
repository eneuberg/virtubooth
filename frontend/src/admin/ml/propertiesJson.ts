/**
 * „Exportieren“ / „Importieren“ of the Eigenschaften as JSON (propertiesJson.test.ts).
 * Names are immutable (N7): an import only adds names that do not exist yet and never
 * overwrites one; it goes through the same POST /llm/properties (+ archive) as the sheet.
 */
import { isApiError } from '@/api/client';
import { validateProperty } from './forms';
import type { LlmProperty } from './types';

export const PROPERTIES_FILE = 'eigenschaften.json';
export const IMPORT_MAX_ENTRIES = 200;
export const IMPORT_MAX_BYTES = 1_000_000;

export interface PropertyEntry {
  name: string;
  prompt: string;
  archived: boolean;
}

export interface PropertiesFile {
  version: 1;
  properties: PropertyEntry[];
}

export interface InvalidEntry {
  /** the entry's name, or „Eintrag 3“ when it has none */
  label: string;
  reason: string;
}

export type ParsedImport =
  { ok: true; entries: PropertyEntry[]; invalid: InvalidEntry[] } | { ok: false; error: string };

export interface ImportResult {
  imported: string[];
  skipped: string[];
  invalid: InvalidEntry[];
  failed: InvalidEntry[];
}

/** All properties, archived ones included, active first as in the list. */
export function exportPayload(props: readonly LlmProperty[]): PropertiesFile {
  return {
    version: 1,
    properties: props.map((p) => ({ name: p.name, prompt: p.prompt, archived: p.archived_at !== null })),
  };
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === 'object' && v !== null && !Array.isArray(v);

/** Reads a file's text: the whole file fails on bad JSON, version or size; single bad entries are listed. */
export function parseImport(text: string, bytes: number = new Blob([text]).size): ParsedImport {
  if (bytes > IMPORT_MAX_BYTES) return { ok: false, error: 'Die Datei ist größer als 1 MB.' };
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { ok: false, error: 'Die Datei ist kein gültiges JSON.' };
  }
  if (!isRecord(data) || data.version !== 1 || !Array.isArray(data.properties)) {
    return { ok: false, error: 'Unbekanntes Format: erwartet { "version": 1, "properties": [ … ] }.' };
  }
  const list: unknown[] = data.properties;
  if (list.length > IMPORT_MAX_ENTRIES) {
    return { ok: false, error: `Höchstens ${IMPORT_MAX_ENTRIES} Eigenschaften pro Datei.` };
  }
  const entries: PropertyEntry[] = [];
  const invalid: InvalidEntry[] = [];
  list.forEach((item, i) => {
    const fallback = `Eintrag ${i + 1}`;
    if (!isRecord(item)) {
      invalid.push({ label: fallback, reason: 'kein Objekt' });
      return;
    }
    const { name, prompt, archived } = item;
    const label = typeof name === 'string' && name ? name : fallback;
    if (typeof name !== 'string' || typeof prompt !== 'string') {
      invalid.push({ label, reason: 'name und prompt müssen Text sein' });
      return;
    }
    if (archived !== undefined && typeof archived !== 'boolean') {
      invalid.push({ label, reason: 'archived muss true oder false sein' });
      return;
    }
    const errs = validateProperty(name, prompt);
    const reason = errs.name ?? errs.prompt;
    if (reason) {
      invalid.push({ label, reason });
      return;
    }
    entries.push({ name, prompt: prompt.trim(), archived: archived ?? false });
  });
  return { ok: true, entries, invalid };
}

export interface ImportDeps {
  create: (name: string, prompt: string) => Promise<unknown>;
  archive: (name: string, archive: boolean) => Promise<unknown>;
}

/**
 * Creates each entry whose name is new (archiving it when the file says so), one after
 * the other; existing names and repeats within the file are skipped, never overwritten.
 */
export async function importProperties(
  entries: readonly PropertyEntry[],
  existing: Iterable<string>,
  deps: ImportDeps,
  errorText: (err: unknown) => string,
): Promise<Omit<ImportResult, 'invalid'>> {
  const seen = new Set(existing);
  const out: Omit<ImportResult, 'invalid'> = { imported: [], skipped: [], failed: [] };
  for (const e of entries) {
    if (seen.has(e.name)) {
      out.skipped.push(e.name);
      continue;
    }
    seen.add(e.name);
    try {
      // oxlint-disable-next-line no-await-in-loop -- one after the other: names stay in file order
      await deps.create(e.name, e.prompt);
    } catch (err) {
      if (isApiError(err) && err.code === 'property_exists') out.skipped.push(e.name);
      else out.failed.push({ label: e.name, reason: errorText(err) });
      continue;
    }
    out.imported.push(e.name);
    if (e.archived) {
      try {
        // oxlint-disable-next-line no-await-in-loop -- right after its create
        await deps.archive(e.name, true);
      } catch (err) {
        out.failed.push({ label: e.name, reason: `angelegt, aber nicht archiviert: ${errorText(err)}` });
      }
    }
  }
  return out;
}

/** „2 importiert, 1 übersprungen (gibt es schon), 1 ungültig“ (+ „, 1 fehlgeschlagen“). */
export function importSummary(r: ImportResult): string {
  const parts = [
    `${r.imported.length} importiert`,
    `${r.skipped.length} übersprungen (gibt es schon)`,
    `${r.invalid.length} ungültig`,
  ];
  if (r.failed.length) parts.push(`${r.failed.length} fehlgeschlagen`);
  return parts.join(', ');
}
