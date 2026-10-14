/**
 * Live Wall admin queries. No admin events for the wall (D11): the config refetches on
 * focus, the analysis status polls every 5 s while its card is on screen, a photo's
 * analysis every 2 s while it waits or runs.
 */
import { useQuery } from '@tanstack/react-query';
import { useExtensions } from '../store/hooks';
import { fetchAnalysisStatus, fetchPhotoAnalysis, fetchWallAdmin, fetchWallCategories } from './api';
import { wk } from './keys';

/** true / false once the extension list is there: is the wall extension loaded here? */
export function useWallEnabled(): boolean | undefined {
  const { data } = useExtensions();
  return data ? data.some((e) => e.id === 'wall' && e.loaded) : undefined;
}

export function useWallAdmin(enabled = true) {
  return useQuery({
    queryKey: wk.config,
    queryFn: fetchWallAdmin,
    enabled,
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  });
}

export function useWallCategories(enabled = true) {
  return useQuery({
    queryKey: wk.categories,
    queryFn: fetchWallCategories,
    enabled,
    staleTime: 0,
    refetchOnWindowFocus: true,
    retry: false,
  });
}

export function useAnalysisStatus(enabled = true) {
  return useQuery({
    queryKey: wk.analysis,
    queryFn: fetchAnalysisStatus,
    enabled,
    staleTime: 0,
    refetchInterval: 5000,
    retry: false,
  });
}

export function usePhotoAnalysis(publicId: string, enabled = true) {
  return useQuery({
    queryKey: wk.photoAnalysis(publicId),
    queryFn: () => fetchPhotoAnalysis(publicId),
    enabled,
    staleTime: 0,
    retry: false,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state === 'pending' || state === 'running' ? 2000 : false;
    },
  });
}
