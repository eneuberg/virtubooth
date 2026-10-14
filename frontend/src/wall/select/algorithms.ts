/**
 * Spotlight selection algorithms (PLAN-WALL D9: client side, pure).
 *
 *   const sel = createSelector('fair', { n: 12 }, rng);
 *   const photo = sel.next(pool, ctx);   // pool: the visible photos, newest first
 *
 * The caller counts what it showed in `ctx.shown` (recordShown). `pool` is always the
 * current state, so a removed photo can never be returned.
 */
import type { WallAlgorithm, WallPhoto } from '../api/types';
import { pick, type Rng } from '../rng';

export interface SelectContext {
  /** how often each photo id was shown */
  shown: Map<string, number>;
  /** ids that arrived live, oldest first */
  fresh: readonly string[];
  /** category winners in catalogue order */
  highlights: readonly string[];
}

export interface Selector {
  next(pool: readonly WallPhoto[], ctx: SelectContext): WallPhoto | null;
}

export interface SelectorOptions {
  /** `newest`: how many of the newest photos it cycles */
  n: number;
}

export function emptyContext(): SelectContext {
  return { shown: new Map(), fresh: [], highlights: [] };
}

export function recordShown(ctx: SelectContext, id: string): void {
  ctx.shown.set(id, (ctx.shown.get(id) ?? 0) + 1);
}

const count = (ctx: SelectContext, id: string): number => ctx.shown.get(id) ?? 0;

/** Without `lastId` when something else is left. */
function others(pool: readonly WallPhoto[], lastId: string | null): readonly WallPhoto[] {
  if (lastId === null || pool.length < 2) return pool;
  const rest = pool.filter((p) => p.id !== lastId);
  return rest.length > 0 ? rest : pool;
}

/** Cycles the newest n photos, newest first; new arrivals join at the front. */
function newest(opts: SelectorOptions): Selector {
  let last: string | null = null;
  return {
    next(pool) {
      const candidates = pool.slice(0, Math.max(1, opts.n));
      if (candidates.length === 0) return null;
      const at = last === null ? -1 : candidates.findIndex((p) => p.id === last);
      const photo = candidates[(at + 1) % candidates.length]!;
      last = photo.id;
      return photo;
    },
  };
}

/** Uniform, never the same photo twice in a row. */
function random(rng: Rng): Selector {
  let last: string | null = null;
  return {
    next(pool) {
      const photo = pick(others(pool, last), rng) ?? null;
      last = photo?.id ?? null;
      return photo;
    },
  };
}

interface Bag extends Selector {
  /** counts as drawn in this round (shown by another rule) */
  take(id: string): void;
}

/** A bag: every photo once per round, in random order; new photos join the current bag. */
function shuffle(rng: Rng): Bag {
  const drawn = new Set<string>();
  let last: string | null = null;
  return {
    take(id) {
      drawn.add(id);
      last = id;
    },
    next(pool) {
      if (pool.length === 0) return null;
      let bag = pool.filter((p) => !drawn.has(p.id));
      if (bag.length === 0) {
        drawn.clear();
        bag = [...others(pool, last)];
      }
      const photo = pick(bag, rng)!;
      drawn.add(photo.id);
      last = photo.id;
      return photo;
    },
  };
}

/** Round robin over the guests (author_key): each turn the guest's newest unshown photo. */
function fair(): Selector {
  const turns = new Map<string, number>();
  let clock = 0;
  let last: string | null = null;
  return {
    next(pool, ctx) {
      if (pool.length === 0) return null;
      const byAuthor = new Map<string, WallPhoto[]>(); // insertion order = newest photo first
      for (const p of pool) {
        const list = byAuthor.get(p.author_key);
        if (list) list.push(p);
        else byAuthor.set(p.author_key, [p]);
      }
      // the guest whose turn is longest ago (never = first); ties: the newest photo
      let author: string | null = null;
      let best = Infinity;
      for (const key of byAuthor.keys()) {
        const turn = turns.get(key) ?? -1;
        if (turn < best) {
          best = turn;
          author = key;
        }
      }
      const photos = byAuthor.get(author!)!;
      // newest unshown, else the least shown (ties: newer), not the last one when possible
      const choices = others(photos, byAuthor.size === 1 ? last : null);
      let photo = choices[0]!;
      for (const p of choices) if (count(ctx, p.id) < count(ctx, photo.id)) photo = p;
      turns.set(author!, clock++);
      last = photo.id;
      return photo;
    },
  };
}

/** The least shown photo; ties: the newer one. */
function leastShown(): Selector {
  let last: string | null = null;
  return {
    next(pool, ctx) {
      const choices = others(pool, last);
      if (choices.length === 0) return null;
      let photo = choices[0]!;
      for (const p of choices) if (count(ctx, p.id) < count(ctx, photo.id)) photo = p;
      last = photo.id;
      return photo;
    },
  };
}

/** Unshown live arrivals first (in arrival order), otherwise a shuffle bag. */
function freshFirst(rng: Rng): Selector {
  const rest = shuffle(rng);
  return {
    next(pool, ctx) {
      const ids = new Set(pool.map((p) => p.id));
      const id = ctx.fresh.find((f) => ids.has(f) && count(ctx, f) === 0);
      if (id !== undefined) {
        rest.take(id);
        return pool.find((p) => p.id === id) ?? null;
      }
      return rest.next(pool, ctx);
    },
  };
}

/** Category winners first (each once), then a shuffle bag. */
function highlights(rng: Rng): Selector {
  const rest = shuffle(rng);
  const done = new Set<string>();
  return {
    next(pool, ctx) {
      const byId = new Map(pool.map((p) => [p.id, p]));
      const id = ctx.highlights.find((h) => byId.has(h) && !done.has(h));
      if (id !== undefined) {
        done.add(id);
        rest.take(id);
        return byId.get(id)!;
      }
      return rest.next(pool, ctx);
    },
  };
}

export function createSelector(kind: WallAlgorithm, opts: SelectorOptions, rng: Rng): Selector {
  switch (kind) {
    case 'newest':
      return newest(opts);
    case 'random':
      return random(rng);
    case 'shuffle':
      return shuffle(rng);
    case 'fair':
      return fair();
    case 'least_shown':
      return leastShown();
    case 'fresh_first':
      return freshFirst(rng);
    case 'highlights':
      return highlights(rng);
    default:
      return shuffle(rng);
  }
}
