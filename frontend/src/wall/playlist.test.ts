import { describe, expect, it } from 'vitest';
import type { PlaylistEntry } from './api/types';
import { modeAllowed, modeContent, nextMode } from './playlist';

const only = (entries: PlaylistEntry[], on: (e: PlaylistEntry) => boolean): PlaylistEntry[] =>
  entries.map((e) => ({ mode: e.mode, duration_s: e.duration_s, enabled: on(e) }));

const all: PlaylistEntry[] = [
  { mode: 'spotlight', enabled: true, duration_s: 120 },
  { mode: 'gallery', enabled: true, duration_s: 45 },
  { mode: 'categories', enabled: true, duration_s: 60 },
];

describe('playlist', () => {
  it('knows which modes have content', () => {
    expect(modeContent(0, 0)).toEqual({ spotlight: false, gallery: false, categories: false });
    expect(modeContent(5, 0)).toEqual({ spotlight: true, gallery: false, categories: false });
    expect(modeContent(6, 1)).toEqual({ spotlight: true, gallery: true, categories: true });
  });

  it('goes through the enabled modes in order and wraps', () => {
    const full = modeContent(10, 2);
    expect(nextMode(all, null, full)).toBe('spotlight');
    expect(nextMode(all, 'spotlight', full)).toBe('gallery');
    expect(nextMode(all, 'gallery', full)).toBe('categories');
    expect(nextMode(all, 'categories', full)).toBe('spotlight');
  });

  it('follows the configured order', () => {
    const order: PlaylistEntry[] = [all[2]!, all[0]!, all[1]!];
    expect(nextMode(order, null, modeContent(10, 2))).toBe('categories');
    expect(nextMode(order, 'categories', modeContent(10, 2))).toBe('spotlight');
  });

  it('skips disabled modes and modes without content', () => {
    const noGallery = only(all, (e) => e.mode !== 'gallery');
    expect(nextMode(noGallery, 'spotlight', modeContent(10, 1))).toBe('categories');
    // 5 photos: no gallery; no categories yet
    expect(nextMode(all, 'spotlight', modeContent(5, 0))).toBe('spotlight');
    expect(nextMode(all, null, modeContent(0, 1))).toBe('categories');
  });

  it('a single enabled mode just stays', () => {
    const single = only(all, (e) => e.mode === 'gallery');
    expect(nextMode(single, 'gallery', modeContent(10, 3))).toBe('gallery');
    expect(nextMode(single, null, modeContent(10, 3))).toBe('gallery');
  });

  it('nothing to show → null', () => {
    expect(nextMode(all, null, modeContent(0, 0))).toBeNull();
    const single = only(all, (e) => e.mode === 'gallery');
    expect(nextMode(single, 'gallery', modeContent(3, 0))).toBeNull();
  });

  it('modeAllowed needs enabled and content', () => {
    expect(modeAllowed(all, 'gallery', modeContent(6, 0))).toBe(true);
    expect(modeAllowed(all, 'gallery', modeContent(5, 0))).toBe(false);
    const off = only(all, (e) => e.mode !== 'spotlight');
    expect(modeAllowed(off, 'spotlight', modeContent(6, 0))).toBe(false);
  });
});
