/**
 * The Fotobox catalogue (GET /api/x/booth/filters: ids, names, icons, strip order) and
 * the party name for the overlays (GET /api/extensions). A failed catalogue is fatal
 * (the server only accepts its ids); a failed party name falls back to "Party".
 */
import { useEffect, useState } from 'react';
import { api, unwrap } from '@/api/client';
import type { ApiError } from '@/api/errors';
import type { BoothFilter } from '@/api/types';

export type CatalogueState =
  | { status: 'loading' }
  | { status: 'ready'; filters: BoothFilter[]; partyName: string }
  | { status: 'error'; error: ApiError | Error };

export function useCatalogue(enabled: boolean): CatalogueState {
  const [state, setState] = useState<CatalogueState>({ status: 'loading' });
  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    const party = unwrap(api.GET('/api/extensions'))
      .then((info) => info.party_name)
      .catch(() => 'Party');
    unwrap(api.GET('/api/x/booth/filters'))
      .then(async ({ filters }) => {
        const partyName = await party;
        if (!cancelled) setState({ status: 'ready', filters, partyName });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: 'error', error: error instanceof Error ? error : new Error(String(error)) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return state;
}
