/**
 * The guest's own photos: GET /api/me/photos (not hidden, not deleted, newest
 * first, at most 60).
 */
import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '@/api/client';
import type { GuestPhoto } from '@/api/types';
import { formatFrame } from '@/lib/format';

export const MY_PHOTOS_KEY = ['me', 'photos'] as const;

export function useMyPhotos() {
  return useQuery({
    queryKey: MY_PHOTOS_KEY,
    queryFn: () => unwrap(api.GET('/api/me/photos')),
    select: (data) => data.photos,
    staleTime: 15_000,
    refetchInterval: 60_000,
  });
}

/** "beer-00012.jpg", like the server's download name */
export function photoFileName(photo: GuestPhoto): string {
  return `${photo.extension}-${formatFrame(photo.seq, 5)}.jpg`;
}
