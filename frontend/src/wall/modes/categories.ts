import type { WallCategory } from '../api/types';

/**
 * The categories the wall may show: not disabled in the live config, without winners
 * that were removed since /categories answered, and with at least one winner left.
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
      winners: c.winners.filter((w) => !gone.has(w.photo.id)).slice(0, 3),
    }))
    .filter((c) => c.winners.length > 0);
}

/** Winner photo ids in catalogue order (the `highlights` algorithm). */
export function highlightIds(categories: readonly WallCategory[]): string[] {
  const ids: string[] = [];
  for (const c of categories) for (const w of c.winners) if (!ids.includes(w.photo.id)) ids.push(w.photo.id);
  return ids;
}
