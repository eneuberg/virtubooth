/**
 * Pure helpers that patch the admin query cache. They never mutate: each returns a new
 * object, or the SAME object when nothing changed (so callers can skip the write).
 * All of them are idempotent: an event replayed by the server changes nothing twice.
 */
import type { InfiniteData, QueryClient, QueryKey } from '@tanstack/react-query';
import type { AdminPhoto, AdminUser, AdminUsersResponse, PhotoUser, UserDetail } from '@/api/types';
import type { PhotoFilter, PhotoPage } from './types';

export type PhotoPages = InfiniteData<PhotoPage, string | null>;
export type UserPages = InfiniteData<AdminUsersResponse, number>;

// ------------------------------------------------------------------ photos

export function photoMatches(photo: AdminPhoto, filter: PhotoFilter): boolean {
  if (filter.ext && photo.extension !== filter.ext) return false;
  if (filter.user !== null && photo.user.id !== filter.user) return false;
  if (filter.status === 'hidden' && !photo.hidden) return false;
  if (filter.status === 'visible' && photo.hidden) return false;
  return true;
}

/** Newest first, like the server: ISO-8601 UTC strings compare in time order. */
export function newestFirst(a: AdminPhoto, b: AdminPhoto): number {
  if (a.created_at === b.created_at) return a.id < b.id ? 1 : -1;
  return a.created_at < b.created_at ? 1 : -1;
}

/** A sorted copy (toSorted needs Firefox 115; the build targets 114). */
function sortedNewestFirst(list: ReadonlyArray<AdminPhoto>): AdminPhoto[] {
  const copy = [...list];
  // oxlint-disable-next-line unicorn/no-array-sort -- sorts a fresh copy
  copy.sort(newestFirst);
  return copy;
}

export function listedPhotos(data: PhotoPages | undefined): AdminPhoto[] {
  return data ? data.pages.flatMap((p) => p.photos) : [];
}

export function incomingPhotos(data: PhotoPages | undefined): AdminPhoto[] {
  return data?.pages[0]?.incoming ?? [];
}

function hasPhoto(data: PhotoPages, id: string): boolean {
  return data.pages.some((p) => p.photos.some((x) => x.id === id) || p.incoming?.some((x) => x.id === id));
}

function replaceIn(list: AdminPhoto[], photo: AdminPhoto): AdminPhoto[] {
  let changed = false;
  const next = list.map((p) => {
    if (p.id !== photo.id || p === photo) return p;
    changed = true;
    return photo;
  });
  return changed ? next : list;
}

/** Replace a photo wherever the list has it (pages and incoming). */
export function replacePhoto(data: PhotoPages, photo: AdminPhoto): PhotoPages {
  if (!hasPhoto(data, photo.id)) return data;
  return {
    ...data,
    pages: data.pages.map((page) => {
      const photos = replaceIn(page.photos, photo);
      const incoming = page.incoming ? replaceIn(page.incoming, photo) : page.incoming;
      return photos === page.photos && incoming === page.incoming ? page : { ...page, photos, incoming };
    }),
  };
}

/**
 * Remove a deleted photo. `total` (first page) drops by one when the photo was in the
 * list or, beyond the loaded pages, matches the filter. Counted once per id: the API
 * answer and the event both report a deletion.
 */
export function removePhoto(
  data: PhotoPages,
  id: string,
  photo: AdminPhoto | null,
  filter: PhotoFilter,
): PhotoPages {
  const listed = data.pages.some((p) => p.photos.some((x) => x.id === id));
  const queued = data.pages.some((p) => p.incoming?.some((x) => x.id === id));
  const beyond = !listed && !queued && photo !== null && photoMatches(photo, filter);
  if (!listed && !queued && !beyond) return data;
  // beyond the loaded pages: only the count changes, and only if nothing follows that
  // could still bring it (an exhausted list knows it does not have it)
  const lastPage = data.pages.at(-1);
  if (beyond && lastPage && lastPage.next === null) return data;
  return {
    ...data,
    pages: data.pages.map((page, i) => {
      const photos = listed ? page.photos.filter((x) => x.id !== id) : page.photos;
      const incoming = queued && page.incoming ? page.incoming.filter((x) => x.id !== id) : page.incoming;
      const total =
        i === 0 && typeof page.total === 'number' && (listed || beyond)
          ? Math.max(0, page.total - 1)
          : page.total;
      return { ...page, photos, incoming, total };
    }),
  };
}

/** A photo from the stream: queue it on the first page unless the list already has it. */
export function addIncoming(data: PhotoPages, photo: AdminPhoto, filter: PhotoFilter): PhotoPages {
  if (!photoMatches(photo, filter) || hasPhoto(data, photo.id)) return data;
  const [first, ...rest] = data.pages;
  if (!first) return data;
  const incoming = sortedNewestFirst([photo, ...(first.incoming ?? [])]);
  return { ...data, pages: [{ ...first, incoming }, ...rest] };
}

/** Show the queued photos: on top of the first page, counted in `total`. */
export function mergeIncoming(data: PhotoPages): PhotoPages {
  const [first, ...rest] = data.pages;
  if (!first?.incoming?.length) return data;
  const known = new Set(first.photos.map((p) => p.id));
  const fresh = first.incoming.filter((p) => !known.has(p.id));
  const photos = sortedNewestFirst([...fresh, ...first.photos]);
  const total = typeof first.total === 'number' ? first.total + fresh.length : first.total;
  return { ...data, pages: [{ ...first, photos, incoming: [], total }, ...rest] };
}

function photoUser(user: AdminUser): PhotoUser {
  return {
    id: user.id,
    name: user.name,
    instagram: user.instagram,
    banned: user.banned,
    auto_banned: user.auto_banned,
    uploads_paused: user.uploads_paused,
  };
}

function samePhotoUser(a: PhotoUser, b: PhotoUser): boolean {
  return (
    a.name === b.name &&
    a.instagram === b.instagram &&
    a.banned === b.banned &&
    a.auto_banned === b.auto_banned &&
    a.uploads_paused === b.uploads_paused
  );
}

/** The guest's fields inside each of their photos (paused / banned marks on tiles). */
export function patchPhotoUser(photo: AdminPhoto, users: ReadonlyMap<number, AdminUser>): AdminPhoto {
  const user = users.get(photo.user.id);
  if (!user) return photo;
  const next = photoUser(user);
  return samePhotoUser(photo.user, next) ? photo : { ...photo, user: next };
}

export function patchPhotoUsers(data: PhotoPages, users: ReadonlyMap<number, AdminUser>): PhotoPages {
  let changed = false;
  const pages = data.pages.map((page) => {
    const photos = page.photos.map((p) => patchPhotoUser(p, users));
    const incoming = page.incoming?.map((p) => patchPhotoUser(p, users));
    const pageChanged =
      photos.some((p, i) => p !== page.photos[i]) ||
      (incoming ?? []).some((p, i) => p !== page.incoming?.[i]);
    if (!pageChanged) return page;
    changed = true;
    return { ...page, photos, incoming };
  });
  return changed ? { ...data, pages } : data;
}

// ------------------------------------------------------------------- users

/** Replace guests in the guests table (membership changes come with a refetch). */
export function replaceUsers(data: UserPages, users: ReadonlyMap<number, AdminUser>): UserPages {
  let changed = false;
  const pages = data.pages.map((page) => {
    let pageChanged = false;
    const list = page.users.map((u) => {
      const next = users.get(u.id);
      if (!next || next === u) return u;
      pageChanged = true;
      return next;
    });
    if (!pageChanged) return page;
    changed = true;
    return { ...page, users: list };
  });
  return changed ? { ...data, pages } : data;
}

/** A user page: the guest itself and the photos it lists. */
export function patchUserDetail(
  detail: UserDetail,
  change: {
    user?: AdminUser;
    photo?: AdminPhoto;
    created?: AdminPhoto;
    deletedId?: string;
    photos?: AdminPhoto[];
  },
): UserDetail {
  let next = detail;
  if (change.user && change.user.id === detail.user.id && change.user !== detail.user) {
    next = { ...next, user: change.user };
  }
  if (change.photos) {
    const byId = new Map(change.photos.map((p) => [p.id, p]));
    const photos = next.photos.map((p) => byId.get(p.id) ?? p);
    if (photos.some((p, i) => p !== next.photos[i])) next = { ...next, photos };
  }
  if (change.photo) {
    const photos = replaceIn(next.photos, change.photo);
    if (photos !== next.photos) next = { ...next, photos };
  }
  if (change.created && change.created.user.id === detail.user.id) {
    const created = change.created;
    if (!next.photos.some((p) => p.id === created.id)) {
      next = { ...next, photos: sortedNewestFirst([created, ...next.photos]) };
    }
  }
  if (change.deletedId && next.photos.some((p) => p.id === change.deletedId)) {
    next = { ...next, photos: next.photos.filter((p) => p.id !== change.deletedId) };
  }
  return next;
}

// ------------------------------------------------------------- query-level

/**
 * Apply `update` to every cached query under `queryKey`. A query that is fetching right
 * now would overwrite the patch with older data when its answer lands, so it is
 * re-fetched instead (the new request reads after the change).
 */
export function patchQueries<T>(
  qc: QueryClient,
  queryKey: QueryKey,
  update: (data: T, key: QueryKey) => T,
): void {
  for (const query of qc.getQueryCache().findAll({ queryKey })) {
    // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- every entry under this key has that shape
    const before = query.state.data as T | undefined;
    if (before === undefined) continue;
    const after = update(before, query.queryKey);
    if (after === before) continue;
    qc.setQueryData(query.queryKey, after);
    if (query.state.fetchStatus === 'fetching') {
      void qc.invalidateQueries({ queryKey: query.queryKey, exact: true });
    }
  }
}

/** The filter a photo-list key was built with: ['admin','photos', scope, filter]. */
export function filterOfKey(key: QueryKey): PhotoFilter | null {
  const filter = key[3];
  if (!filter || typeof filter !== 'object') return null;
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- keys are built by qk.photos only
  return filter as PhotoFilter;
}
