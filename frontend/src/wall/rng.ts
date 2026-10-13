/** A random number generator in [0, 1): Math.random, or seeded (mulberry32) for tests. */
export type Rng = () => number;

export function seededRng(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const mathRng: Rng = () => Math.random();

/** One element, uniformly; undefined for an empty list. */
export function pick<T>(items: readonly T[], rng: Rng): T | undefined {
  if (items.length === 0) return undefined;
  return items[Math.min(items.length - 1, Math.floor(rng() * items.length))];
}

/** One key by weight (weights > 0). */
export function pickWeighted<T>(items: readonly (readonly [T, number])[], rng: Rng): T | undefined {
  const total = items.reduce((sum, [, w]) => sum + w, 0);
  if (items.length === 0 || total <= 0) return undefined;
  let r = rng() * total;
  for (const [item, w] of items) {
    r -= w;
    if (r < 0) return item;
  }
  return items[items.length - 1]?.[0];
}
