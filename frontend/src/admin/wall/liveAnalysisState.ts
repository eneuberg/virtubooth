/**
 * The Live screen's analysis state: the switch „Analyse zeigen“ (remembered in this
 * browser) and one tile's summary query (batched, refreshed by `photo.analyzed`).
 */
import { useQuery } from '@tanstack/react-query';
import { create } from 'zustand';
import { useWallEnabled } from './hooks';
import { wk } from './keys';
import { loadSummary } from './summaryBatch';

const STORAGE_KEY = 'vb.admin.live.analysis';

function remembered(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'off';
  } catch {
    return true;
  }
}

/** „Analyse zeigen“: on unless this browser switched it off. */
export const useShowAnalysis = create<{ show: boolean; setShow: (show: boolean) => void }>((set) => ({
  show: remembered(),
  setShow: (show) => {
    try {
      localStorage.setItem(STORAGE_KEY, show ? 'on' : 'off');
    } catch {
      // private window: the choice lasts for this page only
    }
    set({ show });
  },
}));

/** Whether the Live screen shows the analysis: the wall is loaded and the switch is on. */
export function useLiveAnalysis(): boolean {
  const enabled = useWallEnabled();
  const show = useShowAnalysis((s) => s.show);
  return enabled === true && show;
}

export function useAnalysisSummary(photoId: string, enabled = true) {
  return useQuery({
    queryKey: wk.photoSummary(photoId),
    queryFn: () => loadSummary(photoId),
    enabled,
    // fresh until the event stream says otherwise (photo.analyzed)
    staleTime: Infinity,
    retry: false,
  });
}
