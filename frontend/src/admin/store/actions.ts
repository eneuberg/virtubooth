/**
 * Admin actions. Each one calls the API and writes the answer into the cache right
 * away, so the screen that acted is current even when the event stream is down; the
 * stream's own copy of the change arrives later and is a no-op (idempotent reducers).
 */
import type { QueryClient } from '@tanstack/react-query';
import { api } from '@/api/client';
import type {
  AdminPhoto,
  BanResponse,
  DeviceUnbanResponse,
  ExportJob,
  ExportRequest,
  InstagramHandle,
  PauseResponse,
  PauseState,
  StopState,
  UnbanResponse,
  UserUploadsResponse,
} from '@/api/types';
import { dropPhoto, patchPhoto, patchUsers, removeExportJob, upsertExportJob } from './applyEvent';
import { call } from './api';
import { patchQueries } from './cache';
import { qk } from './keys';

const BULK_MAX = 200;

function chunks<T>(list: ReadonlyArray<T>, size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}

function hiddenCopy(photo: AdminPhoto, hidden: boolean): AdminPhoto {
  return {
    ...photo,
    hidden,
    hidden_reason: hidden ? 'admin' : null,
    hidden_at: hidden ? new Date().toISOString() : null,
  };
}

function refreshCounts(qc: QueryClient): void {
  void qc.invalidateQueries({ queryKey: qk.stats });
}

// ------------------------------------------------------------------ photos

/** Ausblenden / Einblenden. Optimistic: the tile flips at once and flips back on error. */
export async function setPhotoHidden(
  qc: QueryClient,
  photo: AdminPhoto,
  hidden: boolean,
): Promise<AdminPhoto> {
  patchPhoto(qc, hiddenCopy(photo, hidden));
  try {
    const params = { params: { path: { photo_id: photo.id } } };
    const res = hidden
      ? await call(api.POST('/api/admin/photos/{photo_id}/hide', params))
      : await call(api.POST('/api/admin/photos/{photo_id}/unhide', params));
    patchPhoto(qc, res.photo);
    refreshCounts(qc);
    return res.photo;
  } catch (err) {
    patchPhoto(qc, photo);
    throw err;
  }
}

/** Bulk Ausblenden / Einblenden. Returns how many photos changed. */
export async function bulkSetHidden(
  qc: QueryClient,
  photos: ReadonlyArray<AdminPhoto>,
  hidden: boolean,
): Promise<number> {
  let changed = 0;
  for (const part of chunks(photos, BULK_MAX)) {
    // oxlint-disable-next-line no-await-in-loop -- one chunk after the other, on purpose
    const res = await call(
      api.POST('/api/admin/photos/bulk', {
        body: { ids: part.map((p) => p.id), action: hidden ? 'hide' : 'unhide' },
      }),
    );
    const done = new Set(res.changed);
    const gone = new Set(res.missing);
    for (const p of part) {
      if (done.has(p.id)) patchPhoto(qc, hiddenCopy(p, hidden));
      if (gone.has(p.id)) dropPhoto(qc, p.id, p);
    }
    changed += res.changed.length;
  }
  refreshCounts(qc);
  return changed;
}

/**
 * Löschen (after the confirm dialog): the bulk endpoint in chunks of 200. Returns the
 * ids that are gone (deleted now, or already gone). Never used by the live screen.
 */
export async function deletePhotos(qc: QueryClient, photos: ReadonlyArray<AdminPhoto>): Promise<string[]> {
  const gone: string[] = [];
  try {
    for (const part of chunks(photos, BULK_MAX)) {
      // oxlint-disable-next-line no-await-in-loop -- one chunk after the other: stop at the first error
      const res = await call(
        api.POST('/api/admin/photos/bulk', { body: { ids: part.map((p) => p.id), action: 'delete' } }),
      );
      const ids = new Set([...res.changed, ...res.missing]);
      for (const p of part) {
        if (!ids.has(p.id)) continue;
        dropPhoto(qc, p.id, p);
        gone.push(p.id);
      }
    }
  } finally {
    refreshCounts(qc);
    void qc.invalidateQueries({ queryKey: qk.instagram });
  }
  return gone;
}

// ------------------------------------------------------------------ guests

function afterBanChange(qc: QueryClient, res: BanResponse | UnbanResponse): void {
  patchUsers(qc, [res.user]);
  for (const photo of res.photos) patchPhoto(qc, photo);
  for (const key of [qk.userDetails, qk.bannedUsers, qk.deviceBans, qk.userLists, qk.instagram, qk.stats]) {
    void qc.invalidateQueries({ queryKey: key });
  }
}

export async function banUser(
  qc: QueryClient,
  userId: number,
  body: { reason: string; fingerprint: boolean },
): Promise<BanResponse> {
  const res = await call(
    api.POST('/api/admin/users/{user_id}/ban', { params: { path: { user_id: userId } }, body }),
  );
  afterBanChange(qc, res);
  return res;
}

export async function unbanUser(
  qc: QueryClient,
  userId: number,
  fingerprint: boolean,
): Promise<UnbanResponse> {
  const res = await call(
    api.POST('/api/admin/users/{user_id}/unban', {
      params: { path: { user_id: userId } },
      body: { fingerprint },
    }),
  );
  afterBanChange(qc, res);
  return res;
}

/** Lift a device ban (Gerätemerkmal); releases the guests it banned automatically. */
export async function liftDeviceBan(qc: QueryClient, fpHash: string): Promise<DeviceUnbanResponse> {
  const res = await call(
    api.DELETE('/api/admin/device-bans/{fp_hash}', { params: { path: { fp_hash: fpHash } } }),
  );
  for (const key of [qk.deviceBans, qk.bannedUsers, qk.userDetails, qk.userLists, qk.stats]) {
    void qc.invalidateQueries({ queryKey: key });
  }
  return res;
}

export async function setUserPaused(
  qc: QueryClient,
  userId: number,
  paused: boolean,
): Promise<UserUploadsResponse> {
  const res = await call(
    api.POST('/api/admin/users/{user_id}/uploads', {
      params: { path: { user_id: userId } },
      body: { paused },
    }),
  );
  patchUsers(qc, [res.user]);
  void qc.invalidateQueries({ queryKey: qk.uploadPause });
  void qc.invalidateQueries({ queryKey: qk.pausedUsers });
  return res;
}

// ---------------------------------------------------------- upload controls

export async function setUploadStop(qc: QueryClient, enabled: boolean): Promise<StopState> {
  const res = await call(api.POST('/api/admin/upload-stop', { body: { enabled } }));
  const state: StopState = { enabled: res.enabled, since: res.since, by: res.by };
  qc.setQueryData(qk.uploadStop, state);
  return state;
}

export async function setNewGuestPause(
  qc: QueryClient,
  enabled: boolean,
  restore?: boolean,
): Promise<PauseResponse> {
  const res = await call(
    api.POST('/api/admin/upload-pause', {
      body: restore === undefined ? { enabled } : { enabled, restore },
    }),
  );
  const state: PauseState = {
    enabled: res.enabled,
    since: res.since,
    period: res.period,
    by: res.by,
    affected: res.affected,
    paused_total: res.paused_total,
  };
  qc.setQueryData(qk.uploadPause, state);
  for (const key of [qk.pausedUsers, qk.userLists, qk.userDetails]) {
    void qc.invalidateQueries({ queryKey: key });
  }
  return res;
}

// ------------------------------------------------------------------ session

export async function login(password: string): Promise<void> {
  await call(api.POST('/api/admin/login', { body: { password } }));
}

export async function logout(): Promise<void> {
  try {
    await api.POST('/api/admin/logout');
  } finally {
    location.assign('/admin/login');
  }
}

// ------------------------------------- Instagram board (contracts/api.md §6)

export async function setHandleDone(qc: QueryClient, handle: string, done: boolean): Promise<void> {
  const patch = (value: boolean) =>
    patchQueries<InstagramHandle[]>(qc, qk.instagram, (list) =>
      list.map((h) => (h.handle === handle && h.done !== value ? { ...h, done: value } : h)),
    );
  patch(done);
  try {
    await call(
      api.POST('/api/admin/instagram/{handle}/done', { params: { path: { handle } }, body: { done } }),
    );
  } catch (err) {
    patch(!done);
    throw err;
  }
}

export function handleZipUrl(handle: string): string {
  return `/api/admin/instagram/${encodeURIComponent(handle)}/photos.zip`;
}

// ------------------------------------------------ exports (contracts/api.md §6)

/**
 * Start an export job. `created: false`: one of that kind is already queued or
 * running, and that job comes back instead (contracts/api.md §6.1).
 */
export async function startExport(
  qc: QueryClient,
  request: ExportRequest,
): Promise<{ job: ExportJob; created: boolean }> {
  const res = await call(api.POST('/api/admin/exports', { body: request }));
  upsertExportJob(qc, res.job);
  return { job: res.job, created: res.created };
}

export async function deleteExport(qc: QueryClient, id: string): Promise<void> {
  await call(api.DELETE('/api/admin/exports/{job_id}', { params: { path: { job_id: id } } }));
  removeExportJob(qc, id);
}
