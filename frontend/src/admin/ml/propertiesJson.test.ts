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
  it('writes all properties, the Papierkorb included, with name, prompt and deleted', () => {
    expect(exportPayload(properties())).toEqual({
      version: 1,
      properties: [
        { name: 'coolness', prompt: 'Bewerte, wie cool jedes Objekt ist.', deleted: false },
        { name: 'most_giraffe', prompt: 'Wie sehr erinnert das Objekt an eine Giraffe?', deleted: false },
        { name: 'old_vibe', prompt: 'Wie retro wirkt das Objekt?', deleted: true },
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

  it('lists bad entries and keeps the good ones (prompt trimmed)', () => {
    const out = parseImport(
      file([
        { name: 'ok_one', prompt: '  Wie cool?  ' },
        { name: 'Bad Name', prompt: 'x' },
        { name: 'empty', prompt: '   ' },
        { name: 'long', prompt: 'x'.repeat(2001) },
        { name: 'flag', prompt: 'x', archived: 'yes' },
        { prompt: 'no name' },
        42,
        { name: 'flag_two', prompt: 'x', active: 1 },
        { name: 'flag_three', prompt: 'x', deleted: 'no' },
      ]),
    );
    if (!out.ok) throw new Error(out.error);
    expect(out.entries).toEqual([{ name: 'ok_one', prompt: 'Wie cool?', deleted: false }]);
    expect(out.invalid.map((x) => x.label)).toEqual([
      'Bad Name',
      'empty',
      'long',
      'flag',
      'Eintrag 6',
      'Eintrag 7',
      'flag_two',
      'flag_three',
    ]);
    expect(out.invalid[0]?.reason).toContain('Kleinbuchstaben');
    expect(out.invalid[6]?.reason).toBe('active muss true oder false sein');
  });

  it('reads older files: `active` and `archived` (the switch, gone) are ignored', () => {
    const out = parseImport(
      file([
        { name: 'old_one', prompt: 'x', archived: true },
        { name: 'kept', prompt: 'x', archived: false },
        { name: 'both', prompt: 'x', archived: true, active: false, deleted: true },
      ]),
    );
    if (!out.ok) throw new Error(out.error);
    expect(out.entries.map((e) => [e.name, e.deleted])).toEqual([
      ['old_one', false],
      ['kept', false],
      ['both', true],
    ]);
  });
});

const entry = (name: string, prompt: string, deleted = false): PropertyEntry => ({ name, prompt, deleted });

describe('Eigenschaften import: create, skip, Papierkorb', () => {
  const entries: PropertyEntry[] = [
    entry('coolness', 'anders'),
    entry('shiny', 'Wie glänzend?'),
    entry('old', 'Alt.'),
    entry('shiny', 'doppelt'),
    entry('raced', 'x'),
    entry('broken', 'x'),
    entry('binned', 'Weg.', true),
  ];

  it('creates only new names, trashes when asked, never overwrites', async () => {
    const create = vi.fn<(name: string, prompt: string) => Promise<unknown>>((name) => {
      if (name === 'raced') return Promise.reject(new ApiError(409, 'property_exists', 'gibt es schon'));
      if (name === 'broken') return Promise.reject(new Error('Server weg'));
      return Promise.resolve({});
    });
    const trash = vi.fn<(name: string, trash: boolean) => Promise<unknown>>(() => Promise.resolve({}));
    const out = await importProperties(entries, ['coolness'], { create, trash }, text);
    expect(create.mock.calls).toEqual([
      ['shiny', 'Wie glänzend?'],
      ['old', 'Alt.'],
      ['raced', 'x'],
      ['broken', 'x'],
      ['binned', 'Weg.'],
    ]);
    expect(trash.mock.calls).toEqual([['binned', true]]);
    expect(out).toEqual({
      imported: ['shiny', 'old', 'binned'],
      skipped: ['coolness', 'shiny', 'raced'],
      failed: [{ label: 'broken', reason: 'Server weg' }],
    });
    expect(importSummary({ ...out, invalid: [{ label: 'x', reason: 'y' }] })).toBe(
      '3 importiert, 3 übersprungen (gibt es schon), 1 ungültig, 1 fehlgeschlagen',
    );
    expect(importSummary({ imported: ['a'], skipped: [], invalid: [], failed: [] })).toBe(
      '1 importiert, 0 übersprungen (gibt es schon), 0 ungültig',
    );
  });

  it('reports a follow-up step that failed', async () => {
    const out = await importProperties(
      [entry('binned', 'x', true)],
      [],
      {
        create: () => Promise.resolve({}),
        trash: () => Promise.reject(new Error('kaputt')),
      },
      text,
    );
    expect(out.failed).toEqual([
      { label: 'binned', reason: 'angelegt, aber nicht in den Papierkorb gelegt: kaputt' },
    ]);
  });
});
