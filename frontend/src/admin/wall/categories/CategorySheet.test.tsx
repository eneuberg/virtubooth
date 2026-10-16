import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearToasts, ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { bodyField, json, must, stubApi, testClient, type Route } from '../../testing';
import { llmStatus } from '../../ml/fixtures';
import { categoryItems, valuesOut } from '../fixtures';
import type { CategoryItem, CategoryLock } from '../types';
import { CategorySheet } from './CategorySheet';
import { MeasurePicker } from './MeasurePicker';
import { emptyMeasure, type MeasureDraft } from './spec';

const A = '/api/x/wall/admin';
const AI_OFF: CategoryLock = { reason: 'ai_off', property: null, message: 'Externe KI ist aus (Hauptschalter …).' };

const item = (id: string, over: Partial<CategoryItem> = {}): CategoryItem => ({
  ...must(categoryItems().find((c) => c.id === id)),
  ...over,
});

function renderSheet(current: CategoryItem | null, routes: Record<string, Route> = {}) {
  const requests = stubApi({
    [`POST ${A}/categories/preview`]: async (r: Request) => ({
      winners: [],
      matched: 4,
      reason: null,
      explanation: 'Höchster Wert bei „Personen“, mindestens 3',
      spec: await bodyField(r, 'spec'),
      locked: current?.locked ?? null,
    }),
    [`GET ${A}/llm`]: () => llmStatus(),
    ...routes,
  });
  const onOpenChange = vi.fn();
  render(
    <QueryClientProvider client={testClient()}>
      <UiProvider>
        <CategorySheet item={current} values={valuesOut} taken={['volles_haus']} isOpen onOpenChange={onOpenChange} />
        <ToastSlot />
      </UiProvider>
    </QueryClientProvider>,
  );
  return { requests, onOpenChange, sheet: screen.getByTestId('category-sheet') };
}

afterEach(() => {
  clearToasts();
  vi.unstubAllGlobals();
});

const pick = async (scope: HTMLElement, testid: string, option: string) => {
  fireEvent.click(within(within(scope).getByTestId(testid)).getAllByRole('button')[0] as HTMLElement);
  fireEvent.click(await screen.findByRole('option', { name: option }));
};

describe('the category editor', () => {
  it('shows the steps with the stored spec, the measure in plain German', async () => {
    const { sheet } = renderSheet(item('volles_haus'));
    expect(within(sheet).getByRole('textbox', { name: 'Titel' })).toHaveProperty('value', 'Volles Haus');
    for (const step of ['category-head', 'category-pool', 'category-rank', 'category-select', 'category-caption', 'category-verdict']) {
      expect(within(sheet).getByTestId(step)).toBeTruthy();
    }
    expect(within(sheet).getByTestId('category-pool-all').textContent).toBe('Alle Fotos.');
    const rank = within(sheet).getByTestId('category-rank');
    expect(within(rank).getByTestId('measure-sentence').textContent).toBe('Höchster Wert bei „Personen“');
    expect(within(rank).getByTestId('category-threshold-word').textContent).toBe('mindestens');
    expect(within(rank).getByRole('textbox', { name: 'Schwelle (mindestens)' })).toHaveProperty('value', '3');
    // the other direction: „höchstens“
    fireEvent.click(within(rank).getByRole('radio', { name: 'niedrigsten' }));
    expect(within(rank).getByTestId('category-threshold-word').textContent).toBe('höchstens');
    expect(within(rank).getByTestId('measure-sentence').textContent).toBe('Niedrigster Wert bei „Personen“');
    // no AI: no badge, no lock
    expect(within(sheet).queryByTestId('category-needs-ai')).toBeNull();
    expect(within(sheet).queryByTestId('category-locked')).toBeNull();
  });

  it('marks a locked category that needs the external AI; saving it switches it off', async () => {
    const cool = item('coolstes_objekt', { enabled: true, locked: AI_OFF });
    const puts: unknown[] = [];
    const { sheet } = renderSheet(cool, {
      [`PUT ${A}/categories/coolstes_objekt`]: async (r: Request) => {
        const enabled = await bodyField(r, 'enabled');
        puts.push(enabled);
        return enabled ? json(409, { error: 'category_locked', message: 'Diese Kategorie lässt sich gerade nicht einschalten.' }) : { ...cool, enabled: false };
      },
      [`GET ${A}/categories`]: () => ({ categories: categoryItems() }),
    });
    expect(within(sheet).getByTestId('category-needs-ai').textContent).toContain('braucht externe KI');
    expect(within(sheet).getByTestId('category-needs-ai').textContent).toContain('„coolness“');
    const lock = within(sheet).getByTestId('category-locked');
    expect(lock.textContent).toContain('Externe KI ist aus (Hauptschalter …). Speichern geht, aber nur ausgeschaltet.');
    expect(within(lock).getByRole('link', { name: 'Zur Externen KI' })).toBeTruthy();
    fireEvent.click(within(sheet).getByTestId('category-save'));
    await waitFor(() => expect(puts).toEqual([true, false]));
    expect(await screen.findByText(/gespeichert, aber ausgeschaltet/)).toBeTruthy();
  });

  it('picks a property measure without filtering persons out (host decision §8.4)', async () => {
    const { sheet } = renderSheet(item('coolstes_objekt'));
    const by = within(within(sheet).getByTestId('category-rank')).getAllByTestId('category-by')[0] as HTMLElement;
    expect(by.dataset.kind).toBe('objects');
    expect(within(by).getByTestId('measure-field').textContent).toContain('Eigenschaft „coolness“');
    expect(within(by).getByTestId('measure-agg').textContent).toContain('höchster Wert');
    expect(within(within(by).getByTestId('measure-exclude')).queryByRole('list')).toBeNull();
    expect(within(by).getByTestId('measure-sentence').textContent).toBe('Höchster coolness-Wert unter allen Objekten');

    // a new „Eigenschaft …“ pool row: the first property, highest value, nobody excluded
    fireEvent.click(within(sheet).getByTestId('condition-add'));
    fireEvent.click(await screen.findByTestId('condition-add-prop'));
    const row = await within(sheet).findByTestId('condition');
    expect(row.dataset.type).toBe('objects');
    const measure = within(row).getByTestId('cond-measure');
    expect(within(measure).getByTestId('measure-field').textContent).toContain('Eigenschaft „coolness“');
    expect(within(within(measure).getByTestId('measure-exclude')).queryByRole('list')).toBeNull();
  });

  it('creates a category: pool rows of each kind, the caption follows the measure', async () => {
    const posts: unknown[] = [];
    const { sheet } = renderSheet(null, {
      [`POST ${A}/categories`]: async (r: Request) => {
        posts.push(await r.clone().json());
        return { ...item('mein_prost'), id: 'huttraeger', enabled: true };
      },
      [`GET ${A}/categories`]: () => ({ categories: categoryItems() }),
    });
    fireEvent.change(within(sheet).getByRole('textbox', { name: 'Titel' }), { target: { value: 'Hutträger' } });
    expect(within(sheet).getByRole('textbox', { name: 'Kennung' })).toHaveProperty('value', 'huttraeger');
    // „Enthält Objekt …“ Hut
    fireEvent.click(within(sheet).getByTestId('condition-add'));
    fireEvent.click(await screen.findByTestId('condition-add-has'));
    const row = await within(sheet).findByTestId('condition');
    const input = within(within(row).getByTestId('cond-labels')).getByRole('combobox');
    fireEvent.change(input, { target: { value: 'Hut' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(within(row).getByRole('list').textContent).toContain('Hut'));
    // rank by the number of hats: objects, only Hut
    const rank = within(sheet).getByTestId('category-rank');
    const by = within(rank).getAllByTestId('category-by')[0] as HTMLElement;
    fireEvent.click(within(by).getByRole('radio', { name: 'Objekte im Foto' }));
    const only = within(within(by).getByTestId('measure-labels')).getByRole('combobox');
    fireEvent.change(only, { target: { value: 'Hut' } });
    fireEvent.keyDown(only, { key: 'Enter' });
    await waitFor(() => expect(within(by).getByTestId('measure-sentence').textContent).toBe('Die meisten Objekte (nur Hut)'));
    // the caption: still a count, words for one and many; the mini preview as on the wall
    const caption = within(sheet).getByTestId('category-caption');
    fireEvent.change(within(caption).getByRole('textbox', { name: 'Einzahl (1 …)' }), { target: { value: 'Hut' } });
    fireEvent.change(within(caption).getByRole('textbox', { name: 'Mehrzahl (7 …)' }), { target: { value: 'Hüte' } });
    expect(within(caption).getByTestId('caption-preview-headline').textContent).toBe('7 Hüte');
    expect(within(caption).getByTestId('category-show-object')).toBeTruthy();
    fireEvent.click(within(sheet).getByTestId('category-save'));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({
      id: 'huttraeger',
      enabled: true,
      spec: {
        version: 2,
        emoji: '⭐',
        title: 'Hutträger',
        line: '',
        pool: [
          {
            measure: { kind: 'objects', where: { labels: ['hat'], exclude: [], min_confidence: null }, field: null, agg: 'count', k: null, t: null },
            op: 'gte',
            operand: 1,
          },
        ],
        rank: {
          by: { kind: 'objects', where: { labels: ['hat'], exclude: [], min_confidence: null }, field: null, agg: 'count', k: null, t: null },
          order: 'desc',
          threshold: null,
          then_by: [],
        },
        select: { count: 3, one_per_guest: true },
        caption: { value: null, format: 'count', one: 'Hut', many: 'Hüte', show_object: false },
        verdict: null,
      },
    });
  });

  it('suggests the caption from a new measure until the host picks one', async () => {
    const { sheet } = renderSheet(null);
    const rank = within(sheet).getByTestId('category-rank');
    const by = within(rank).getAllByTestId('category-by')[0] as HTMLElement;
    fireEvent.click(within(by).getByRole('radio', { name: 'Objekte im Foto' }));
    await pick(by, 'measure-field', 'Eigenschaft „coolness“');
    const caption = within(sheet).getByTestId('category-caption');
    await waitFor(() => expect(within(caption).getByTestId('category-format').textContent).toContain('Dezimalzahl'));
    expect(within(caption).getByRole('checkbox', { name: /Objekt nennen/ })).toHaveProperty('checked', true);
    expect(within(caption).getByTestId('caption-preview-headline').textContent).toBe('Sonnenbrille');
    expect(within(caption).getByTestId('caption-preview-detail').textContent).toBe('0,93 Coolness');
    expect(within(caption).getByRole('textbox', { name: 'Einheit zur Zahl' })).toHaveProperty('value', 'Coolness');
  });

  it('takes the generated explanation as the line on request', async () => {
    const { sheet } = renderSheet(item('volles_haus', { spec: { ...item('volles_haus').spec, line: '' } }));
    const line = within(sheet).getByRole('textbox', { name: 'Erklärung' });
    await waitFor(() => expect(line.getAttribute('placeholder')).toBe('Höchster Wert bei „Personen“, mindestens 3'));
    fireEvent.click(within(sheet).getByTestId('category-line-suggest'));
    expect(line).toHaveProperty('value', 'Höchster Wert bei „Personen“, mindestens 3');
  });

  it('sets up the AI comments: how many, the default prompt, model, effort and the price', async () => {
    const llm = llmStatus({ key: { set: true, set_at: null, provider: 'anthropic', valid: true } });
    llm.config = { ...llm.config, enabled: false };
    const { sheet } = renderSheet(item('volles_haus'), { [`GET ${A}/llm`]: () => llm });
    const verdict = within(sheet).getByTestId('category-verdict');
    expect(within(verdict).queryByTestId('category-verdict-prompt')).toBeNull();
    fireEvent.click(within(verdict).getByRole('switch'));
    const prompt = await within(verdict).findByTestId('category-verdict-prompt');
    await waitFor(() => expect(prompt.getAttribute('placeholder')).toContain('Kategorie „Volles Haus“'));
    expect(within(verdict).getByRole('textbox', { name: 'Kommentare zu den besten (1 bis 5)' })).toHaveProperty('value', '3');
    expect(within(verdict).getByTestId('verdict-system-prompt').textContent).toContain('cheeky');
    const price = within(verdict).getByTestId('verdict-price');
    expect(price.textContent).toMatch(/0,0014.*pro Kommentar \(Claude Haiku 5\.5\) · aus echten Läufen/);
    await pick(verdict, 'category-verdict-model', 'Claude Sonnet 5.5');
    await pick(verdict, 'category-verdict-effort', 'hoch');
    await waitFor(() => expect(within(verdict).getByTestId('verdict-price').textContent).toContain('Schätzung, noch nicht gemessen'));
    expect(within(verdict).getByTestId('verdict-price').dataset.measured).toBe('false');
    // the external AI is off: the red hint
    expect((await within(verdict).findByTestId('ml-ai-off-hint')).textContent).toContain('Externe KI ist aus');
  });

  it('asks for a preview 400 ms after the last change and says how many photos are in the pool', async () => {
    const { requests, sheet } = renderSheet(item('volles_haus'));
    await waitFor(() => expect(requests.filter((r) => r.url.endsWith('/preview'))).toHaveLength(1), { timeout: 2000 });
    expect((await within(sheet).findByTestId('category-preview-matched')).textContent).toBe('4 Fotos im Pool');
  });
});

describe('MeasurePicker', () => {
  function renderPicker(start: MeasureDraft) {
    let value = start;
    const changes: MeasureDraft[] = [];
    const view = render(
      <UiProvider>
        <MeasurePicker label="Rang" value={value} onChange={(v) => changes.push((value = v))} values={valuesOut} name="rank.by" errors={{}} order="desc" />
      </UiProvider>,
    );
    const rerender = () =>
      view.rerender(
        <UiProvider>
          <MeasurePicker label="Rang" value={value} onChange={(v) => changes.push((value = v))} values={valuesOut} name="rank.by" errors={{}} order="desc" />
        </UiProvider>,
      );
    return { changes, rerender, get: () => value };
  }

  it('switches the source, the field and the building block', async () => {
    const p = renderPicker(emptyMeasure('value', 'people'));
    expect(screen.getByTestId('measure-sentence').textContent).toBe('Höchster Wert bei „Personen“');
    fireEvent.click(screen.getByRole('radio', { name: 'Objekte im Foto' }));
    p.rerender();
    expect(p.get()).toMatchObject({ kind: 'objects', field: '', agg: 'count' });
    expect(screen.getByTestId('measure-sentence').textContent).toBe('Die meisten Objekte');
    expect(screen.queryByTestId('measure-agg')).toBeNull();
    await pick(document.body, 'measure-field', 'Erkennungssicherheit');
    p.rerender();
    expect(p.get()).toMatchObject({ field: 'confidence', agg: 'max' });
    await pick(document.body, 'measure-agg', 'Mittel der besten k');
    p.rerender();
    expect(p.get().agg).toBe('top_k_mean');
    expect(screen.getByRole('textbox', { name: 'k (die besten wie viele?)' })).toHaveProperty('value', '2');
    expect(screen.getByTestId('measure-sentence').textContent).toBe('Höchster Schnitt der besten 2 Erkennungssicherheit-Werte');
    await pick(document.body, 'measure-agg', 'Anzahl mit Wert ≥ t');
    p.rerender();
    expect(screen.getByRole('textbox', { name: 't (Wert ab, 0 bis 1)' })).toHaveProperty('value', '0,5');
    // back to counting: the building block goes
    await pick(document.body, 'measure-field', 'Anzahl der Objekte');
    p.rerender();
    expect(p.get()).toMatchObject({ field: '', agg: 'count' });
  });

  it('lists a property that is not there any more instead of dropping it', () => {
    renderPicker({ ...emptyMeasure('objects'), field: 'prop:weg', agg: 'max' });
    expect(screen.getByTestId('measure-field').textContent).toContain('Eigenschaft „weg“ (fehlt)');
  });
});
