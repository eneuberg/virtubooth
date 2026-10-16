import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AdminExtension } from '@/api/types';
import { NBSP } from '@/lib/format';
import { UiProvider } from '@/ui/UiProvider';
import { applyAdminEvent } from '../store/applyEvent';
import { must, stubApi, testClient, type Route } from '../testing';
import { labelColor } from './labelColors';
import { AnalysisChips, AnalysisTileFrames, AnalysisToggle, AnalysisWins } from './LiveAnalysis';
import { useShowAnalysis } from './liveAnalysisState';
import { analysisChips, chipsLabel } from './summaryText';
import { categoryItems, valuesOut } from './fixtures';
import type { CategoryWin, PhotoAnalysisSummary } from './types';

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
    boxes: [],
    opt_out: { analysis: false, external_ai: false },
    objects_off: false,
    wins: [],
    ...over,
  };
}

type SummaryObject = PhotoAnalysisSummary['objects'][number];
const WIN: CategoryWin = {
  id: 'party',
  emoji: '🎉',
  title: 'Partykanone',
  verdict: false,
  rank: 1,
  headline: '7 Personen',
  detail: null,
  object_label: null,
  comment: null,
};

const obj = (
  label_de: string,
  source = 'local',
  box: SummaryObject['box'] = null,
  score = 0.8,
  label = label_de.toLowerCase(),
): SummaryObject => ({ label, label_de, source, sources: [source], box, score });

/** the chips one tile shows (the area also holds an invisible copy for measuring) */
const chipText = (id: string) =>
  within(screen.getByTestId(`tile-${id}`)).queryByTestId('analysis-chips')?.textContent ?? null;

const texts = (s: PhotoAnalysisSummary) => analysisChips(s).map((c) => c.text);

describe('analysisChips', () => {
  it('names people, smiles, mood, hands, gestures, glasses, hats and objects', () => {
    const s = summary('p', {
      facts: { people: 3, smiles: 2, happy_max: 0.8, hands: 4, thumbs_up: 1, glasses: 1, hats: 2 },
      objects: [
        obj('Person', 'local'),
        obj('Flasche', 'local'),
        obj('Becher', 'local'),
        obj('Flasche', 'claude'),
        obj('Hut', 'claude'),
        obj('Kuchen', 'claude'),
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
      wins: [WIN],
    });
    const chips = analysisChips(s);
    expect(chips[0]).toEqual({ id: 'win-party', text: `🎉${NBSP}Partykanone`, tone: 'win', win: WIN });
  });

  it('says „Objekterkennung aus“ instead of „Nichts erkannt“ when detection was off', () => {
    expect(texts(summary('p', { objects_off: true }))).toEqual(['Objekterkennung aus']);
    expect(texts(summary('p', { objects_off: true, facts: { faces: 2 } }))).toEqual([
      `2${NBSP}Personen`,
      'Objekterkennung aus',
    ]);
  });
});

function renderTiles(
  ids: string[],
  answer: (ids: string[]) => PhotoAnalysisSummary[],
  aspect: Record<string, number> = {},
  routes: Record<string, Route> = {},
  viewer = false,
) {
  const qc = testClient();
  const requests = stubApi({
    'GET /api/admin/extensions': () => ({ extensions: [WALL] }),
    'GET /api/x/wall/admin/photos/analysis': (req) => ({
      items: answer(new URL(req.url).searchParams.getAll('ids')),
    }),
    ...routes,
  });
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <AnalysisToggle />
        {ids.map((id) => (
          <div key={id}>
            <div data-testid={`photo-${id}`} className="relative">
              <AnalysisTileFrames photoId={id} aspect={aspect[id] ?? 3 / 4} />
            </div>
            <div data-testid={`tile-${id}`}>
              <AnalysisChips photoId={id} />
            </div>
            {viewer ? <AnalysisWins photoId={id} /> : null}
          </div>
        ))}
      </UiProvider>
    </QueryClientProvider>,
  );
  const batches = () =>
    requests
      .filter((r) => new URL(r.url).pathname === '/api/x/wall/admin/photos/analysis')
      .map((r) => new URL(r.url).searchParams.getAll('ids'));
  return { qc, batches, requests };
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
    expect(chipText('a')).toBe(`2${NBSP}Personen`);
    expect(chipText('b')).toBe('Analyse wartet');
  });

  it('refreshes exactly the photos a photo.analyzed event names', async () => {
    let done = false;
    const { qc, batches } = renderTiles(['a', 'b'], (ids) =>
      ids.map((id) =>
        id === 'b' && done
          ? summary(id, { objects: [obj('Flasche', 'local')] })
          : summary(id, { state: id === 'b' ? 'running' : 'done', facts: { people: 1 } }),
      ),
    );
    await waitFor(() => expect(chipText('b')).toBe('Analyse läuft…'));
    done = true;
    act(() =>
      applyAdminEvent(
        { type: 'photo.analyzed', id: 'e-1', data: { ids: ['b'] } },
        { qc, invalidate: () => {} },
      ),
    );
    await waitFor(() => expect(chipText('b')).toBe('Flasche'));
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

const frames = (id: string) => within(screen.getByTestId(`photo-${id}`)).queryAllByTestId('tile-frame');

describe('AnalysisTileFrames', () => {
  const bottle = obj('Flasche', 'local', { x: 0.1, y: 0.2, w: 0.5, h: 0.5 }, 0.8, 'bottle');
  const cup = obj('Becher', 'local', { x: 0.7, y: 0.7, w: 0.1, h: 0.1 }, 0.8, 'cup');
  const face = { kind: 'face' as const, x: 0.4, y: 0.1, w: 0.2, h: 0.2 };

  it('draws objects, faces and hands on every tile, labels only the big ones, from the same batch', async () => {
    const { batches } = renderTiles(['a', 'b'], (ids) =>
      ids.map((id) =>
        id === 'a'
          ? summary(id, {
              objects: [bottle, cup, obj('Kuchen', 'claude')],
              boxes: [face, { kind: 'hand', x: 0.05, y: 0.8, w: 0.1, h: 0.1 }],
            })
          : summary(id),
      ),
    );
    await waitFor(() => expect(frames('a')).toHaveLength(4)); // the cake has no box
    expect(frames('b')).toHaveLength(0);
    expect(batches()).toEqual([['a', 'b']]);
    // biggest first; the bottle carries its name, the small cup only its outline
    const [big, ...rest] = frames('a');
    expect(big!.getAttribute('data-kind')).toBe('object');
    expect(big!.textContent).toBe('Flasche');
    expect(big!.style.left).toBe('10.00%');
    expect(big!.style.width).toBe('50.00%');
    expect(rest.map((f) => f.getAttribute('data-kind') ?? '').toSorted((a, b) => a.localeCompare(b))).toEqual(
      ['face', 'hand', 'object'],
    );
    expect(rest.every((f) => f.textContent === '')).toBe(true);
    // no legend: every frame has its thing's colour, the chip names it
    expect(screen.queryByTestId('analysis-legend')).toBeNull();
  });

  it('colours every frame by what it is: the same thing the same colour on every tile', async () => {
    const otherCup = obj('Tasse', 'claude', { x: 0.1, y: 0.1, w: 0.5, h: 0.5 }, 0.8, 'cup');
    renderTiles(['a', 'b'], (ids) =>
      ids.map((id) =>
        id === 'a'
          ? summary(id, { objects: [bottle, cup], boxes: [face] })
          : summary(id, { objects: [otherCup], boxes: [{ ...face, kind: 'hand' }] }),
      ),
    );
    await waitFor(() => expect(frames('b')).toHaveLength(2));
    const colour = (id: string, key: string) =>
      frames(id).find((f) => f.getAttribute('data-key') === key)!.style.borderColor;
    // „Becher“ (local) and „Tasse“ (the AI) are both a cup: one colour
    expect(colour('a', 'cup')).toBe(colour('b', 'cup'));
    const all = [colour('a', 'bottle'), colour('a', 'cup'), colour('a', 'face'), colour('b', 'hand')];
    expect(new Set(all).size).toBe(4);
    // the chip: the frame's colour, its text black or white by contrast
    const chip = frames('b')[0]!.querySelector('span')!;
    expect(chip.textContent).toBe('Tasse');
    expect(chip.style.backgroundColor).toBe(colour('b', 'cup'));
    expect(chip.style.color).toBe(labelColor('cup').text); // black on the cup's yellow
  });

  it('maps the frames onto a cropped thumbnail (a landscape photo in the 3:4 tile)', async () => {
    // 4:3 photo in a 3:4 tile: the picture is 16/9 of the tile wide, centred
    renderTiles(['w'], (ids) => ids.map((id) => summary(id, { objects: [bottle], boxes: [face] })), {
      w: 4 / 3,
    });
    await waitFor(() => expect(frames('w')).toHaveLength(2));
    const geometry = frames('w').map((f) => [f.style.left, f.style.width]);
    // bottle: x 0.1 → -0.389 + 0.1·1.778 = -0.211 (cut at the left edge), right edge 0.678
    // face: x 0.4 → 0.322, w 0.2 → 0.356
    expect(geometry).toEqual([
      ['0.00%', '67.78%'],
      ['32.22%', '35.56%'],
    ]);
  });

  it('follows photo.analyzed and goes away with „Analyse zeigen“', async () => {
    let analysed = false;
    const { qc } = renderTiles(['a'], (ids) =>
      ids.map((id) => (analysed ? summary(id, { objects: [bottle] }) : summary(id, { state: 'running' }))),
    );
    await screen.findByTestId('analysis-chips');
    expect(frames('a')).toHaveLength(0);
    analysed = true;
    act(() =>
      applyAdminEvent(
        { type: 'photo.analyzed', id: 'e-2', data: { ids: ['a'] } },
        { qc, invalidate: () => {} },
      ),
    );
    await waitFor(() => expect(frames('a')).toHaveLength(1));
    fireEvent.click(screen.getByRole('switch', { name: 'Analyse zeigen' }));
    await waitFor(() => expect(frames('a')).toHaveLength(0));
    expect(screen.queryByTestId('analysis-chips')).toBeNull();
    expect(screen.queryByTestId('analysis-legend')).toBeNull();
  });
});

describe('a category the photo wins opens (§8.6)', () => {
  const cool: CategoryWin = {
    id: 'coolstes_objekt',
    emoji: '🏆',
    title: 'Das coolste Objekt',
    verdict: true,
    rank: 2,
    headline: 'Hut',
    detail: '0,80 Coolness',
    object_label: 'Hut',
    comment: { text: 'Der Hut von Otter 3!', emoji: '🎩' },
  };
  const routes = {
    'GET /api/x/wall/admin/categories': () => ({
      categories: categoryItems().map((c) =>
        c.id === 'coolstes_objekt'
          ? Object.assign({}, c, {
              locked: { reason: 'ai_off', property: null, message: 'Externe KI ist aus.' },
            })
          : c,
      ),
    }),
    'GET /api/x/wall/admin/values': () => valuesOut,
  };

  it('from the tile chip: rule, place, object, comment, state and the editor link', async () => {
    const { requests } = renderTiles(
      ['a'],
      (ids) => ids.map((id) => summary(id, { wins: [cool] })),
      {},
      routes,
    );
    const chip = await screen.findByRole('button', { name: 'Das coolste Objekt: Platz 2, aufklappen' });
    // the rule is asked for only once it opens
    expect(requests.some((r) => r.url.endsWith('/categories'))).toBe(false);
    fireEvent.click(chip);
    const details = await screen.findByTestId('category-win-details');
    expect(within(details).getByTestId('category-win-place').textContent).toBe(
      'Dieses FotoPlatz 2 · Hut · 0,80 Coolness',
    );
    expect(within(details).getByTestId('category-win-object').textContent).toBe('ObjektHut');
    expect(within(details).getByTestId('category-win-comment').textContent).toBe(
      `KI-Kommentar🎩${NBSP}Der Hut von Otter 3!`,
    );
    await waitFor(() =>
      expect(within(details).getByTestId('category-win-rank').textContent).toBe(
        'GewinnerHöchster coolness-Wert unter allen Objekten',
      ),
    );
    expect(within(details).getByTestId('category-win-pool').textContent).toBe('FotosAlle Fotos');
    expect(within(details).getByTestId('category-win-select').textContent).toBe('AnzahlEin Gewinner');
    expect(within(details).getByTestId('category-win-state').textContent).toBe(
      'Statusgesperrt: Externe KI ist aus.',
    );
    expect(details.textContent).toContain('Was die KI am coolsten findet');
    expect(within(details).getByRole('link', { name: 'Im Editor öffnen' }).getAttribute('href')).toBe(
      '/manage?tab=livewall&category=coolstes_objekt',
    );
  });

  it('in the viewer: each category opens in place', async () => {
    renderTiles(['a'], (ids) => ids.map((id) => summary(id, { wins: [cool, WIN] })), {}, routes, true);
    const wins = await screen.findByTestId('analysis-wins');
    const rows = within(wins).getAllByTestId('analysis-win');
    expect(rows.map((r) => r.dataset.category)).toEqual(['coolstes_objekt', 'party']);
    const trigger = within(must(rows[0])).getByRole('button');
    expect(trigger.textContent).toContain('Platz 2 · KI-Kommentar');
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(trigger);
    await waitFor(() => expect(trigger.getAttribute('aria-expanded')).toBe('true'));
    const details = within(must(rows[0])).getByTestId('category-win-details');
    await waitFor(() =>
      expect(within(details).getByTestId('category-win-state').textContent).toContain('gesperrt'),
    );
  });
});
