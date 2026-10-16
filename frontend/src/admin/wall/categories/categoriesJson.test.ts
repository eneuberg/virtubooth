import { describe, expect, it } from 'vitest';
import { spec } from '../fixtures';
import type { CategoryImportResult } from '../types';
import {
  conflicts,
  exportName,
  IMPORT_MAX_BYTES,
  importProblems,
  importSummary,
  parseCategoriesFile,
} from './categoriesJson';

const v2 = {
  format: 'virtubooth-categories',
  version: 2,
  exported_at: '2026-10-16T21:00:00Z',
  properties: [{ name: 'coolness', prompt: 'Wie cool?' }],
  categories: [
    { id: 'coolstes_objekt', enabled: false, preset: 'coolstes_objekt', spec: spec({ title: 'Das coolste Objekt' }) },
    { id: 'volles_haus', enabled: true, preset: 'volles_haus', spec: spec() },
  ],
};

const result = (over: Partial<CategoryImportResult> = {}): CategoryImportResult => ({
  imported: [],
  skipped: [],
  properties_created: [],
  prompt_conflicts: [],
  switched_off: [],
  notes: [],
  ...over,
});

describe('reading a categories file', () => {
  it('reads the envelope: ids, titles, properties', () => {
    const parsed = parseCategoriesFile(JSON.stringify(v2));
    expect(parsed).toMatchObject({
      ok: true,
      version: 2,
      ids: ['coolstes_objekt', 'volles_haus'],
      titles: ['Das coolste Objekt', 'Volles Haus'],
      properties: ['coolness'],
    });
    // sent as it is
    expect(parsed.ok && parsed.file).toEqual(v2);
  });

  it('takes a v1 file (no format, v1 specs; an id from the title)', () => {
    const v1 = {
      version: 1,
      categories: [
        { id: 'huete', spec: { emoji: '🎩', title: 'Hutträger', where: [], select: { by: 'people' } } },
        { spec: { emoji: '🎉', title: 'Prost! Gläser' } },
      ],
    };
    expect(parseCategoriesFile(JSON.stringify(v1))).toMatchObject({ ok: true, version: 1, ids: ['huete', 'prost_glaeser'], properties: [] });
    // no version at all reads as 1
    expect(parseCategoriesFile(JSON.stringify({ categories: [] }))).toMatchObject({ ok: true, version: 1 });
  });

  it('refuses what is not a categories file', () => {
    const bad = (text: string) => {
      const out = parseCategoriesFile(text);
      return out.ok ? null : out.error;
    };
    expect(bad('{')).toBe('Die Datei ist kein gültiges JSON.');
    expect(bad('[]')).toBe('Die Datei ist kein JSON-Objekt.');
    expect(bad(JSON.stringify({ ...v2, version: 3 }))).toBe('Unbekannte Version: erwartet 1 oder 2.');
    expect(bad(JSON.stringify({ ...v2, format: 'eigenschaften' }))).toMatch(/^Unbekanntes Format/);
    expect(bad(JSON.stringify({ version: 2, categories: [] }))).toMatch(/^Unbekanntes Format/);
    // a properties file („Eigenschaften › Exportieren“) is not one
    expect(bad(JSON.stringify({ version: 1, properties: [] }))).toBe('Die Datei enthält keine Kategorien.');
    expect(bad(JSON.stringify({ ...v2, categories: Array.from({ length: 201 }, () => ({})) }))).toBe(
      'Höchstens 200 Kategorien pro Datei.',
    );
    expect(parseCategoriesFile('{}', IMPORT_MAX_BYTES + 1)).toEqual({ ok: false, error: 'Die Datei ist größer als 1 MB.' });
  });

  it('finds the ids that exist already (they come in as a copy, or replace)', () => {
    expect(conflicts(['volles_haus', 'neu', 'volles_haus'], ['volles_haus', 'prost'])).toEqual(['volles_haus']);
    expect(conflicts(['neu'], [])).toEqual([]);
    expect(exportName([])).toBe('kategorien.json');
    expect(exportName(['prost'])).toBe('kategorie-prost.json');
  });
});

describe('the import result', () => {
  it('says it in one line: copies, replaced, skipped, properties, prompt conflicts, off', () => {
    const r = result({
      imported: [
        { id: 'volles_haus_2', title: 'Volles Haus', enabled: true, from_id: 'volles_haus', replaced: false },
        { id: 'prost', title: 'Prost', enabled: true, from_id: null, replaced: true },
        { id: 'neu', title: 'Neu', enabled: false, from_id: null, replaced: false },
      ],
      skipped: [{ id: 'kaputt', reason: 'ungültig (Titel)' }],
      properties_created: ['glitzer', 'funkeln'],
      prompt_conflicts: ['coolness'],
      switched_off: [{ id: 'neu', reason: 'property_missing', detail: 'x', message: 'Die Eigenschaft „x“ gibt es nicht.' }],
      notes: ['Eigenschaft „funkeln“: „active“ wird nicht mehr gebraucht.'],
    });
    expect(importSummary(r)).toBe(
      '3 importiert (1 als Kopie, 1 ersetzt), 1 übersprungen. Eigenschaften angelegt: glitzer, funkeln. ' +
        'Prompt weicht ab, eure bleibt: coolness. 1 ausgeschaltet.',
    );
    expect(importProblems(r)).toEqual([
      'kaputt: übersprungen, ungültig (Titel)',
      'neu: aus, Die Eigenschaft „x“ gibt es nicht.',
      'Eigenschaft „funkeln“: „active“ wird nicht mehr gebraucht.',
    ]);
    expect(importSummary(result())).toBe('0 importiert.');
  });
});
