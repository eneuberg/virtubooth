/**
 * The Fotobox catalogue (GET /api/x/booth/filters: ids, names, icons, strip order; only
 * the filters the host has on) and the party name for the overlays (GET /api/extensions,
 * the cache the activity menu and Start share). Both are fetched again while the page is
 * visible: the catalogue every 30 s, the name every minute, so a filter the host switches
 * off leaves the strip (BoothPage then falls back to the first filter) and a renamed event
 * reaches the party frame. A failed catalogue is fatal only while there is none (the
 * server only accepts its ids); a failed refetch keeps the last one. A failed party name
 * falls back to "Party".
 */
import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '@/api/client';
import type { BoothFilter } from '@/api/types';
import { ACTIVITIES_KEY, ACTIVITIES_REFRESH_MS, fetchActivities } from '@/sdk/activities';

export type CatalogueState =
  | { status: 'loading' }
  | { status: 'ready'; filters: BoothFilter[]; partyName: string }
  | { status: 'error'; error: Error };

/** Shared with Start's Fotobox card (BoothCard.tsx): same key, same data (the whole answer). */
export const FILTERS_KEY = ['booth', 'filters'] as const;
/** How often the catalogue is fetched again while the page is visible. */
export const CATALOGUE_REFRESH_MS = 30_000;

export function fetchFilters() {
  return unwrap(api.GET('/api/x/booth/filters'));
}

/** The page's state from the two queries (useCatalogue.test.ts). */
export function catalogueState(
  filters: { data: BoothFilter[] | undefined; error: Error | null },
  party: { data: string | undefined; isPending: boolean },
): CatalogueState {
  if (!filters.data) {
    if (filters.error) return { status: 'error', error: filters.error };
    return { status: 'loading' };
  }
  if (party.isPending) return { status: 'loading' };
  return { status: 'ready', filters: filters.data, partyName: party.data ?? 'Party' };
}

export function useCatalogue(): CatalogueState {
  const filters = useQuery({
    queryKey: FILTERS_KEY,
    queryFn: fetchFilters,
    staleTime: CATALOGUE_REFRESH_MS,
    refetchInterval: CATALOGUE_REFRESH_MS,
    select: (data) => data.filters,
  });
  const party = useQuery({
    queryKey: ACTIVITIES_KEY,
    queryFn: fetchActivities,
    staleTime: 5 * 60_000,
    refetchInterval: ACTIVITIES_REFRESH_MS,
    select: (data) => data.party_name,
  });
  return catalogueState(filters, party);
}
