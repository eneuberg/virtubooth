/**
 * Query hooks of the admin app. Fetchers are in api.ts; the event stream keeps every
 * one of these current (applyEvent.ts), so stale times are long.
 */
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo } from 'react';
import type { AdminExtension } from '@/api/types';
import {
  fetchAudit,
  fetchDeviceBans,
  fetchExports,
  fetchExtensions,
  fetchInstagram,
  fetchPause,
  fetchPhoto,
  fetchPhotos,
  fetchStats,
  fetchStop,
  fetchUser,
  fetchUsers,
  PAGE_SIZE,
} from './api';
import { incomingPhotos, mergeIncoming, type PhotoPages } from './cache';
import { qk, type PhotoScope } from './keys';
import type { GuestFilter, PhotoFilter } from './types';

export function usePhotoList(scope: PhotoScope, filter: PhotoFilter) {
  return useInfiniteQuery({
    queryKey: qk.photos(scope, filter),
    queryFn: ({ pageParam }) => fetchPhotos(filter, pageParam, PAGE_SIZE[scope]),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next,
  });
}

/** Show the photos that arrived through the stream on top of the list. */
export function useMergeIncoming(scope: PhotoScope, filter: PhotoFilter): () => void {
  const qc = useQueryClient();
  return () => {
    qc.setQueryData<PhotoPages>(qk.photos(scope, filter), (data) => (data ? mergeIncoming(data) : data));
  };
}

/**
 * Live: new photos slide in at once while the host is at the top of the page (and as
 * soon as they scroll back up); further down they wait behind the "neue Fotos" pill.
 */
export function useAutoMerge(scope: PhotoScope, filter: PhotoFilter, isAtTop: () => boolean): void {
  const qc = useQueryClient();
  const key = JSON.stringify(qk.photos(scope, filter));
  useEffect(() => {
    const queryKey = qk.photos(scope, filter);
    const check = () => {
      if (!isAtTop()) return;
      const data = qc.getQueryData<PhotoPages>(queryKey);
      if (incomingPhotos(data).length > 0)
        qc.setQueryData<PhotoPages>(queryKey, (d) => (d ? mergeIncoming(d) : d));
    };
    check();
    const unsubscribe = qc.getQueryCache().subscribe((e) => {
      if (e.type === 'updated' && JSON.stringify(e.query.queryKey) === key) check();
    });
    window.addEventListener('scroll', check, { passive: true });
    return () => {
      unsubscribe();
      window.removeEventListener('scroll', check);
    };
    // scope/filter are covered by `key`
    // oxlint-disable-next-line react/exhaustive-deps
  }, [qc, key, isAtTop]);
}

export function usePhoto(id: string | null) {
  return useQuery({
    queryKey: qk.photo(id ?? ''),
    queryFn: () => fetchPhoto(id ?? ''),
    enabled: Boolean(id),
    retry: false,
  });
}

export function useStats() {
  return useQuery({ queryKey: qk.stats, queryFn: fetchStats, refetchInterval: 60_000 });
}

export function useExtensions() {
  return useQuery({ queryKey: qk.extensions, queryFn: fetchExtensions, staleTime: 5 * 60_000 });
}

export function useExtensionMap(): ReadonlyMap<string, AdminExtension> {
  const { data } = useExtensions();
  return useMemo(() => new Map((data ?? []).map((e) => [e.id, e])), [data]);
}

export function useUploadStop() {
  return useQuery({ queryKey: qk.uploadStop, queryFn: fetchStop });
}

export function useUploadPause() {
  return useQuery({ queryKey: qk.uploadPause, queryFn: fetchPause });
}

export function useGuestList(filter: GuestFilter) {
  return useInfiniteQuery({
    queryKey: qk.users(filter),
    queryFn: ({ pageParam }) => fetchUsers(filter, pageParam),
    initialPageParam: 0,
    getNextPageParam: (last) => last.next_offset ?? undefined,
  });
}

/** Every guest with photos (plus `keep`), sorted by name: the "Gast" filter. */
export function useUserOptions(enabled: boolean) {
  return useQuery({
    queryKey: qk.userOptions,
    queryFn: async () => (await fetchUsers({ search: '', status: 'all' }, 0, 500)).users,
    enabled,
    staleTime: 30_000,
  });
}

export function usePausedUsers(enabled: boolean) {
  return useQuery({
    queryKey: qk.pausedUsers,
    queryFn: () => fetchUsers({ search: '', status: 'paused' }, 0, 50),
    enabled,
  });
}

export function useUserDetail(id: number | null) {
  return useQuery({
    queryKey: qk.user(id ?? 0),
    queryFn: () => fetchUser(id ?? 0),
    enabled: id !== null,
    retry: false,
  });
}

export function useBannedUsers() {
  return useQuery({
    queryKey: qk.bannedUsers,
    queryFn: async () => (await fetchUsers({ search: '', status: 'banned' }, 0, 500)).users,
  });
}

export function useDeviceBans() {
  return useQuery({ queryKey: qk.deviceBans, queryFn: fetchDeviceBans });
}

export function useInstagram() {
  return useQuery({ queryKey: qk.instagram, queryFn: fetchInstagram });
}

export function useAudit() {
  return useInfiniteQuery({
    queryKey: qk.audit,
    queryFn: ({ pageParam }) => fetchAudit(pageParam),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next ?? undefined,
  });
}

/** Export jobs; polls every 2 s while one runs (the `export.updated` event is the fast path). */
export function useExports() {
  return useQuery({
    queryKey: qk.exports,
    queryFn: fetchExports,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.jobs.some((j) => j.status === 'queued' || j.status === 'running') ? 2000 : false,
  });
}
