import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AdminExtension } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { bodyField, json, must, stubApi, testClient, type Route } from '../testing';
import { analysisStatus } from '../wall/fixtures';
import { llmStatus, properties, testResult } from './fixtures';
import { MlSection } from './MlSection';
import type { LlmStatus } from './types';

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

const A = '/api/x/wall/admin';
const SECRET = 'sk-ant-api03-geheim-1234567890';

function renderSection(routes: Record<string, Route> = {}, llm: LlmStatus = llmStatus()) {
  const requests = stubApi({
    'GET /api/admin/extensions': () => ({ extensions: [WALL] }),
    [`GET ${A}/analysis`]: () => analysisStatus,
    [`GET ${A}/llm`]: () => llm,
    [`GET ${A}/llm/properties`]: () => ({ properties: properties() }),
    ...routes,
  });
  const view = render(
    <QueryClientProvider client={testClient()}>
      <UiProvider>
        <MlSection />
      </UiProvider>
    </QueryClientProvider>,
  );
  return { requests, view };
}

describe('ML-Pipeline section', () => {
  it('shows the five cards in order', async () => {
    renderSection();
    expect(await screen.findByRole('heading', { name: 'ML-Pipeline', level: 1 })).toBeTruthy();
    await screen.findByRole('heading', { name: 'Budget', level: 2 });
    const titles = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent);
    expect(titles).toEqual(['Modelle', 'Testbild', 'Claude (KI-Dienst)', 'Eigenschaften', 'Budget']);
  });

  it('lists every model with size, numbers, settings and the freeze note', async () => {
    renderSection();
    const row = await waitFor(() => {
      const el = document.querySelector<HTMLElement>('[data-analyzer=objects]');
      if (!el) throw new Error('no row');
      return el;
    });
    expect(row.textContent).toContain('Erkennt Dinge auf dem Foto');
    expect(within(row).getByTestId('ml-analyzer-size').textContent).toBe('12 MB');
    expect(within(row).getByTestId('ml-analyzer-stats').textContent).toBe(
      'Ø 340 ms · zuletzt 290 ms · 128 Fotos · 2 Fehler',
    );
    expect(within(row).getByRole('textbox', { name: 'Mindest-Sicherheit' })).toHaveProperty('value', '0,35');
    expect(screen.getByTestId('ml-queue').textContent).toBe('Warteschlange: 3 Fotos (ältestes seit 12 s)');
    expect(screen.getByTestId('ml-freeze-note').textContent).toContain(
      'Analysen werden einmal gemacht und danach nicht mehr verändert.',
    );
    expect(screen.queryByRole('button', { name: /neu analysieren/i })).toBeNull();
  });

  it('saves analyzer settings through PUT /analysis/analyzers/{name}', async () => {
    const { requests } = renderSection({ [`PUT ${A}/analysis/analyzers/objects`]: () => analysisStatus });
    const field = await screen.findByRole('textbox', { name: 'Mindest-Sicherheit' });
    fireEvent.change(field, { target: { value: '0,5' } });
    fireEvent.click(
      within(screen.getByTestId('ml-analyzer-settings')).getByRole('button', { name: 'Speichern' }),
    );
    await waitFor(() => expect(requests.some((r) => r.method === 'PUT')).toBe(true));
    const put = requests.find((r) => r.method === 'PUT');
    expect(await bodyField(must(put), 'settings')).toEqual({ score_min: 0.5, max_objects: 50 });
    expect(await bodyField(must(put), 'enabled')).toBe(true);
  });

  it('stores a key, then shows only „gesetzt“ and never the key', async () => {
    // the server's state: GET /llm follows the PUT (the card refetches after saving)
    let llm = llmStatus();
    const { requests } = renderSection({
      [`GET ${A}/llm`]: () => llm,
      [`PUT ${A}/llm/key`]: () => {
        llm = {
          ...llm,
          key: { set: true, set_at: '2026-10-15T20:00:00Z', provider: 'anthropic', valid: true },
        };
        return llm.key;
      },
    });
    expect((await screen.findByTestId('ml-key-state')).textContent).toBe('nicht gesetzt');
    const field = screen.getByLabelText('API-Schlüssel');
    expect(field.getAttribute('type')).toBe('password');
    expect(field).toHaveProperty('value', '');
    fireEvent.change(field, { target: { value: SECRET } });
    fireEvent.click(screen.getByTestId('ml-key-save'));
    await waitFor(() => expect(screen.getByTestId('ml-key-state').textContent).toBe('gesetzt'));
    const put = requests.find((r) => r.method === 'PUT' && r.url.endsWith('/llm/key'));
    expect(await bodyField(must(put), 'key')).toBe(SECRET);
    // the field is gone and nothing of the key is anywhere on the page
    expect(screen.queryByLabelText('API-Schlüssel')).toBeNull();
    expect(document.body.innerHTML).not.toContain(SECRET);
    expect(document.body.innerHTML).not.toContain('geheim');
    expect(screen.getByTestId('ml-key-replace').textContent).toBe('Schlüssel ersetzen');
    expect(screen.getByTestId('ml-key-clear').textContent).toContain('Schlüssel löschen');
    expect(screen.getByTestId('ml-key-test').textContent).toBe('Testen');
    // replacing opens an EMPTY field
    fireEvent.click(screen.getByTestId('ml-key-replace'));
    expect(screen.getByLabelText('Neuer API-Schlüssel')).toHaveProperty('value', '');
  });

  it('shows the budget meter, the table and the stop banner', async () => {
    const base = llmStatus();
    renderSection({}, { ...base, usage: { ...base.usage, blocked: true, reason: 'Tageslimit erreicht.' } });
    expect((await screen.findByTestId('ml-budget-blocked')).textContent).toContain(
      'Budget erreicht – externe KI pausiert',
    );
    expect(screen.getByTestId('ml-meter-party-usd').textContent).toContain('1,25 $ von 5,00 $');
    expect(screen.getByTestId('ml-meter-party-calls').textContent).toContain('ohne Limit');
    const table = screen.getByTestId('ml-usage-table');
    expect(table.textContent).toContain('Eigenschaft „coolness“');
    expect(table.textContent).toContain('Urteil „coolstes_objekt“');
    // the test image can't go to Claude now
    expect(screen.getByRole('checkbox', { name: 'Auch an Claude schicken (kostet)' })).toHaveProperty(
      'disabled',
      true,
    );
  });

  it('lists properties without edit or delete; a new one warns first', async () => {
    renderSection();
    const list = await screen.findByTestId('ml-properties');
    expect(within(list).getByText('coolness')).toBeTruthy();
    expect(within(list).getByText('Archiviert')).toBeTruthy();
    expect(within(list).getByRole('button', { name: 'Wiederherstellen' })).toBeTruthy();
    expect(within(list).queryByRole('button', { name: /bearbeiten|löschen/i })).toBeNull();
    fireEvent.click(screen.getByTestId('ml-property-new'));
    expect((await screen.findByTestId('ml-property-warning')).textContent).toBe(
      'Name und Prompt lassen sich später nicht ändern. Für eine Änderung legst du eine neue Eigenschaft an.',
    );
  });

  it('runs a test image and shows objects, values and durations', async () => {
    const { requests } = renderSection({ [`POST ${A}/test-image`]: () => testResult });
    const input = await waitFor(() => {
      const el = document.querySelector<HTMLInputElement>('input[type=file]');
      if (!el) throw new Error('no input');
      return el;
    });
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'test.jpg', { type: 'image/jpeg' });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByTestId('ml-test-run'));
    const result = await screen.findByTestId('ml-test-result');
    expect(within(result).getByTestId('ml-test-objects').textContent).toContain('Weinglas');
    expect(within(result).getByTestId('ml-test-objects').textContent).toContain('Claude');
    expect(within(result).getByTestId('ml-test-facts').textContent).toContain('brightness');
    expect(within(result).getByTestId('ml-test-durations').textContent).toContain('Gesichter 150 ms');
    expect(within(result).getAllByTestId('analysis-box')).toHaveLength(3);
    const post = requests.find((r) => r.method === 'POST');
    const form = await must(post).formData();
    expect(form.get('analyzers')).toBe('all');
    expect(form.get('external')).toBe('0');
  });

  it('says when the worker is off', async () => {
    renderSection({
      [`POST ${A}/test-image`]: () => json(409, { error: 'worker_off', message: 'Worker aus.' }),
    });
    const input = await waitFor(() => {
      const el = document.querySelector<HTMLInputElement>('input[type=file]');
      if (!el) throw new Error('no input');
      return el;
    });
    fireEvent.change(input, { target: { files: [new File(['x'], 'a.png', { type: 'image/png' })] } });
    fireEvent.click(screen.getByTestId('ml-test-run'));
    expect((await screen.findByTestId('ml-test-error')).textContent).toBe('Die Analyse läuft gerade nicht.');
  });
});
