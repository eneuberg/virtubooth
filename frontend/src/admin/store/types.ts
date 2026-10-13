/**
 * Shapes the admin app keeps in its query cache, on top of the API aliases in
 * `@/api/types`.
 */
import type { AdminPhoto, ExportJob, InstagramHandle } from '@/api/types';

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
}

/** `GET /api/admin/instagram` gains `done` per handle (PLAN §3.3, built by BE-features). */
export type BoardHandle = InstagramHandle & { done?: boolean };

// ------------------------------------------- exports (contracts/api.md §6, BE-features)
// TODO(merge): alias the schema once BE-features' endpoints are in openapi.json.

/** `ExportJob` as BE-features ships it: plus `download_url` and the options it runs with. */
export type AdminExportJob = ExportJob & {
  download_url?: string | null;
  options?: Record<string, unknown>;
};

/** GET /api/admin/exports */
export interface ExportList {
  jobs: AdminExportJob[];
  /** VB_PUBLIC_BASE_URL: prefill of the QR form; null: the field is required */
  public_base_url?: string | null;
  /** false: timelapse jobs can't run (no ffmpeg on the server) */
  ffmpeg?: boolean;
}

/** Events BE-features adds to the stream (not in `@/api/events` yet). */
export type ExtraAdminEvent =
  | { type: 'export.deleted'; data: { id: string }; id?: string }
  | { type: 'instagram.done'; data: { handle: string; done: boolean }; id?: string };
