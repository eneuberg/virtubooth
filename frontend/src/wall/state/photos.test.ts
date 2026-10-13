import { describe, expect, it } from 'vitest';
import { DEFAULT_CONFIG, type WallEvent } from '../api/types';
import { feed, photo, pool } from '../fixtures.test-util';
import { visibleCategories } from '../modes/categories';
import { initialWallState, MAX_PHOTOS, wallReducer, type WallState } from './photos';

const ev = (event: WallEvent) => ({ type: 'event' as const, event });

function loaded(count = 3): WallState {
  return wallReducer(initialWallState, {
    type: 'feed',
    feed: feed(pool(count)),
    now: Date.parse('2026-10-13T20:00:05Z'),
  });
}

describe('wallReducer', () => {
  it('takes the feed, newest first, and the clock skew', () => {
    const s = wallReducer(initialWallState, {
      type: 'feed',
      feed: feed([photo(1), photo(3), photo(2)]),
      now: Date.parse('2026-10-13T20:00:05Z'),
    });
    expect(s.loaded).toBe(true);
    expect(s.photos.map((p) => p.id)).toEqual(['p3', 'p2', 'p1']);
    expect(s.eventName).toBe('Sommerfest');
    expect(s.total).toBe(3);
    expect(s.clockSkewMs).toBe(5000);
  });

  it('adds a photo in order, counts it and marks it fresh', () => {
    const s = wallReducer(loaded(), ev({ type: 'photo.add', data: { photo: photo(9) } }));
    expect(s.photos[0]!.id).toBe('p9');
    expect(s.total).toBe(4);
    expect(s.fresh).toEqual(['p9']);
    // a repeated add (replay) changes nothing but the data
    const again = wallReducer(
      s,
      ev({ type: 'photo.add', data: { photo: photo(9, 'a', { author: 'Neu' }) } }),
    );
    expect(again.total).toBe(4);
    expect(again.photos.filter((p) => p.id === 'p9')).toHaveLength(1);
    expect(again.photos[0]!.author).toBe('Neu');
  });

  it('keeps at most MAX_PHOTOS', () => {
    const big = wallReducer(initialWallState, { type: 'feed', feed: feed(pool(MAX_PHOTOS)) });
    const s = wallReducer(big, ev({ type: 'photo.add', data: { photo: photo(MAX_PHOTOS + 1) } }));
    expect(s.photos).toHaveLength(MAX_PHOTOS);
    expect(s.photos[0]!.id).toBe(`p${MAX_PHOTOS + 1}`);
  });

  it('updates a known photo and ignores unknown ones', () => {
    const s = wallReducer(
      loaded(),
      ev({ type: 'photo.update', data: { photo: photo(2, 'a', { instagram: 'lena' }) } }),
    );
    expect(s.photos.find((p) => p.id === 'p2')!.instagram).toBe('lena');
    const same = wallReducer(s, ev({ type: 'photo.update', data: { photo: photo(77) } }));
    expect(same).toBe(s);
  });

  it('removes photos at once and remembers the ids', () => {
    const added = wallReducer(loaded(), ev({ type: 'photo.add', data: { photo: photo(9) } }));
    const s = wallReducer(added, ev({ type: 'photo.remove', data: { ids: ['p9', 'p2', 'old'] } }));
    expect(s.photos.map((p) => p.id)).toEqual(['p3', 'p1']);
    expect(s.total).toBe(2);
    expect(s.fresh).toEqual([]);
    expect(s.removed).toEqual(['p9', 'p2', 'old']);
  });

  it('applies a config event', () => {
    const config = { ...DEFAULT_CONFIG, look: { ...DEFAULT_CONFIG.look, primary: '#22c55e' } };
    const qr = { url: '/?t=abc', name: 'Otter 1' };
    const s = wallReducer(loaded(), ev({ type: 'config', data: { config, event_name: 'Hochzeit', qr } }));
    expect(s.config.look.primary).toBe('#22c55e');
    expect(s.eventName).toBe('Hochzeit');
    expect(s.qr).toEqual(qr);
    const off = wallReducer(s, ev({ type: 'config', data: { config, event_name: 'Hochzeit', qr: null } }));
    expect(off.qr).toBeNull();
  });

  it('counts categories.changed', () => {
    const s = wallReducer(loaded(), ev({ type: 'categories.changed', data: {} }));
    expect(s.categoriesRev).toBe(1);
  });

  it('a new snapshot drops fresh ids it does not contain', () => {
    let s = wallReducer(loaded(), ev({ type: 'photo.add', data: { photo: photo(9) } }));
    s = wallReducer(s, ev({ type: 'photo.add', data: { photo: photo(10) } }));
    s = wallReducer(s, { type: 'feed', feed: feed([photo(10), ...pool(3)]) });
    expect(s.fresh).toEqual(['p10']);
  });
});

const cat = (id: string, ...ids: string[]) => ({
  id,
  emoji: '👥',
  title: id,
  line: '',
  winners: ids.map((pid, i) => ({ photo: photo(Number(pid.slice(1))), value: i, label: `${i}` })),
});

describe('visibleCategories', () => {
  it('drops disabled categories, removed winners and empty categories', () => {
    const list = [cat('volles_haus', 'p1', 'p2'), cat('peace', 'p3'), cat('rock', 'p4')];
    const out = visibleCategories(list, ['rock'], ['p1', 'p3']);
    expect(out.map((c) => c.id)).toEqual(['volles_haus']);
    expect(out[0]!.winners.map((w) => w.photo.id)).toEqual(['p2']);
  });
});
