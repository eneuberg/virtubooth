/**
 * Shapes the admin app keeps in its query cache, on top of the API aliases in
 * `@/api/types`.
 */
import type { AdminPhoto } from '@/api/types';

export type PhotoStatus = 'all' | 'visible' | 'hidden';

/** Which photos a list shows (manage filters; live uses ALL_PHOTOS). */
export interface PhotoFilter {
  ext: string | null;
  status: PhotoStatus;
  user: number | null;
}

export const ALL_PHOTOS: PhotoFilter = { ext: null, status: 'all', user: null };

/**
 * One page of `GET /api/admin/photos`. `incoming` (first page only) holds photos that
 * arrived through the event stream but are not shown yet: live merges them as soon as
 * the host is at the top, manage only when the host asks ("3 neue Fotos").
 */
export interface PhotoPage {
  photos: AdminPhoto[];
  next: string | null;
  total?: number | null;
  incoming?: AdminPhoto[];
}

export type GuestStatus = 'all' | 'banned' | 'ok' | 'paused';

export interface GuestFilter {
  search: string;
  status: GuestStatus;
  /** only guests who joined via this QR code (its number); null: all */
  code: number | null;
}

export const ALL_GUESTS: GuestFilter = { search: '', status: 'all', code: null };
