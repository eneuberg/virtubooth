import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { BoothFilter } from '@/api/types';
import { buildFilterList, FILTER_IMPLS, NORMAL, runsOn } from './filters';
import { fragmentSource, PRELUDE, previewSize } from './renderer';

/** The catalogue the server serves (GET /api/x/booth/filters) and validates uploads against. */
// vitest runs from frontend/
const CATALOGUE_FILE = resolve(process.cwd(), '../backend/src/virtubooth/extensions/booth/filters.json');
// oxlint-disable-next-line typescript/no-unsafe-type-assertion -- the backend's catalogue file
const catalogue = (JSON.parse(readFileSync(CATALOGUE_FILE, 'utf8')) as { filters: BoothFilter[] }).filters;

describe('filter catalogue ↔ shaders', () => {
  it('has a shader for every id the server accepts, and none it would refuse', () => {
    expect([...FILTER_IMPLS.keys()].toSorted()).toEqual(catalogue.map((f) => f.id).toSorted());
  });

  it('keeps the strip order and the German names from the catalogue', () => {
    const { filters, missing } = buildFilterList(catalogue, 'webgl');
    expect(missing).toEqual([]);
    expect(filters.map((f) => f.id)).toEqual([
      'normal',
      'bw',
      'sepia',
      'colorpop',
      'party',
      'emoji',
      'neon',
      'vhs',
      'retro',
      'comic',
      'thermal',
      'disco',
      'kaleido',
      'glow',
    ]);
    expect(filters.find((f) => f.id === 'bw')?.name).toBe('Schwarz-Weiß');
    expect(filters[0]?.id).toBe('normal'); // the default is first
  });

  it('leaves out GPU-only filters without WebGL', () => {
    const { filters } = buildFilterList(catalogue, 'canvas2d');
    expect(filters.map((f) => f.id)).toEqual([
      'normal',
      'bw',
      'sepia',
      'colorpop',
      'party',
      'emoji',
      'neon',
      'thermal',
    ]);
    for (const f of filters) expect(runsOn(f, 'canvas2d')).toBe(true);
  });

  it('reports catalogue ids without an implementation', () => {
    const { filters, missing } = buildFilterList(
      [...catalogue, { id: 'sparkle', name: 'Glitzer', icon: '✨' }],
      'webgl',
    );
    expect(missing).toEqual(['sparkle']);
    expect(filters).toHaveLength(catalogue.length);
  });

  it('every shader defines effect() on top of the shared prelude', () => {
    for (const impl of FILTER_IMPLS.values()) {
      expect(impl.glsl).toMatch(/vec3 effect\(vec2 uv\)/);
      const source = fragmentSource(impl);
      expect(source.startsWith(PRELUDE)).toBe(true);
      expect(source).toContain('gl_FragColor');
      // patterns live in output space, never screen pixels (WYSIWYG)
      expect(impl.glsl).not.toMatch(/gl_FragCoord/);
    }
    expect(PRELUDE).toContain('const vec2 OUT = vec2(1080.0, 1440.0)');
    expect(NORMAL.id).toBe('normal');
  });

  it('never uses CSS filters (the photo is the shader output)', () => {
    for (const impl of FILTER_IMPLS.values()) {
      expect(String(impl.cpu ?? '')).not.toMatch(/\.filter\s*=/);
    }
  });
});

describe('preview backing store', () => {
  it.each([
    // [css width, dpr, kind, w, h]
    [390, 2, 'webgl', 780, 1040],
    [390, 3, 'webgl', 780, 1040], // DPR capped at 2
    [600, 2, 'webgl', 1080, 1440], // never more than the photo
    [390, 2, 'canvas2d', 480, 640], // CPU pixel ops: small
    [20, 1, 'webgl', 60, 80],
  ] as const)('%s px at DPR %s on %s → %s×%s', (css, dpr, kind, w, h) => {
    expect(previewSize(css, dpr, kind)).toEqual({ w, h });
  });
});
