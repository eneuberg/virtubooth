import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AdminExtension } from '@/api/types';
import { NBSP } from '@/lib/format';
import { UiProvider } from '@/ui/UiProvider';
import { applyAdminEvent } from '../store/applyEvent';
import { stubApi, testClient } from '../testing';
import { AnalysisChips, AnalysisToggle } from './LiveAnalysis';
import { useShowAnalysis } from './liveAnalysisState';
import { analysisChips, chipsLabel } from './summaryText';
import type { PhotoAnalysisSummary } from './types';

const WALL: AdminExtension = {
  id: 'wall',
  title: 'Live-Wall',
  emoji: '📺',
  tagline: '',
  url: null,
  uploads: false,
  meta_labels: {},
  loaded: true,
};

function summary(id: string, over: Partial<PhotoAnalysisSummary> = {}): PhotoAnalysisSummary {
  return {
    photo_id: id,
    state: 'done',
    facts: {},
    objects: [],
    opt_out: { analysis: false, external_ai: false },
    wins: [],
    ...over,
  };
}

const texts = (s: PhotoAnalysisSummary) => analysisChips(s).map((c) => c.text);

describe('analysisChips', () => {
  it('names people, smiles, mood, hands, gestures, glasses, hats and objects', () => {
    const s = summary('p', {
      facts: { people: 3, smiles: 2, happy_max: 0.8, hands: 4, thumbs_up: 1, glasses: 1, hats: 2 },
      objects: [
        { label_de: 'Person', source: 'local' },
        { label_de: 'Flasche', source: 'local' },
        { label_de: 'Becher', source: 'local' },
        { label_de: 'Flasche', source: 'claude' },
        { label_de: 'Hut', source: 'claude' },
        { label_de: 'Kuchen', source: 'claude' },
      ],
    });
    expect(texts(s)).toEqual([
      `3${NBSP}Personen`,
      `2${NBSP}lächeln`,
      'fröhlich',
      `4${NBSP}Hände`,
      'Daumen hoch',
      `1${NBSP}Brille`,
      `2${NBSP}Hüte`,
      'Flasche, Becher, Hut +1',
    ]);
    expect(chipsLabel(analysisChips(s))).toContain('3 Personen, 2 lächeln');
  });

  it('falls back to faces, and says when nothing was found', () => {
    expect(texts(summary('p', { facts: { faces: 1 } }))).toEqual([`1${NBSP}Person`]);
    expect(texts(summary('p'))).toEqual(['Nichts erkannt']);
  });

  it('says the state while there is no result, and the opt-outs always', () => {
    expect(texts(summary('p', { state: 'pending' }))).toEqual(['Analyse wartet']);
    expect(texts(summary('p', { state: 'running' }))).toEqual(['Analyse läuft…']);
    expect(texts(summary('p', { state: 'failed' }))).toEqual(['Analyse fehlgeschlagen']);
    expect(texts(summary('p', { state: 'skipped' }))).toEqual(['Nicht ausgewertet']);
    const optOut = summary('p', { opt_out: { analysis: true, external_ai: true }, facts: { people: 1 } });
    expect(texts(optOut)).toEqual(['Keine Auswertung (Gast)', 'Keine externe KI', `1${NBSP}Person`]);
  });

  it('puts the categories the photo wins first', () => {
    const s = summary('p', {
      facts: { people: 2 },
      wins: [{ id: 'party', emoji: '🎉', title: 'Partykanone', verdict: false }],
    });
    const chips = analysisChips(s);
    expect(chips[0]).toEqual({ id: 'win-party', text: `🎉${NBSP}Partykanone`, tone: 'win' });
  });
});

function renderTiles(ids: string[], answer: (ids: string[]) => PhotoAnalysisSummary[]) {
  const qc = testClient();
  const requests = stubApi({
    'GET /api/admin/extensions': () => ({ extensions: [WALL] }),
    'GET /api/x/wall/admin/photos/analysis': (req) => ({
      items: answer(new URL(req.url).searchParams.getAll('ids')),
    }),
  });
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <AnalysisToggle />
        {ids.map((id) => (
          <div key={id} data-testid={`tile-${id}`}>
            <AnalysisChips photoId={id} />
          </div>
        ))}
      </UiProvider>
    </QueryClientProvider>,
  );
  const batches = () =>
    requests
      .filter((r) => new URL(r.url).pathname === '/api/x/wall/admin/photos/analysis')
      .map((r) => new URL(r.url).searchParams.getAll('ids'));
  return { qc, batches };
}

afterEach(() => {
  vi.unstubAllGlobals();
  act(() => useShowAnalysis.getState().setShow(true));
  localStorage.clear();
});

describe('AnalysisChips', () => {
  it('asks for all tiles in one batch and shows their chips', async () => {
    const { batches } = renderTiles(['a', 'b', 'c'], (ids) =>
      ids.map((id) =>
        id === 'b' ? summary(id, { state: 'pending' }) : summary(id, { facts: { people: 2 } }),
      ),
    );
    await waitFor(() => expect(screen.getAllByTestId('analysis-chips')).toHaveLength(3));
    expect(batches()).toEqual([['a', 'b', 'c']]);
    expect(screen.getByTestId('tile-a').textContent).toBe(`2${NBSP}Personen`);
    expect(screen.getByTestId('tile-b').textContent).toBe('Analyse wartet');
  });

  it('refreshes exactly the photos a photo.analyzed event names', async () => {
    let done = false;
    const { qc, batches } = renderTiles(['a', 'b'], (ids) =>
      ids.map((id) =>
        id === 'b' && done
          ? summary(id, { objects: [{ label_de: 'Flasche', source: 'local' }] })
          : summary(id, { state: id === 'b' ? 'running' : 'done', facts: { people: 1 } }),
      ),
    );
    await waitFor(() => expect(screen.getByTestId('tile-b').textContent).toBe('Analyse läuft…'));
    done = true;
    act(() =>
      applyAdminEvent(
        { type: 'photo.analyzed', id: 'e-1', data: { ids: ['b'] } },
        { qc, invalidate: () => {} },
      ),
    );
    await waitFor(() => expect(screen.getByTestId('tile-b').textContent).toBe('Flasche'));
    expect(batches()).toEqual([['a', 'b'], ['b']]);
  });

  it('„Analyse zeigen“ off hides the chips and is remembered in this browser', async () => {
    const { batches } = renderTiles(['a'], (ids) => ids.map((id) => summary(id, { facts: { people: 1 } })));
    await screen.findByTestId('analysis-chips');
    const toggle = screen.getByRole('switch', { name: 'Analyse zeigen' });
    expect(toggle.getAttribute('aria-checked') ?? String(toggle.matches(':checked'))).toBe('true');
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.queryByTestId('analysis-chips')).toBeNull());
    expect(localStorage.getItem('vb.admin.live.analysis')).toBe('off');
    expect(batches()).toHaveLength(1);
  });
});
