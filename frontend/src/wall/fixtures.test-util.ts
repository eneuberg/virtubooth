import { DEFAULT_CONFIG, type WallFeed, type WallPhoto } from './api/types';

/** A wall photo; `n` decides the id and the time (higher = newer). */
export function photo(n: number, author = 'a', extra: Partial<WallPhoto> = {}): WallPhoto {
  const id = `p${n}`;
  return {
    id,
    source: 'booth',
    seq: n,
    taken_at: new Date(Date.UTC(2026, 9, 13, 20, 0, n)).toISOString(),
    width: 1080,
    height: 1440,
    author: `Gast ${author}`,
    instagram: null,
    author_key: author,
    urls: { s: `/livewall/media/${id}?s=s`, m: `/livewall/media/${id}?s=m`, l: `/livewall/media/${id}?s=l` },
    facts: {},
    analysis: 'done',
    ...extra,
  };
}

/** Photos 1..count, newest first (the feed's order). */
export function pool(count: number, author: (n: number) => string = () => 'a'): WallPhoto[] {
  return Array.from({ length: count }, (_, i) => photo(count - i, author(count - i)));
}

export function feed(photos: WallPhoto[], extra: Partial<WallFeed> = {}): WallFeed {
  return {
    config: DEFAULT_CONFIG,
    event_name: 'Sommerfest',
    total: photos.length,
    photos,
    cursor: 42,
    server_time: '2026-10-13T20:00:00Z',
    ...extra,
  };
}
