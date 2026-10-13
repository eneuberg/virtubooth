/**
 * The wall's data: the feed snapshot plus the live events on top of it. Pure reducer
 * (Vitest), at most MAX_PHOTOS photos, newest first.
 */
import {
  DEFAULT_CONFIG,
  type WallConfig,
  type WallEvent,
  type WallFeed,
  type WallPhoto,
  type WallQr,
} from '../api/types';

export const MAX_PHOTOS = 1000;
/** how many removed ids the state remembers (category winners can be older than the feed) */
const MAX_REMOVED = 500;

export interface WallState {
  /** false until the first feed arrived */
  loaded: boolean;
  config: WallConfig;
  eventName: string;
  /** the corner QR code (null: none) */
  qr: WallQr | null;
  /** all visible photos on the server (the feed may hold fewer) */
  total: number;
  /** newest first */
  photos: WallPhoto[];
  /** ids that arrived live and were not in a snapshot yet, oldest first (fresh_first) */
  fresh: string[];
  /** recently removed ids: category winners and preloaded images must skip them */
  removed: string[];
  /** bumped by `categories.changed` */
  categoriesRev: number;
  /** client clock minus server clock in ms (for „vor 3 Min.“ on a TV with a wrong clock) */
  clockSkewMs: number;
}

export type WallAction = { type: 'feed'; feed: WallFeed; now?: number } | { type: 'event'; event: WallEvent };

export const initialWallState: WallState = {
  loaded: false,
  config: DEFAULT_CONFIG,
  eventName: '',
  qr: null,
  total: 0,
  photos: [],
  fresh: [],
  removed: [],
  categoriesRev: 0,
  clockSkewMs: 0,
};

/** newest first: taken_at, then seq */
function newerFirst(a: WallPhoto, b: WallPhoto): number {
  if (a.taken_at !== b.taken_at) return a.taken_at < b.taken_at ? 1 : -1;
  return b.seq - a.seq;
}

function insertPhoto(photos: WallPhoto[], photo: WallPhoto): WallPhoto[] {
  const next = [...photos];
  let i = 0;
  while (i < next.length && newerFirst(next[i]!, photo) < 0) i++;
  next.splice(i, 0, photo);
  return next.length > MAX_PHOTOS ? next.slice(0, MAX_PHOTOS) : next;
}

function skewOf(serverTime: string, now: number): number {
  const server = Date.parse(serverTime);
  return Number.isFinite(server) ? now - server : 0;
}

export function wallReducer(state: WallState, action: WallAction): WallState {
  if (action.type === 'feed') {
    const { feed } = action;
    const photos = feed.photos.toSorted(newerFirst).slice(0, MAX_PHOTOS);
    const ids = new Set(photos.map((p) => p.id));
    return {
      ...state,
      loaded: true,
      config: feed.config,
      eventName: feed.event_name,
      qr: feed.qr ?? null,
      total: feed.total,
      photos,
      fresh: state.fresh.filter((id) => ids.has(id)),
      removed: state.removed.filter((id) => !ids.has(id)),
      clockSkewMs: skewOf(feed.server_time, action.now ?? Date.now()),
    };
  }
  const { event } = action;
  switch (event.type) {
    case 'photo.add': {
      const photo = event.data.photo;
      const exists = state.photos.some((p) => p.id === photo.id);
      if (exists) return { ...state, photos: state.photos.map((p) => (p.id === photo.id ? photo : p)) };
      return {
        ...state,
        photos: insertPhoto(state.photos, photo),
        total: state.total + 1,
        fresh: [...state.fresh, photo.id],
        removed: state.removed.filter((id) => id !== photo.id),
      };
    }
    case 'photo.update': {
      const photo = event.data.photo;
      if (!state.photos.some((p) => p.id === photo.id)) return state;
      return { ...state, photos: state.photos.map((p) => (p.id === photo.id ? photo : p)) };
    }
    case 'photo.remove': {
      const gone = new Set(event.data.ids);
      const photos = state.photos.filter((p) => !gone.has(p.id));
      const removedHere = state.photos.length - photos.length;
      return {
        ...state,
        photos,
        total: Math.max(0, state.total - removedHere),
        fresh: state.fresh.filter((id) => !gone.has(id)),
        removed: [...state.removed.filter((id) => !gone.has(id)), ...gone].slice(-MAX_REMOVED),
      };
    }
    case 'config':
      return {
        ...state,
        config: event.data.config,
        eventName: event.data.event_name,
        qr: event.data.qr ?? null,
      };
    case 'categories.changed':
      return { ...state, categoriesRev: state.categoriesRev + 1 };
    default:
      return state;
  }
}
