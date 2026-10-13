import { describe, expect, it } from 'vitest';
import {
  changedKeys,
  isDirty,
  moveMode,
  normalizeHex,
  RANGES,
  setModeEnabled,
  toggleIn,
  validate,
} from './draft';
import { defaultConfig } from './fixtures';

describe('draft', () => {
  it('is clean until something differs, and names the changed top-level keys', () => {
    const base = defaultConfig();
    expect(isDirty(base, null)).toBe(false);
    expect(isDirty(base, defaultConfig())).toBe(false);
    const draft = defaultConfig();
    draft.spotlight.transition = 'glitch';
    draft.look.primary = '#112233';
    expect(isDirty(base, draft)).toBe(true);
    expect(changedKeys(base, draft)).toEqual(['spotlight', 'look']);
  });

  it('ignores server fields, key order and the order of set-like lists', () => {
    const base = { ...defaultConfig(), sources: ['beer', 'booth'] };
    const draft = { ...defaultConfig(), rev: 7, by: 'admin:1', sources: ['booth', 'beer'] };
    expect(isDirty(base, draft)).toBe(false);
    const reordered = { ...defaultConfig(), look: { ...defaultConfig().look } };
    const { preset, ...rest } = reordered.look;
    reordered.look = { ...rest, preset };
    expect(isDirty(defaultConfig(), reordered)).toBe(false);
  });

  it('a playlist move is a change', () => {
    const base = defaultConfig();
    const draft = { ...base, playlist: moveMode(base.playlist, 'gallery', -1) };
    expect(draft.playlist.map((e) => e.mode)).toEqual(['gallery', 'spotlight', 'categories']);
    expect(changedKeys(base, draft)).toEqual(['playlist']);
    expect(moveMode(base.playlist, 'spotlight', -1)).toBe(base.playlist);
    expect(moveMode(base.playlist, 'categories', 1)).toBe(base.playlist);
  });

  it('keeps the last mode on', () => {
    let playlist = defaultConfig().playlist;
    playlist = setModeEnabled(playlist, 'spotlight', false);
    playlist = setModeEnabled(playlist, 'gallery', false);
    expect(setModeEnabled(playlist, 'categories', false)).toBe(playlist);
    expect(playlist.filter((e) => e.enabled).map((e) => e.mode)).toEqual(['categories']);
  });

  it('defaults are valid', () => {
    expect(validate(defaultConfig())).toEqual({});
  });

  it('checks every range at both ends', () => {
    const c = defaultConfig();
    c.spotlight.algorithm = 'newest';
    const cases: Array<[string, (v: number) => void, readonly [number, number]]> = [
      ['playlist.gallery', (v) => (c.playlist[1] = { ...c.playlist[1]!, duration_s: v }), RANGES.duration_s],
      ['spotlight.n', (v) => (c.spotlight.n = v), RANGES.n],
      ['spotlight.interval_s', (v) => (c.spotlight.interval_s = v), RANGES.interval_s],
      ['spotlight.transition_ms', (v) => (c.spotlight.transition_ms = v), RANGES.transition_ms],
      ['gallery.rows', (v) => (c.gallery.rows = v), RANGES.rows],
      ['categories.per_category_s', (v) => (c.categories.per_category_s = v), RANGES.per_category_s],
      ['delay_s', (v) => (c.delay_s = v), RANGES.delay_s],
    ];
    for (const [path, set, [min, max]] of cases) {
      set(min);
      expect(validate(c)[path], `${path}=${min}`).toBeUndefined();
      set(max);
      expect(validate(c)[path], `${path}=${max}`).toBeUndefined();
      set(max + 1);
      expect(validate(c)[path], `${path}=${max + 1}`).toBe(`Bitte eine ganze Zahl von ${min} bis ${max}.`);
      set(min - 1); // -1 for delay_s: no negative numbers either
      expect(validate(c)[path]).toBeDefined();
      set(Number.NaN);
      expect(validate(c)[path]).toBeDefined();
      set(min);
    }
  });

  it('checks N only for "Die neuesten N"', () => {
    const c = defaultConfig();
    c.spotlight.n = 0;
    expect(validate(c)['spotlight.n']).toBeUndefined();
    c.spotlight.algorithm = 'newest';
    expect(validate(c)['spotlight.n']).toBeDefined();
  });

  it('checks colours and needs one mode on', () => {
    const c = defaultConfig();
    c.look.secondary = '#FFF';
    c.playlist = c.playlist.map((e) => ({ ...e, enabled: false }));
    const errors = validate(c);
    expect(errors['look.secondary']).toBe('Bitte eine Farbe wie #a855f7.');
    expect(errors.playlist).toBe('Mindestens ein Modus bleibt an.');
  });

  it('normalises hex colours', () => {
    expect(normalizeHex(' #A855F7 ')).toBe('#a855f7');
    expect(normalizeHex('ff4fa3')).toBe('#ff4fa3');
    expect(normalizeHex('#fff')).toBeNull();
    expect(normalizeHex('red')).toBeNull();
  });

  it('toggles ids in set-like lists', () => {
    expect(toggleIn([], 'beer', true)).toEqual(['beer']);
    expect(toggleIn(['beer'], 'beer', true)).toEqual(['beer']);
    expect(toggleIn(['beer', 'booth'], 'beer', false)).toEqual(['booth']);
  });
});
