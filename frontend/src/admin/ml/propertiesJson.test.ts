import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import { properties } from './fixtures';
import {
  exportPayload,
  IMPORT_MAX_BYTES,
  IMPORT_MAX_ENTRIES,
  importProperties,
  importSummary,
  parseImport,
  type PropertyEntry,
} from './propertiesJson';

const file = (props: unknown, version: unknown = 1) => JSON.stringify({ version, properties: props });
const text = (err: unknown) => (err instanceof Error ? err.message : String(err));

describe('Eigenschaften export', () => {
  it('writes all properties, archived ones included, with name, prompt and archived only', () => {
    expect(exportPayload(properties())).toEqual({
      version: 1,
      properties: [
        { name: 'coolness', prompt: 'Bewerte, wie cool jedes Objekt ist.', archived: false },
        { name: 'most_giraffe', prompt: 'Wie sehr erinnert das Objekt an eine Giraffe?', archived: true },
      ],
    });
  });

  it('round-trips through parseImport', () => {
    const out = parseImport(JSON.stringify(exportPayload(properties())));
    expect(out).toEqual({ ok: true, entries: exportPayload(properties()).properties, invalid: [] });
  });
});

describe('Eigenschaften import: validation', () => {
  it('rejects the whole file on bad JSON, version, shape, count or size', () => {
    expect(parseImport('{nope')).toEqual({ ok: false, error: 'Die Datei ist kein gültiges JSON.' });
    expect(parseImport(file([], 2)).ok).toBe(false);
    expect(parseImport('[]').ok).toBe(false);
    expect(parseImport(JSON.stringify({ version: 1, properties: {} })).ok).toBe(false);
    const many = Array.from({ length: IMPORT_MAX_ENTRIES + 1 }, (_, i) => ({ name: `p${i}`, prompt: 'x' }));
    expect(parseImport(file(many))).toEqual({ ok: false, error: 'Höchstens 200 Eigenschaften pro Datei.' });
    expect(parseImport(file([]), IMPORT_MAX_BYTES + 1)).toEqual({
      ok: false,
      error: 'Die Datei ist größer als 1 MB.',
    });
  });

  it('lists bad entries and keeps the good ones (prompt trimmed, archived defaults to false)', () => {
    const out = parseImport(
      file([
        { name: 'ok_one', prompt: '  Wie cool?  ' },
        { name: 'Bad Name', prompt: 'x' },
        { name: 'empty', prompt: '   ' },
        { name: 'long', prompt: 'x'.repeat(2001) },
        { name: 'flag', prompt: 'x', archived: 'yes' },
        { prompt: 'no name' },
        42,
      ]),
    );
    if (!out.ok) throw new Error(out.error);
    expect(out.entries).toEqual([{ name: 'ok_one', prompt: 'Wie cool?', archived: false }]);
    expect(out.invalid.map((x) => x.label)).toEqual([
      'Bad Name',
      'empty',
      'long',
      'flag',
      'Eintrag 6',
      'Eintrag 7',
    ]);
    expect(out.invalid[0]?.reason).toContain('Kleinbuchstaben');
  });
});

describe('Eigenschaften import: create, skip, archive', () => {
  const entries: PropertyEntry[] = [
    { name: 'coolness', prompt: 'anders', archived: false },
    { name: 'shiny', prompt: 'Wie glänzend?', archived: false },
    { name: 'old', prompt: 'Alt.', archived: true },
    { name: 'shiny', prompt: 'doppelt', archived: false },
    { name: 'raced', prompt: 'x', archived: false },
    { name: 'broken', prompt: 'x', archived: false },
  ];

  it('creates only new names, archives when asked, never overwrites', async () => {
    const create = vi.fn<(name: string, prompt: string) => Promise<unknown>>((name) => {
      if (name === 'raced') return Promise.reject(new ApiError(409, 'property_exists', 'gibt es schon'));
      if (name === 'broken') return Promise.reject(new Error('Server weg'));
      return Promise.resolve({});
    });
    const archive = vi.fn<(name: string, archive: boolean) => Promise<unknown>>(() => Promise.resolve({}));
    const out = await importProperties(entries, ['coolness'], { create, archive }, text);
    expect(create.mock.calls).toEqual([
      ['shiny', 'Wie glänzend?'],
      ['old', 'Alt.'],
      ['raced', 'x'],
      ['broken', 'x'],
    ]);
    expect(archive.mock.calls).toEqual([['old', true]]);
    expect(out).toEqual({
      imported: ['shiny', 'old'],
      skipped: ['coolness', 'shiny', 'raced'],
      failed: [{ label: 'broken', reason: 'Server weg' }],
    });
    expect(importSummary({ ...out, invalid: [{ label: 'x', reason: 'y' }] })).toBe(
      '2 importiert, 3 übersprungen (gibt es schon), 1 ungültig, 1 fehlgeschlagen',
    );
    expect(importSummary({ imported: ['a'], skipped: [], invalid: [], failed: [] })).toBe(
      '1 importiert, 0 übersprungen (gibt es schon), 0 ungültig',
    );
  });
});
