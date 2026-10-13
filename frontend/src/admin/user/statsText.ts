/** Words for the user page's „Statistik“ (pure; statsText.test.ts). */
import type { AdminExtension } from '@/api/types';
import { formatDuration, formatNumber, NBSP } from '@/lib/format';

/** "1 h 12 min in 3 Besuchen", "unter 1 min in 1 Besuch"; nothing yet: "noch nicht gemessen". */
export function onlineText(seconds: number, sessions: number): string {
  if (sessions <= 0) return 'noch nicht gemessen';
  const time = seconds > 0 ? formatDuration(seconds) : `unter 1${NBSP}min`;
  return `${time} in ${formatNumber(sessions)}${NBSP}${sessions === 1 ? 'Besuch' : 'Besuchen'}`;
}

/** "12: Beer Cam 8, Fotobox 4" (activity titles; an unknown id as it is). */
export function photoCountsText(
  photos: number,
  byActivity: ReadonlyArray<{ id: string; photos: number }>,
  extensions: ReadonlyMap<string, Pick<AdminExtension, 'title'>>,
): string {
  const parts = byActivity.map(
    (a) => `${extensions.get(a.id)?.title ?? a.id}${NBSP}${formatNumber(a.photos)}`,
  );
  return parts.length > 0 ? `${formatNumber(photos)}: ${parts.join(', ')}` : formatNumber(photos);
}
