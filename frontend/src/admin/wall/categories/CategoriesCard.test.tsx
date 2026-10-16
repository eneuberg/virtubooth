import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { clearToasts, ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { bodyField, json, must, stubApi, testClient, type Route } from '../../testing';
import { categoryItems, valuesOut } from '../fixtures';
import type { CategoryImportResult, CategoryItem } from '../types';
import { CategoriesCard } from './CategoriesCard';

const downloads = vi.hoisted(() => [] as Array<{ name: string; blob: Blob }>);
vi.mock('@/print/names', () => ({
  downloadBlob: (blob: Blob, name: string) => downloads.push({ name, blob }),
}));

const A = '/api/x/wall/admin';

function renderCard(routes: Record<string, Route> = {}, over: (items: CategoryItem[]) => CategoryItem[] = (x) => x) {
  let items = over(categoryItems());
  const requests = stubApi({
    [`GET ${A}/categories`]: () => ({ categories: items }),
    [`GET ${A}/values`]: () => valuesOut,
    [`POST ${A}/categories/preview`]: () => ({ winners: [], matched: 0, reason: 'Noch kein Foto.', explanation: '', locked: null }),
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
        <ToastSlot />
      </UiProvider>
    </QueryClientProvider>,
  );
  return requests;
}

function row(id: string): HTMLElement {
  return must(document.querySelector<HTMLElement>(`[data-category=${id}]`), id);
}

afterEach(() => {
  clearToasts();
  vi.unstubAllGlobals();
  downloads.length = 0;
});

const comment = { text: 'Der Hut von Gast 3 ist unschlagbar.', emoji: '🎩' };

describe('the categories card', () => {
  it('lists the categories with badges, line or explanation, comments and winners', async () => {
    renderCard({}, (items) =>
      items.map((c) =>
        c.id === 'volles_haus'
          ? { ...c, spec: { ...c.spec, line: '' }, winners: c.winners.map((w) => ({ ...w, comment })) }
          : c,
      ),
    );
    await screen.findByTestId('wall-categories');
    expect(row('volles_haus').textContent).toContain('Vorlage');
    expect(row('mein_prost').textContent).not.toContain('Vorlage');
    // an empty line: the generated explanation
    expect(row('volles_haus').textContent).toContain('Höchster Wert bei „Personen“, mindestens 3');
    expect(within(row('coolstes_objekt')).getByTestId('category-ai-badge').textContent).toBe('KI');
    expect(within(row('volles_haus')).queryByTestId('category-ai-badge')).toBeNull();
    expect(row('coolstes_objekt').textContent).toContain('Braucht die Eigenschaft „coolness“.');
    expect(within(row('volles_haus')).getByTestId('wall-category-verdict').textContent).toBe(
      '1. 🎩 Der Hut von Gast 3 ist unschlagbar.',
    );
    expect(within(row('volles_haus')).getAllByRole('img')).toHaveLength(1);
    // the v2 editor edits every category
    for (const id of ['volles_haus', 'coolstes_objekt', 'mein_prost']) {
      expect(within(row(id)).getByTestId('category-edit').hasAttribute('disabled')).toBe(false);
    }
  });

  it('says why the app switched one off, and disables the switch of a locked one', async () => {
    renderCard({}, (items) =>
      items.map((c) =>
        c.id === 'coolstes_objekt'
          ? {
              ...c,
              off_reason: 'ai_off',
              locked: { reason: 'ai_off', property: null, message: 'Externe KI ist aus (Hauptschalter …).' },
            }
          : c.id === 'mein_prost'
            ? { ...c, enabled: false, off_reason: 'property_trashed', off_detail: 'glitzer' }
            : c,
      ),
    );
    await screen.findByTestId('wall-categories');
    const cool = row('coolstes_objekt');
    expect(within(cool).getByTestId('category-lock').textContent).toContain('Externe KI ist aus (Hauptschalter …).');
    expect(within(cool).getByRole('switch', { name: 'Das coolste Objekt zeigen' })).toHaveProperty('disabled', true);
    expect(cool.dataset.locked).toBe('true');
    // no lock any more: the reason stays until the host switches it, the switch works
    const prost = row('mein_prost');
    expect(within(prost).getByTestId('category-auto-off').textContent).toBe(
      'Automatisch aus: Die Eigenschaft „glitzer“ liegt im Papierkorb.',
    );
    expect(within(prost).getByRole('switch', { name: 'Prost! zeigen' })).toHaveProperty('disabled', false);
  });

  it('switches the categories the app switched off back on from the banner (nothing by itself)', async () => {
    const puts: Array<{ id: string; enabled: unknown }> = [];
    const off = (c: CategoryItem): CategoryItem => ({ ...c, enabled: false, off_reason: 'ai_off', locked: null });
    const requests = renderCard(
      {
        [`PUT ${A}/categories/volles_haus`]: async (r: Request) => {
          puts.push({ id: 'volles_haus', enabled: await bodyField(r, 'enabled') });
          return { ...must(categoryItems()[0]), enabled: true };
        },
        [`PUT ${A}/categories/mein_prost`]: async (r: Request) => {
          puts.push({ id: 'mein_prost', enabled: await bodyField(r, 'enabled') });
          return { ...must(categoryItems()[2]), enabled: true };
        },
      },
      // coolstes_objekt is off with a reason but still locked: not offered
      (items) =>
        items.map((c) =>
          c.id === 'coolstes_objekt'
            ? { ...off(c), locked: { reason: 'ai_off', property: null, message: 'Externe KI ist aus.' } }
            : off(c),
        ),
    );
    const banner = await screen.findByTestId('category-comeback');
    expect(banner.textContent).toContain('2 Kategorien wurden automatisch ausgeschaltet');
    expect(banner.textContent).toContain('Volles Haus, Prost!');
    expect(requests.some((r) => r.method === 'PUT')).toBe(false);
    fireEvent.click(within(banner).getByRole('button', { name: '2 Kategorien wieder einschalten' }));
    await waitFor(() => expect(puts).toEqual([{ id: 'volles_haus', enabled: true }, { id: 'mein_prost', enabled: true }]));
  });

  it('moves a category down with ↓', async () => {
    const requests = renderCard();
    await screen.findByTestId('wall-categories');
    fireEvent.click(screen.getByRole('button', { name: 'Volles Haus nach unten' }));
    await waitFor(() => expect(requests.some((r) => r.url.endsWith('/categories/order'))).toBe(true));
    const put = must(requests.find((r) => r.url.endsWith('/categories/order')));
    expect(await bodyField(put, 'ids')).toEqual(['coolstes_objekt', 'volles_haus', 'mein_prost']);
  });

  it('exports all categories, or one, as the server writes the file', async () => {
    const file = { format: 'virtubooth-categories', version: 2, exported_at: 'x', properties: [], categories: [] };
    const requests = renderCard({ [`GET ${A}/categories/export`]: () => file });
    await screen.findByTestId('wall-categories');
    fireEvent.click(screen.getByTestId('category-export'));
    await waitFor(() => expect(downloads).toHaveLength(1));
    expect(downloads[0]?.name).toBe('kategorien.json');
    expect(JSON.parse(await must(downloads[0]).blob.text())).toEqual(file);
    fireEvent.click(screen.getByRole('button', { name: 'Prost! exportieren' }));
    await waitFor(() => expect(downloads).toHaveLength(2));
    expect(downloads[1]?.name).toBe('kategorie-mein_prost.json');
    const urls = requests.filter((r) => r.url.includes('/export')).map((r) => new URL(r.url).search);
    expect(urls).toEqual(['', '?ids=mein_prost']);
  });

  it('imports a file: a known id asks copy or replace, the result in one line', async () => {
    const result: CategoryImportResult = {
      imported: [{ id: 'volles_haus', title: 'Volles Haus', enabled: true, from_id: null, replaced: true }],
      skipped: [{ id: 'kaputt', reason: 'ungültig (Titel)' }],
      properties_created: ['glitzer'],
      prompt_conflicts: [],
      switched_off: [],
      notes: [],
    };
    const requests = renderCard({ [`POST ${A}/categories/import`]: () => result });
    await screen.findByTestId('wall-categories');
    const text = JSON.stringify({
      format: 'virtubooth-categories',
      version: 2,
      properties: [{ name: 'glitzer', prompt: 'p' }],
      categories: [{ id: 'volles_haus', spec: { title: 'Volles Haus' } }, { id: 'kaputt', spec: {} }],
    });
    const input = must(document.querySelector<HTMLInputElement>('input[type=file]'));
    fireEvent.change(input, { target: { files: [new File([text], 'k.json', { type: 'application/json' })] } });
    const dialog = await screen.findByTestId('category-import-confirm');
    expect(dialog.textContent).toContain('„volles_haus“ gibt es schon.');
    fireEvent.click(within(dialog).getByRole('radio', { name: 'Vorhandene ersetzen' }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Importieren' }));
    await waitFor(() => expect(requests.some((r) => r.url.endsWith('/categories/import'))).toBe(true));
    const post = must(requests.find((r) => r.url.endsWith('/categories/import')));
    expect(await bodyField(post, 'on_conflict')).toBe('replace');
    expect(await bodyField(post, 'file')).toMatchObject({ version: 2, categories: [{ id: 'volles_haus' }, { id: 'kaputt' }] });
    expect((await screen.findByTestId('category-import-problems')).textContent).toContain('kaputt: übersprungen, ungültig (Titel)');
    expect(await screen.findByText(/1 importiert \(1 ersetzt\), 1 übersprungen\. Eigenschaft angelegt: glitzer\./)).toBeTruthy();
  });

  it('imports a file without known ids at once; a file that is not one never goes up', async () => {
    const result: CategoryImportResult = {
      imported: [{ id: 'neu', title: 'Neu', enabled: false, from_id: null, replaced: false }],
      skipped: [],
      properties_created: [],
      prompt_conflicts: ['coolness'],
      switched_off: [{ id: 'neu', reason: 'ai_off', detail: null, message: 'Externe KI ist aus.' }],
      notes: [],
    };
    const requests = renderCard({ [`POST ${A}/categories/import`]: () => result });
    await screen.findByTestId('wall-categories');
    const input = must(document.querySelector<HTMLInputElement>('input[type=file]'));
    fireEvent.change(input, { target: { files: [new File(['{"version": 7}'], 'x.json')] } });
    expect(await screen.findByText('Unbekannte Version: erwartet 1 oder 2.')).toBeTruthy();
    expect(requests.some((r) => r.url.endsWith('/import'))).toBe(false);
    const v1 = JSON.stringify({ version: 1, categories: [{ id: 'neu', spec: { title: 'Neu' } }] });
    fireEvent.change(input, { target: { files: [new File([v1], 'v1.json')] } });
    await waitFor(() => expect(requests.some((r) => r.url.endsWith('/import'))).toBe(true));
    const post = must(requests.find((r) => r.url.endsWith('/categories/import')));
    expect(await bodyField(post, 'on_conflict')).toBe('copy');
    expect(screen.queryByTestId('category-import-confirm')).toBeNull();
    expect((await screen.findByTestId('category-import-problems')).textContent).toContain('neu: aus, Externe KI ist aus.');
    expect(await screen.findByText(/Prompt weicht ab, eure bleibt: coolness\. 1 ausgeschaltet\./)).toBeTruthy();
  });

  it('shows a server error of the import in the dialog', async () => {
    renderCard({
      [`POST ${A}/categories/import`]: () => json(400, { error: 'invalid_import', message: 'Höchstens 200 Kategorien pro Datei.' }),
    });
    await screen.findByTestId('wall-categories');
    const text = JSON.stringify({ format: 'virtubooth-categories', version: 2, categories: [{ id: 'mein_prost', spec: {} }] });
    const input = must(document.querySelector<HTMLInputElement>('input[type=file]'));
    fireEvent.change(input, { target: { files: [new File([text], 'k.json')] } });
    const dialog = await screen.findByTestId('category-import-confirm');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Importieren' }));
    expect(await within(dialog).findByText('Höchstens 200 Kategorien pro Datei.')).toBeTruthy();
  });
});
