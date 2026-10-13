/**
 * Photo grids: arrow-key navigation between tiles, the tile to focus after a viewer
 * closes, "is the page at the top", and loading the next page before the end.
 */
import { useEffect, useRef, useSyncExternalStore, type RefObject } from 'react';

/** The open button of a photo tile (first button inside `[data-photo-id]`). */
export function tileButton(id: string): HTMLElement | null {
  return document.querySelector<HTMLElement>(`[data-photo-id="${CSS.escape(id)}"] button`);
}

/**
 * Arrow keys move between the tiles' open buttons like in a grid: ←/→ one tile,
 * ↑/↓ one row (columns are counted from the layout), Home/End to the ends.
 */
export function moveInGrid(event: KeyboardEvent, grid: HTMLElement): void {
  if (event.altKey || event.ctrlKey || event.metaKey) return;
  const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'];
  if (!keys.includes(event.key)) return;
  const target = event.target instanceof HTMLElement ? event.target : null;
  const tile = target?.closest<HTMLElement>('[data-photo-id]');
  if (!tile || !grid.contains(tile)) return;
  const tiles = [...grid.querySelectorAll<HTMLElement>('[data-photo-id]')];
  const i = tiles.indexOf(tile);
  if (i === -1) return;
  const top = tiles[0]?.offsetTop ?? 0;
  const columns = Math.max(1, tiles.filter((t) => t.offsetTop === top).length);
  const next = {
    ArrowLeft: i - 1,
    ArrowRight: i + 1,
    ArrowUp: i - columns,
    ArrowDown: i + columns,
    Home: 0,
    End: tiles.length - 1,
  }[event.key];
  const to = next === undefined ? undefined : tiles[next];
  if (!to) return;
  event.preventDefault();
  to.querySelector<HTMLElement>('button')?.focus();
  to.scrollIntoView({ block: 'nearest' });
}

/** Arrow keys between the tiles of the list this ref is on (moveInGrid). */
export function useGridKeys<T extends HTMLElement>(): RefObject<T | null> {
  const ref = useRef<T>(null);
  useEffect(() => {
    const grid = ref.current;
    if (!grid) return undefined;
    const onKey = (event: KeyboardEvent) => moveInGrid(event, grid);
    grid.addEventListener('keydown', onKey);
    return () => grid.removeEventListener('keydown', onKey);
  });
  return ref;
}

export const AT_TOP = 60;

function subscribeScroll(notify: () => void): () => void {
  window.addEventListener('scroll', notify, { passive: true });
  return () => window.removeEventListener('scroll', notify);
}

/** True while the page is scrolled (almost) to the top. */
export function useAtTop(): boolean {
  return useSyncExternalStore(
    subscribeScroll,
    () => window.scrollY < AT_TOP,
    () => true,
  );
}

/**
 * Calls `load` when the sentinel comes within `margin` of the viewport (infinite
 * scroll). The visible "Ältere Fotos laden" button stays as the accessible way.
 */
export function useLoadMore(
  load: () => void,
  enabled: boolean,
  margin = '600px',
): RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement>(null);
  const latest = useRef(load);
  useEffect(() => {
    latest.current = load;
  });
  useEffect(() => {
    const el = ref.current;
    if (!el || !enabled) return undefined;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) latest.current();
      },
      { rootMargin: margin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [enabled, margin]);
  return ref;
}
