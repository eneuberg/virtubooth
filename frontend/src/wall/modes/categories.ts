import { MAX_WINNERS, type WallCategory } from '../api/types';

/**
 * The categories the wall may show: not disabled in the live config, without winners
 * that were removed since /categories answered, and with at least one winner left; at
 * most 10 winners each, in the server's order. A verdict about a removed photo goes
 * with it.
 */
export function visibleCategories(
  categories: readonly WallCategory[],
  disabled: readonly string[],
  removed: readonly string[],
): WallCategory[] {
  const off = new Set(disabled);
  const gone = new Set(removed);
  return categories
    .filter((c) => !off.has(c.id))
    .map((c) => ({
      id: c.id,
      emoji: c.emoji,
      title: c.title,
      line: c.line,
      winners: c.winners.filter((w) => !gone.has(w.photo.id)).slice(0, MAX_WINNERS),
      verdict: c.verdict && !(c.verdict.photo_id && gone.has(c.verdict.photo_id)) ? c.verdict : null,
    }))
    .filter((c) => c.winners.length > 0);
}

/** The index of the winner a verdict is about: its `photo_id`, else the first. */
export function verdictIndex(category: Pick<WallCategory, 'winners' | 'verdict'>): number {
  const id = category.verdict?.photo_id;
  const at = id ? category.winners.findIndex((w) => w.photo.id === id) : -1;
  return at < 0 ? 0 : at;
}

/** Columns of the compact grid (more than 3 winners): 2 rows, TV-safe sizes. */
export function compactColumns(count: number): number {
  return Math.max(2, Math.ceil(count / 2));
}

/** Winner photo ids in catalogue order (the `highlights` algorithm). */
export function highlightIds(categories: readonly WallCategory[]): string[] {
  const ids: string[] = [];
  for (const c of categories) for (const w of c.winners) if (!ids.includes(w.photo.id)) ids.push(w.photo.id);
  return ids;
}
