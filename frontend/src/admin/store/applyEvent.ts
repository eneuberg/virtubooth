/**
 * The admin event stream → the query cache. Exact, cheap changes are patched in place
 * (photos, upload switches, export jobs); everything that needs the server's view
 * (counts, lists whose membership changes, the audit log) is invalidated through a
 * throttled invalidator, so a busy party does not trigger a refetch per event.
 */
import type { QueryClient, QueryKey } from '@tanstack/react-query';
import type { AdminEvent } from '@/api/events';
import type {
  AdminPhoto,
  AdminUser,
  ExportJob,
  ExportsResponse,
  InstagramHandle,
  UserDetail,
} from '@/api/types';
import {
  addIncoming,
  filterOfKey,
  patchPhotoUsers,
  patchQueries,
  patchUserDetail,
  removePhoto,
  replacePhoto,
  replaceUsers,
  type PhotoPages,
  type UserPages,
} from './cache';
import { qk } from './keys';
import { ALL_PHOTOS } from './types';

/**
 * Photos that arrived through the stream (not with a page load): their tile plays the
 * "develop" animation once. Keyed by object, so a later change (hidden) doesn't replay it.
 */
export const arrivedLive = new WeakSet<AdminPhoto>();

export interface EventContext {
  qc: QueryClient;
  /** throttled: refetch these (prefix) keys soon */
  invalidate: (keys: ReadonlyArray<QueryKey>) => void;
}

/** A changed photo: every list, the deep-linked photo, the user page. */
export function patchPhoto(qc: QueryClient, photo: AdminPhoto): void {
  patchQueries<PhotoPages>(qc, qk.photoLists, (data) => replacePhoto(data, photo));
  if (qc.getQueryData(qk.photo(photo.id)) !== undefined) qc.setQueryData(qk.photo(photo.id), photo);
  patchQueries<UserDetail>(qc, qk.user(photo.user.id), (d) => patchUserDetail(d, { photo }));
}

/** A deleted photo: out of every list (counted once), the deep link knows it is gone. */
export function dropPhoto(qc: QueryClient, id: string, photo: AdminPhoto | null): void {
  patchQueries<PhotoPages>(qc, qk.photoLists, (data, key) =>
    removePhoto(data, id, photo, filterOfKey(key) ?? ALL_PHOTOS),
  );
  const cached = qc.getQueryData<AdminPhoto>(qk.photo(id));
  if (cached) qc.setQueryData(qk.photo(id), { ...(photo ?? cached), deleted: true });
  patchQueries<UserDetail>(qc, qk.userDetails, (d) => patchUserDetail(d, { deletedId: id }));
}

/** Changed guests: the guests table, their user pages, the marks on their photos. */
export function patchUsers(qc: QueryClient, users: ReadonlyArray<AdminUser>): void {
  if (users.length === 0) return;
  const byId = new Map(users.map((u) => [u.id, u]));
  patchQueries<UserPages>(qc, qk.userLists, (data) => replaceUsers(data, byId));
  patchQueries<PhotoPages>(qc, qk.photoLists, (data) => patchPhotoUsers(data, byId));
  for (const user of users) {
    patchQueries<UserDetail>(qc, qk.user(user.id), (d) => patchUserDetail(d, { user }));
  }
}

export function upsertExportJob(qc: QueryClient, job: ExportJob): void {
  patchQueries<ExportsResponse>(qc, qk.exports, (list) => {
    const i = list.jobs.findIndex((j) => j.id === job.id);
    if (i === -1) return { ...list, jobs: [job, ...list.jobs] };
    const jobs = [...list.jobs];
    jobs[i] = job;
    return { ...list, jobs };
  });
}

export function removeExportJob(qc: QueryClient, id: string): void {
  patchQueries<ExportsResponse>(qc, qk.exports, (list) =>
    list.jobs.some((j) => j.id === id) ? { ...list, jobs: list.jobs.filter((j) => j.id !== id) } : list,
  );
}

export function applyAdminEvent(event: AdminEvent, { qc, invalidate }: EventContext): void {
  switch (event.type) {
    case 'photo.created': {
      const { photo } = event.data;
      arrivedLive.add(photo);
      patchQueries<PhotoPages>(qc, qk.photoLists, (data, key) =>
        addIncoming(data, photo, filterOfKey(key) ?? ALL_PHOTOS),
      );
      patchQueries<UserDetail>(qc, qk.user(photo.user.id), (d) => patchUserDetail(d, { created: photo }));
      invalidate([qk.stats, qk.instagram, qk.userLists, qk.userOptions, qk.audit]);
      return;
    }
    case 'photo.hidden':
    case 'photo.unhidden':
      patchPhoto(qc, event.data.photo);
      invalidate([qk.stats, qk.instagram, qk.audit]);
      return;
    case 'photo.deleted':
      dropPhoto(qc, event.data.id, event.data.photo ?? null);
      invalidate([qk.stats, qk.instagram, qk.userLists, qk.userOptions, qk.audit]);
      return;
    case 'user.created':
      invalidate([qk.userLists, qk.stats, qk.audit, qk.uploadPause, qk.pausedUsers]);
      return;
    case 'user.banned':
    case 'user.unbanned':
      for (const photo of event.data.photos) patchPhoto(qc, photo);
      patchUsers(qc, [event.data.user]);
      patchQueries<UserDetail>(qc, qk.user(event.data.user.id), (d) =>
        patchUserDetail(d, { photos: event.data.photos }),
      );
      // banned flags of peers, membership of the filtered tables, counts
      invalidate([
        qk.userLists,
        qk.userDetails,
        qk.bannedUsers,
        qk.deviceBans,
        qk.instagram,
        qk.stats,
        qk.userOptions,
        qk.audit,
      ]);
      return;
    case 'fingerprint.banned':
    case 'fingerprint.unbanned':
      invalidate([qk.deviceBans, qk.userDetails, qk.bannedUsers, qk.stats, qk.audit]);
      return;
    case 'user.uploads_changed':
      patchUsers(qc, event.data.users);
      invalidate([qk.uploadPause, qk.pausedUsers, qk.userLists, qk.audit]);
      return;
    case 'settings.upload_stop':
      qc.setQueryData(qk.uploadStop, event.data.upload_stop);
      invalidate([qk.audit]);
      return;
    case 'settings.upload_pause':
      qc.setQueryData(qk.uploadPause, event.data.upload_pause);
      invalidate([qk.pausedUsers, qk.userLists, qk.userDetails, qk.audit]);
      return;
    case 'export.updated':
      upsertExportJob(qc, event.data.job);
      // a finished job prunes old ones on the server: refetch the list
      if (event.data.job.status === 'done' || event.data.job.status === 'failed') invalidate([qk.exports]);
      invalidate([qk.audit]);
      return;
    case 'export.deleted':
      removeExportJob(qc, event.data.id);
      invalidate([qk.audit]);
      return;
    case 'instagram.done':
      patchQueries<InstagramHandle[]>(qc, qk.instagram, (list) =>
        list.map((h) =>
          h.handle === event.data.handle && h.done !== event.data.done ? { ...h, done: event.data.done } : h,
        ),
      );
      invalidate([qk.audit]);
      return;
    case 'stream.resync':
      // the server could not replay what we missed: refetch everything we show
      void qc.invalidateQueries({ queryKey: qk.all });
      return;
    default: {
      const unknown: never = event;
      return unknown;
    }
  }
}
