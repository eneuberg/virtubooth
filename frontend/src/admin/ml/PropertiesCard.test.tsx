import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { UiProvider } from '@/ui/UiProvider';
import { bodyField, json, must, stubApi, testClient, type Route } from '../testing';
import { llmStatus, properties } from './fixtures';
import { PropertiesCard } from './PropertiesCard';
import type { LlmProperty } from './types';

const A = '/api/x/wall/admin/llm/properties';

/** The card over a tiny in-memory server: the switch, the Papierkorb, delete for good. */
function renderCard(routes: Record<string, Route> = {}) {
  let list: LlmProperty[] = properties();
  const update = (name: string, change: Partial<LlmProperty>) => {
    list = list.map((p) => (p.name === name ? { ...p, ...change } : p));
    return must(list.find((p) => p.name === name));
  };
  const requests = stubApi({
    [`GET ${A}`]: () => ({ properties: list }),
    [`PUT ${A}/coolness/active`]: async (r) => {
      const active = (await bodyField(r, 'active')) === true;
      return update('coolness', { active, inactive_at: active ? null : '2026-10-16T10:00:00Z' });
    },
    [`POST ${A}/coolness/trash`]: () => update('coolness', { deleted_at: '2026-10-16T10:00:00Z' }),
    [`POST ${A}/old_vibe/restore`]: () => update('old_vibe', { deleted_at: null }),
    [`DELETE ${A}/old_vibe`]: () => {
      list = list.filter((p) => p.name !== 'old_vibe');
      return { properties: list };
    },
    ...routes,
  });
  render(
    <QueryClientProvider client={testClient()}>
      <UiProvider>
        <PropertiesCard status={llmStatus()} />
      </UiProvider>
    </QueryClientProvider>,
  );
  return requests;
}

const row = (name: string) =>
  waitFor(() => must(document.querySelector<HTMLElement>(`[data-property=${name}]`), name));

const openTrash = async () => {
  const trash = await screen.findByTestId('ml-properties-trash');
  fireEvent.click(within(trash).getByRole('button', { name: /Papierkorb/ }));
  return trash;
};

describe('Eigenschaften: the switch „aktiv“ and the Papierkorb', () => {
  it('shows a switch per property and keeps the Papierkorb out of the list, collapsed', async () => {
    renderCard();
    const list = await screen.findByTestId('ml-properties');
    expect(within(list).getByRole('switch', { name: 'coolness aktiv' })).toHaveProperty('checked', true);
    expect(within(list).getByRole('switch', { name: 'most_giraffe aktiv' })).toHaveProperty('checked', false);
    expect(within(list).getByText('Inaktiv')).toBeTruthy();
    expect(within(list).queryByText('old_vibe')).toBeNull();
    expect(within(list).queryByText(/archiv/i)).toBeNull();
    const trash = screen.getByTestId('ml-properties-trash');
    expect(within(trash).getByRole('button', { name: 'Papierkorb (1)' }).getAttribute('aria-expanded')).toBe(
      'false',
    );
  });

  it('switches a property off', async () => {
    const requests = renderCard();
    fireEvent.click(within(await row('coolness')).getByRole('switch'));
    await waitFor(() =>
      expect(
        within(must(document.querySelector<HTMLElement>('[data-property=coolness]'))).getByRole('switch'),
      ).toHaveProperty('checked', false),
    );
    const put = must(requests.find((r) => r.method === 'PUT'));
    expect(new URL(put.url).pathname).toBe(`${A}/coolness/active`);
    expect(await bodyField(put, 'active')).toBe(false);
  });

  it('„Löschen“ moves it into the Papierkorb, „Wiederherstellen“ brings one back', async () => {
    renderCard();
    fireEvent.click(within(await row('coolness')).getByRole('button', { name: 'Löschen' }));
    const trash = await openTrash();
    await waitFor(() => expect(within(trash).getByRole('button', { name: 'Papierkorb (2)' })).toBeTruthy());
    expect(within(screen.getByTestId('ml-properties')).queryByText('coolness')).toBeNull();
    const vibe = must(trash.querySelector<HTMLElement>('[data-property=old_vibe]'));
    fireEvent.click(within(vibe).getByRole('button', { name: 'Wiederherstellen' }));
    await waitFor(() =>
      expect(within(screen.getByTestId('ml-properties')).getByText('old_vibe')).toBeTruthy(),
    );
  });

  it('„Endgültig löschen“ asks first, then deletes', async () => {
    const requests = renderCard();
    const trash = await openTrash();
    const vibe = must(trash.querySelector<HTMLElement>('[data-property=old_vibe]'));
    fireEvent.click(within(vibe).getByRole('button', { name: 'Endgültig löschen' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog.textContent).toContain('„old_vibe“ endgültig löschen?');
    expect(dialog.textContent).toContain('3 Fotos');
    expect(requests.some((r) => r.method === 'DELETE')).toBe(false);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Endgültig löschen' }));
    await waitFor(() => expect(screen.queryByTestId('ml-properties-trash')).toBeNull());
    expect(requests.filter((r) => r.method === 'DELETE')).toHaveLength(1);
  });

  it('shows why deleting for good was refused (a category uses it) and keeps the dialog open', async () => {
    renderCard({
      [`DELETE ${A}/old_vibe`]: () =>
        json(409, {
          error: 'property_in_use',
          message: 'Die Eigenschaft „old_vibe“ wird noch in der Kategorie „Retro“ verwendet.',
        }),
    });
    const trash = await openTrash();
    const vibe = must(trash.querySelector<HTMLElement>('[data-property=old_vibe]'));
    fireEvent.click(within(vibe).getByRole('button', { name: 'Endgültig löschen' }));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Endgültig löschen' }));
    expect((await within(dialog).findByRole('alert')).textContent).toContain('Kategorie „Retro“');
  });
});
