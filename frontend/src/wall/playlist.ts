/**
 * The mode playlist: the enabled modes in order, skipping modes that have nothing to show.
 */
import type { PlaylistEntry, WallMode } from './api/types';

export const GALLERY_MIN_PHOTOS = 6;

export type ModeContent = Record<WallMode, boolean>;

/** Which modes have something to show. */
export function modeContent(photos: number, categories: number): ModeContent {
  return {
    spotlight: photos >= 1,
    gallery: photos >= GALLERY_MIN_PHOTOS,
    categories: categories >= 1,
  };
}

/**
 * The mode after `current`: the next enabled one with content, in playlist order (wrapping).
 * `current` itself only when nothing else qualifies; null when no mode can show anything.
 */
export function nextMode(
  playlist: readonly PlaylistEntry[],
  current: WallMode | null,
  content: ModeContent,
): WallMode | null {
  const at = current === null ? -1 : playlist.findIndex((e) => e.mode === current);
  for (let step = 1; step <= playlist.length; step++) {
    const entry = playlist[(at + step + playlist.length) % playlist.length];
    if (entry && entry.enabled && content[entry.mode]) return entry.mode;
  }
  return null;
}

/** How long a mode stays (seconds) per the playlist. */
export function modeDuration(playlist: readonly PlaylistEntry[], mode: WallMode): number {
  return playlist.find((e) => e.mode === mode)?.duration_s ?? 60;
}

/** Whether `mode` may still be shown (enabled and with content). */
export function modeAllowed(
  playlist: readonly PlaylistEntry[],
  mode: WallMode,
  content: ModeContent,
): boolean {
  return playlist.some((e) => e.mode === mode && e.enabled) && content[mode];
}
