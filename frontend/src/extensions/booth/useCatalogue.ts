/**
 * The Fotobox catalogue (GET /api/x/booth/filters: ids, names, icons, strip order) and
 * the party name for the overlays (GET /api/extensions, the cache the activity menu
 * and Start share). A failed catalogue is fatal (the server only accepts its ids); a
 * failed party name falls back to "Party".
 */
import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '@/api/client';
import type { BoothFilter } from '@/api/types';
import { ACTIVITIES_KEY, fetchActivities } from '@/sdk/activities';

export type CatalogueState =
  | { status: 'loading' }
  | { status: 'ready'; filters: BoothFilter[]; partyName: string }
  | { status: 'error'; error: Error };

/** Shared with Start's Fotobox card (BoothCard.tsx): same key, same data (the whole answer). */
const FILTERS_KEY = ['booth', 'filters'] as const;

export function useCatalogue(): CatalogueState {
  const filters = useQuery({
    queryKey: FILTERS_KEY,
    queryFn: () => unwrap(api.GET('/api/x/booth/filters')),
    staleTime: Infinity,
    select: (data) => data.filters,
  });
  const party = useQuery({
    queryKey: ACTIVITIES_KEY,
    queryFn: fetchActivities,
    staleTime: 5 * 60_000,
    select: (data) => data.party_name,
  });
  if (filters.isError) return { status: 'error', error: filters.error };
  if (!filters.data || party.isPending) return { status: 'loading' };
  return { status: 'ready', filters: filters.data, partyName: party.data ?? 'Party' };
}
