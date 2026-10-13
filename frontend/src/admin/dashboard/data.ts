/**
 * The dashboard's server state: the join stop („Anmeldung stoppen“), the live overview,
 * and the one-tap switches (join stop and the existing upload stop). The event stream
 * keeps both stops current (`settings.upload_stop`, `settings.join_stop`) and refreshes
 * the overview on relevant events; the overview also polls every 10 s while visible.
 */
import { useQuery, type QueryClient } from '@tanstack/react-query';
import { create } from 'zustand';
import { api, isApiError } from '@/api/client';
import type { Overview, StopState } from '@/api/types';
import { msg } from '@/lib/messages.de';
import { showToast } from '@/ui/Toast';
import { setUploadStop } from '../store/actions';
import { call } from '../store/api';
import { qk } from '../store/keys';

/** How often the overview refreshes while the page is visible (React Query pauses it in the background). */
export const OVERVIEW_POLL_MS = 10_000;

export function fetchJoinStop(): Promise<StopState> {
  return call(api.GET('/api/admin/join-stop'));
}

export function fetchOverview(): Promise<Overview> {
  return call(api.GET('/api/admin/overview'));
}

export function useJoinStop() {
  return useQuery({ queryKey: qk.joinStop, queryFn: fetchJoinStop });
}

export function useOverview() {
  return useQuery({
    queryKey: qk.overview,
    queryFn: fetchOverview,
    refetchInterval: OVERVIEW_POLL_MS,
    staleTime: 0,
  });
}

export async function setJoinStop(qc: QueryClient, enabled: boolean): Promise<StopState> {
  const res = await call(api.POST('/api/admin/join-stop', { body: { enabled } }));
  const state: StopState = { enabled: res.enabled, since: res.since, by: res.by };
  qc.setQueryData(qk.joinStop, state);
  return state;
}

// ------------------------------------------------------- the two switches

export type QuickSwitch = 'uploads' | 'join';

/** Which switch has a request running (shared by the toggles and the status strip). */
export const useSwitchBusy = create<{ busy: QuickSwitch | null }>(() => ({ busy: null }));

/**
 * Flip one switch, no confirmation (it must be instant at a party). The answer goes
 * into the cache at once; a failure shows a toast and leaves the state as it was.
 */
export async function flipSwitch(qc: QueryClient, which: QuickSwitch, enabled: boolean): Promise<void> {
  if (useSwitchBusy.getState().busy !== null) return;
  useSwitchBusy.setState({ busy: which });
  try {
    if (which === 'uploads') await setUploadStop(qc, enabled);
    else await setJoinStop(qc, enabled);
  } catch (err) {
    showToast({ tone: 'error', message: isApiError(err) ? err.message : msg.generic });
  } finally {
    useSwitchBusy.setState({ busy: null });
  }
}
