/**
 * The guest's own photos: GET /api/me/photos (not hidden, not deleted, newest
 * first, at most 60).
 *
 * Only while the session is `ready`: a banned device gets 403 there, which the
 * browser logs as an error. So no refetch on window focus either (the session's own
 * focus re-check runs at the same moment and may be the one that finds the ban);
 * instead, every fresh `ready` answer of the session refetches the photos once they
 * are older than STALE_MS. A photo the guest just sent is added at once
 * (useMyPhotosSync), so Start never says "Noch keine Bilder" right after a shot.
 */
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { api, unwrap } from '@/api/client';
import type { GuestPhoto, MyPhotosResponse } from '@/api/types';
import { formatFrame } from '@/lib/format';
import { subscribeOutboxEvents } from '@/sdk/outbox';
import { sessionStore, useSession } from '@/sdk/session';

export const MY_PHOTOS_KEY = ['me', 'photos'] as const;
const STALE_MS = 15_000;
/** the server's page size */
const MAX_PHOTOS = 60;

/** DELETE /api/me/photos/{id}: the guest deletes one of their own photos for good. */
export async function deleteMyPhoto(client: QueryClient, id: string): Promise<void> {
  await unwrap(api.DELETE('/api/me/photos/{public_id}', { params: { path: { public_id: id } } }));
  client.setQueryData<MyPhotosResponse>(MY_PHOTOS_KEY, (old) =>
    old ? { ...old, photos: old.photos.filter((p) => p.id !== id) } : old,
  );
}

export function useMyPhotos() {
  const ready = useSession().status === 'ready';
  const client = useQueryClient();
  useEffect(
    () =>
      sessionStore.subscribe((now, before) => {
        if (now.session === before.session || now.session.status !== 'ready') return;
        const state = client.getQueryState(MY_PHOTOS_KEY);
        if (state && Date.now() - state.dataUpdatedAt > STALE_MS) {
          void client.invalidateQueries({ queryKey: MY_PHOTOS_KEY });
        }
      }),
    [client],
  );
  return useQuery({
    queryKey: MY_PHOTOS_KEY,
    queryFn: () => unwrap(api.GET('/api/me/photos')),
    select: (data) => data.photos,
    enabled: ready,
    staleTime: STALE_MS,
    refetchInterval: 60_000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Every sent photo (the camera page's own upload or a later one from the outbox) goes
 * to the front of the cached list, and the list is marked stale, so Start shows it
 * when the guest comes back without a reload and then refetches the server's truth.
 * Mounted once for the whole guest app: the camera pages don't render the list.
 */
export function useMyPhotosSync(): void {
  const client = useQueryClient();
  useEffect(
    () =>
      subscribeOutboxEvents((e) => {
        if (e.type !== 'sent') return;
        const photo = e.result.photo;
        client.setQueryData<MyPhotosResponse>(MY_PHOTOS_KEY, (data) =>
          data && !data.photos.some((p) => p.id === photo.id)
            ? { ...data, photos: [photo, ...data.photos].slice(0, MAX_PHOTOS) }
            : data,
        );
        void client.invalidateQueries({ queryKey: MY_PHOTOS_KEY });
      }),
    [client],
  );
}

/** "beer-00012.jpg", like the server's download name */
export function photoFileName(photo: GuestPhoto): string {
  return `${photo.extension}-${formatFrame(photo.seq, 5)}.jpg`;
}
