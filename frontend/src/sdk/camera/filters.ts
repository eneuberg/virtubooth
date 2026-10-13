/**
 * Fotobox filters (GLSL snippets + Canvas2D fallbacks). OWNER: wave 2 "AC".
 * Ids and order come from the backend's extensions/booth/filters.json (normal, bw,
 * sepia, colorpop, party, emoji, neon, vhs, retro, comic).
 */

export interface FilterDef {
  /** ^[a-z][a-z0-9-]{0,31}$ */
  id: string;
  /** German display name, e.g. "Schwarz-Weiß" */
  name: string;
}

export const FILTERS: ReadonlyArray<FilterDef> = [];

export function getFilter(id: string): FilterDef | undefined {
  return FILTERS.find((f) => f.id === id);
}
