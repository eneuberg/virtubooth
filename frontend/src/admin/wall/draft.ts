/**
 * The Live Wall settings draft: edits collect locally and go to the server in one PUT.
 * Pure helpers (draft.test.ts): what changed, what is out of range, playlist moves.
 * Ranges from PLAN-WALL §4.1.
 */
import { sortedCopy } from '../lib/browser';
import type { PlaylistEntry, WallConfig, WallMode } from './types';

/**
 * What the admin sends. `categories.disabled` is left out: categories are switched on
 * and off in their own table now (PUT /categories/{id}); the server ignores the list.
 */
export type WallEdit = Omit<WallConfig, 'rev' | 'updated_at' | 'by' | 'categories'> & {
  categories: Pick<WallConfig['categories'], 'per_category_s'>;
};

export const RANGES = {
  duration_s: [10, 3600],
  n: [1, 100],
  interval_s: [3, 120],
  transition_ms: [300, 4000],
  rows: [2, 6],
  per_category_s: [4, 60],
  delay_s: [0, 600],
} as const satisfies Record<string, readonly [number, number]>;

export type RangeField = keyof typeof RANGES;

const HEX_RE = /^#[0-9a-f]{6}$/;

/** The part of a config the admin edits (server fields dropped). */
export function editable(config: WallConfig): WallEdit {
  return {
    playlist: config.playlist,
    spotlight: config.spotlight,
    gallery: config.gallery,
    categories: { per_category_s: config.categories.per_category_s },
    sources: config.sources,
    delay_s: config.delay_s,
    show_instagram: config.show_instagram,
    look: config.look,
    overlay: config.overlay,
  };
}

/** JSON with sorted keys; set-like lists (sources, disabled categories) sorted too. */
const byText = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

const EDIT_KEYS = [
  'playlist',
  'spotlight',
  'gallery',
  'categories',
  'sources',
  'delay_s',
  'show_instagram',
  'look',
  'overlay',
] as const satisfies ReadonlyArray<keyof WallEdit>;

function canonical(value: unknown, setLike = false): string {
  if (Array.isArray(value)) {
    const items = value.map((v) => canonical(v));
    return `[${(setLike ? sortedCopy(items, byText) : items).join(',')}]`;
  }
  if (value && typeof value === 'object') {
    const entries = sortedCopy(Object.entries(value), ([a], [b]) => byText(a, b)).map(
      ([k, v]) => `${JSON.stringify(k)}:${canonical(v, k === 'sources' || k === 'disabled')}`,
    );
    return `{${entries.join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

/** Top-level keys whose value differs (the server's audit names the same). */
export function changedKeys(base: WallConfig, draft: WallConfig): Array<keyof WallEdit> {
  const a = editable(base);
  const b = editable(draft);
  return EDIT_KEYS.filter((k) => canonical({ [k]: a[k] }) !== canonical({ [k]: b[k] }));
}

export function isDirty(base: WallConfig, draft: WallConfig | null): boolean {
  return draft !== null && changedKeys(base, draft).length > 0;
}

// ---------------------------------------------------------------- validation

/** Field path → German message. Paths: `playlist.<mode>`, `spotlight.n`, `look.primary`, … */
export type ValidationErrors = Partial<Record<string, string>>;

export function rangeText(field: RangeField): string {
  const [min, max] = RANGES[field];
  return `Bitte eine ganze Zahl von ${min} bis ${max}.`;
}

function inRange(value: number, field: RangeField): boolean {
  const [min, max] = RANGES[field];
  return Number.isInteger(value) && value >= min && value <= max;
}

export function validate(draft: WallConfig): ValidationErrors {
  const errors: ValidationErrors = {};
  const check = (path: string, value: number, field: RangeField) => {
    if (!inRange(value, field)) errors[path] = rangeText(field);
  };
  for (const entry of draft.playlist) check(`playlist.${entry.mode}`, entry.duration_s, 'duration_s');
  if (!draft.playlist.some((e) => e.enabled)) errors.playlist = 'Mindestens ein Modus bleibt an.';
  if (draft.spotlight.algorithm === 'newest') check('spotlight.n', draft.spotlight.n, 'n');
  check('spotlight.interval_s', draft.spotlight.interval_s, 'interval_s');
  check('spotlight.transition_ms', draft.spotlight.transition_ms, 'transition_ms');
  check('gallery.rows', draft.gallery.rows, 'rows');
  check('categories.per_category_s', draft.categories.per_category_s, 'per_category_s');
  check('delay_s', draft.delay_s, 'delay_s');
  for (const key of ['primary', 'secondary', 'background'] as const) {
    const value = draft.look[key];
    if (value !== null && !HEX_RE.test(value)) errors[`look.${key}`] = 'Bitte eine Farbe wie #a855f7.';
  }
  return errors;
}

/** "#A855F7", "a855f7", " #a855f7 " → "#a855f7"; anything else → null. */
export function normalizeHex(text: string): string | null {
  const t = text.trim().toLowerCase();
  const hex = t.startsWith('#') ? t : `#${t}`;
  return HEX_RE.test(hex) ? hex : null;
}

// ------------------------------------------------------------------ playlist

/** Move a mode one place up (-1) or down (+1); out of bounds: unchanged. */
export function moveMode(playlist: PlaylistEntry[], mode: WallMode, dir: -1 | 1): PlaylistEntry[] {
  const i = playlist.findIndex((e) => e.mode === mode);
  const j = i + dir;
  if (i < 0 || j < 0 || j >= playlist.length) return playlist;
  const next = [...playlist];
  const a = next[i];
  const b = next[j];
  if (!a || !b) return playlist;
  next[i] = b;
  next[j] = a;
  return next;
}

/** Switch a mode; the last one that is on stays on. */
export function setModeEnabled(playlist: PlaylistEntry[], mode: WallMode, enabled: boolean): PlaylistEntry[] {
  if (!enabled && playlist.filter((e) => e.enabled).length <= 1) return playlist;
  return playlist.map((e) => (e.mode === mode ? { ...e, enabled } : e));
}

export function setModeDuration(
  playlist: PlaylistEntry[],
  mode: WallMode,
  duration_s: number,
): PlaylistEntry[] {
  return playlist.map((e) => (e.mode === mode ? { ...e, duration_s } : e));
}

/** Add or remove an id from a set-like list (sources, disabled categories), order kept. */
export function toggleIn(list: string[], id: string, present: boolean): string[] {
  const has = list.includes(id);
  if (present === has) return list;
  return present ? [...list, id] : list.filter((x) => x !== id);
}
