import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { UiProvider } from '@/ui/UiProvider';
import { bodyField, must, stubApi, testClient, type Route } from '../../testing';
import { llmStatus } from '../../ml/fixtures';
import { categoryItems, valuesOut } from '../fixtures';
import type { CategoryItem } from '../types';
import { CategoriesCard } from './CategoriesCard';

const A = '/api/x/wall/admin';

function renderCard(routes: Record<string, Route> = {}) {
  let items = categoryItems();
  const requests = stubApi({
    [`GET ${A}/categories`]: () => ({ categories: items }),
    [`GET ${A}/values`]: () => valuesOut,
    [`POST ${A}/categories/preview`]: () => ({ winners: [], matched: 0, reason: 'Noch kein Foto.' }),
    [`PUT ${A}/categories/order`]: async (r: Request) => {
      const ids = await bodyField(r, 'ids');
      if (!Array.isArray(ids)) throw new Error('ids');
      const next: CategoryItem[] = [];
      for (const id of ids) {
        const item = must(items.find((c) => c.id === id));
        next.push(Object.assign({}, item, { position: next.length }));
      }
      items = next;
      return { categories: items };
    },
    ...routes,
  });
  render(
    <QueryClientProvider client={testClient()}>
      <UiProvider>
        <CategoriesCard />
      </UiProvider>
    </QueryClientProvider>,
  );
  return requests;
}

function row(id: string): HTMLElement {
  return must(document.querySelector<HTMLElement>(`[data-category=${id}]`), id);
}

describe('the categories card', () => {
  it('lists the categories with preset chip, reason, verdict and winners', async () => {
    renderCard();
    await screen.findByTestId('wall-categories');
    expect(row('volles_haus').textContent).toContain('Vorlage');
    expect(row('mein_prost').textContent).not.toContain('Vorlage');
    expect(row('coolstes_objekt').textContent).toContain('Braucht die Eigenschaft „coolness“.');
    expect(within(row('coolstes_objekt')).getByTestId('wall-category-verdict').textContent).toContain(
      'Der Hut von Gast 3 ist unschlagbar.',
    );
    expect(within(row('volles_haus')).getAllByRole('img')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /analysieren/i })).toBeNull();
  });

  it('marks the AI verdict with the red hint while the external AI is off', async () => {
    const llm = llmStatus({ key: { set: true, set_at: null, provider: 'anthropic', valid: true } });
    llm.config = { ...llm.config, enabled: false };
    renderCard({ [`GET ${A}/llm`]: () => llm });
    await screen.findByTestId('wall-categories');
    fireEvent.click(within(row('coolstes_objekt')).getByTestId('category-edit'));
    const sheet = await screen.findByTestId('category-sheet');
    const verdict = within(sheet).getByTestId('category-verdict');
    const hint = await within(verdict).findByTestId('ml-ai-off-hint');
    expect(hint.textContent).toBe(
      'Externe KI ist aus – unter ‚ML-Pipeline › Externe KI‘ einschalten, um das zu nutzen.',
    );
    // no verdict prompt: no hint
    fireEvent.change(within(sheet).getByTestId('category-verdict-prompt'), { target: { value: '' } });
    await waitFor(() => expect(within(verdict).queryByTestId('ml-ai-off-hint')).toBeNull());
  });

  it('moves a category down with ↓', async () => {
    const requests = renderCard();
    await screen.findByTestId('wall-categories');
    fireEvent.click(screen.getByRole('button', { name: 'Volles Haus nach unten' }));
    await waitFor(() => expect(requests.some((r) => r.url.endsWith('/categories/order'))).toBe(true));
    const put = must(requests.find((r) => r.url.endsWith('/categories/order')));
    expect(await bodyField(put, 'ids')).toEqual(['coolstes_objekt', 'volles_haus', 'mein_prost']);
    await waitFor(() =>
      expect(
        [...document.querySelectorAll('[data-category]')].map((el) => el.getAttribute('data-category')),
      ).toEqual(['coolstes_objekt', 'volles_haus', 'mein_prost']),
    );
  });

  it('edits a spec in the sheet: the label op becomes „enthält eins von“ with two labels', async () => {
    let saved = false;
    const requests = renderCard({
      [`PUT ${A}/categories/mein_prost`]: () => {
        saved = true;
        return must(categoryItems().find((c) => c.id === 'mein_prost'));
      },
    });
    await screen.findByTestId('wall-categories');
    fireEvent.click(within(row('mein_prost')).getByTestId('category-edit'));
    const sheet = await screen.findByTestId('category-sheet');
    expect(within(sheet).getByRole('heading', { name: 'Kategorie bearbeiten' })).toBeTruthy();
    // the stored spec is in the fields
    expect(within(sheet).getByRole('textbox', { name: 'Titel' })).toHaveProperty('value', 'Prost!');
    const label = within(sheet).getByTestId('cond-label');
    expect(within(label).getByRole('combobox')).toHaveProperty('value', 'Weinglas');
    expect(within(sheet).getByTestId('category-selection').textContent).toContain('Anzahl von …');

    // operator → „enthält eins von“, then two labels typed + Enter: a German name maps
    // to the known label, an unknown one is taken as typed (the e2e test picks from the list)
    fireEvent.click(within(within(sheet).getByTestId('cond-op')).getByRole('button'));
    fireEvent.click(await screen.findByRole('option', { name: 'enthält eins von' }));
    const labels = await within(sheet).findByTestId('cond-labels');
    const input = within(labels).getByRole('combobox');
    fireEvent.change(input, { target: { value: 'Hut' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(within(labels).getByRole('list').textContent).toContain('Hut'));
    const again = within(labels).getByRole('combobox');
    fireEvent.change(again, { target: { value: 'Sonnenbrille' } });
    fireEvent.keyDown(again, { key: 'Enter' });
    await waitFor(() => expect(within(labels).getByRole('list').textContent).toContain('sonnenbrille'));

    fireEvent.click(within(sheet).getByTestId('category-save'));
    await waitFor(() => expect(saved).toBe(true));
    const put = must(requests.find((r) => r.method === 'PUT' && r.url.endsWith('/categories/mein_prost')));
    expect(await bodyField(put, 'enabled')).toBe(true);
    expect(await bodyField(put, 'spec')).toMatchObject({
      where: [{ value: 'objects', op: 'contains_any', operand: ['hat', 'sonnenbrille'] }],
      select: { by: 'objects.count:wine glass' },
    });
  });

  it('asks for a preview 400 ms after the last change', async () => {
    const requests = renderCard();
    await screen.findByTestId('wall-categories');
    fireEvent.click(within(row('volles_haus')).getByTestId('category-edit'));
    const sheet = await screen.findByTestId('category-sheet');
    await waitFor(() => expect(requests.filter((r) => r.url.endsWith('/preview'))).toHaveLength(1), {
      timeout: 2000,
    });
    expect((await within(sheet).findByTestId('category-preview-matched')).textContent).toContain(
      'Noch kein Foto.',
    );
  });
});
