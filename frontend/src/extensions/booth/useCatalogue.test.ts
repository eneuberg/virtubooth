import { describe, expect, it } from 'vitest';
import { catalogueState } from './useCatalogue';

const FILTERS = [
  { id: 'normal', name: 'Normal', icon: '✨' },
  { id: 'bw', name: 'Schwarz-Weiß', icon: '🖤' },
];
const party = { data: 'Sommerfest', isPending: false };

describe('catalogueState', () => {
  it('is ready with the filters and the party name', () => {
    expect(catalogueState({ data: FILTERS, error: null }, party)).toEqual({
      status: 'ready',
      filters: FILTERS,
      partyName: 'Sommerfest',
    });
    // a failed party name falls back
    expect(
      catalogueState({ data: FILTERS, error: null }, { data: undefined, isPending: false }),
    ).toMatchObject({
      partyName: 'Party',
    });
  });

  it('is fatal only while there is no catalogue', () => {
    const error = new Error('Keine Verbindung');
    expect(catalogueState({ data: undefined, error }, party)).toEqual({ status: 'error', error });
    // a failed background refetch keeps the catalogue the guest has
    expect(catalogueState({ data: FILTERS, error }, party)).toMatchObject({
      status: 'ready',
      filters: FILTERS,
    });
  });

  it('waits for both', () => {
    expect(catalogueState({ data: undefined, error: null }, party)).toEqual({ status: 'loading' });
    expect(catalogueState({ data: FILTERS, error: null }, { data: undefined, isPending: true })).toEqual({
      status: 'loading',
    });
  });
});
