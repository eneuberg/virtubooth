/**
 * The guest's own photos: GET /api/me/photos (not hidden, not deleted, newest
 * first, at most 60).
 *
 * Only while the session is `ready`: a banned device gets 403 there, which the
 * browser logs as an error. So no refetch on window focus either (the session's own
 * focus re-check runs at the same moment and may be the one that finds the ban);
 * instead, every fresh `ready` answer of the session refetches the photos once they
 * are older than STALE_MS.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { api, unwrap } from '@/api/client';
import type { GuestPhoto } from '@/api/types';
import { formatFrame } from '@/lib/format';
import { sessionStore, useSession } from '@/sdk/session';

export const MY_PHOTOS_KEY = ['me', 'photos'] as const;
const STALE_MS = 15_000;

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

/** "beer-00012.jpg", like the server's download name */
export function photoFileName(photo: GuestPhoto): string {
  return `${photo.extension}-${formatFrame(photo.seq, 5)}.jpg`;
}
