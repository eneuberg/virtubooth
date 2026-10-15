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
import type { AnalysisStatus, Analyzer } from '../wall/types';

const MB = 1_000_000;

/** The fixture with some changes to its model state and analyzers. */
function withModels(
  models: Partial<AnalysisStatus['models']>,
  change: (a: Analyzer) => Analyzer = (a) => a,
): AnalysisStatus {
  return {
    ...analysisStatus,
    analyzers: analysisStatus.analyzers.map(change),
    models: { ...analysisStatus.models, ...models },
  };
}

const MISSING = withModels(
  { missing: ['yunet', 'face_landmarker'], missing_mb: 4, can_download: true },
  (a) =>
    a.kind === 'ml'
      ? { ...a, available: false, reason: 'Modell fehlt: yunet. Oben „Modelle herunterladen“ drücken.' }
      : a,
);

const facesSwitch = () =>
  within(must(document.querySelector<HTMLElement>('[data-analyzer=faces]'))).getByRole('switch');

const analyzerRow = (name: string) =>
  waitFor(() => {
    const el = document.querySelector<HTMLElement>(`[data-analyzer=${name}]`);
    if (!el) throw new Error('no row');
    return el;
  });

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

  it('keeps the analyzer fields in their own grid and „Speichern“ in a row below them', async () => {
    renderSection();
    const field = await screen.findByRole('textbox', { name: 'Mindest-Sicherheit' });
    const form = screen.getByTestId('ml-analyzer-settings');
    const fields = must(field.closest('.group')?.parentElement);
    // fields side by side while each gets 11rem, else stacked (never squeezed under a neighbour)
    expect(fields.className).toContain('grid-cols-[repeat(auto-fit,minmax(min(100%,11rem),1fr))]');
    expect(within(fields).getAllByRole('textbox')).toHaveLength(2);
    const save = within(form).getByRole('button', { name: 'Speichern' });
    expect(fields.contains(save)).toBe(false);
    expect(save.parentElement).toBe(form);
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

  it('shows the test image as three object lists, each with its own frames', async () => {
    renderSection({ [`POST ${A}/test-image`]: () => testResult });
    const input = await waitFor(() => {
      const el = document.querySelector<HTMLInputElement>('input[type=file]');
      if (!el) throw new Error('no input');
      return el;
    });
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], 'test.jpg', { type: 'image/jpeg' });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByTestId('ml-test-run'));
    const result = await screen.findByTestId('ml-test-result');
    const tabs = within(result)
      .getAllByRole('tab')
      .map((t) => t.textContent);
    expect(tabs).toEqual(['Lokales Modell1', 'KI (Claude)2', 'Zusammengeführt (für Eigenschaften)2']);
    // merged (default): the wine glass both found, marked; the hat from the AI
    const merged = within(result).getAllByTestId('analysis-object');
    expect(merged.map((o) => o.dataset.sources)).toEqual(['local,claude', 'claude']);
    expect(merged[0]?.textContent).toContain('beide');
    expect(within(result).getByTestId('analysis-object-parts').textContent?.replaceAll('\u00a0', ' ')).toBe(
      'lokal: Weinglas 87 % · Claude: Sektglas 80 %',
    );
    const objectFrames = () =>
      within(result)
        .getAllByTestId('analysis-box')
        .filter((b) => b.dataset.kind === 'object');
    expect(objectFrames().map((b) => b.dataset.both ?? '')).toEqual(['true', '']);
    // the AI's own list: what it said, with provider and model, in its colour
    fireEvent.click(within(result).getByRole('tab', { name: /KI \(Claude\)/ }));
    const ai = await within(result).findByTestId('object-view-ai');
    expect(ai.textContent).toContain('claude-haiku-5-5');
    expect(
      within(ai)
        .getAllByTestId('analysis-object')
        .map((o) => o.textContent),
    ).toEqual([expect.stringContaining('Sektglas'), expect.stringContaining('Hut')]);
    await waitFor(() => expect(objectFrames().map((b) => b.textContent)).toEqual(['Sektglas', 'Hut']));
    expect(objectFrames()[0]?.style.borderColor).toBe('#c084fc');
    // the local model's: one object
    fireEvent.click(within(result).getByRole('tab', { name: /Lokales Modell/ }));
    await waitFor(() => expect(objectFrames().map((b) => b.textContent)).toEqual(['Weinglas']));
    expect(objectFrames()[0]?.style.borderColor).toBe('#38bdf8');
  });

  it('switches the AI detection and the property poll separately, each with its own state', async () => {
    const llm = llmStatus({
      key: { set: true, set_at: null, provider: 'anthropic', valid: true },
      detection: {
        state: 'idle',
        pending: 2,
        done: 4,
        failed: 1,
        last_run_at: null,
        last_error: 'Zeitüberschreitung',
      },
      poller: { state: 'off', last_poll_at: null, next_poll_at: null, last_error: null },
    });
    llm.config = { ...llm.config, poll: false, detect: { local: true, external: true } };
    const { requests } = renderSection({ [`PUT ${A}/llm/config`]: () => llm }, llm);
    const detect = await screen.findByTestId('ml-part-detection');
    const poll = screen.getByTestId('ml-part-poll');
    expect(
      within(detect).getByRole('switch', { name: 'Objekterkennung mit KI (beim Hochladen)' }),
    ).toHaveProperty('checked', true);
    expect(within(poll).getByRole('switch', { name: 'Eigenschaften abfragen' })).toHaveProperty(
      'checked',
      false,
    );
    expect(within(detect).getByTestId('ml-detection-state').textContent).toBe('bereit');
    expect(within(detect).getByTestId('ml-detection-error').textContent).toBe('Zeitüberschreitung');
    expect(within(detect).getByTestId('ml-detection-cost').textContent).toContain('4 Aufrufe');
    expect(within(poll).getByTestId('ml-poll-state').textContent).toBe('aus');
    expect(within(poll).getByTestId('ml-poll-cost').textContent).toContain('8 Aufrufe');
    expect(within(poll).getByTestId('ml-poll-now')).toHaveProperty('disabled', true);

    // poll on, detection off: one PUT with both, the master switch untouched
    fireEvent.click(within(poll).getByRole('switch', { name: 'Eigenschaften abfragen' }));
    fireEvent.click(within(detect).getByRole('switch', { name: 'Objekterkennung mit KI (beim Hochladen)' }));
    fireEvent.click(screen.getByTestId('ml-llm-save'));
    await waitFor(() => expect(requests.some((r) => r.method === 'PUT')).toBe(true));
    const put = must(requests.find((r) => r.method === 'PUT'));
    expect(await bodyField(put, 'poll')).toBe(true);
    expect(await bodyField(put, 'detect')).toEqual({ local: true, external: false });
    expect(await bodyField(put, 'enabled')).toBe(true);
  });

  it('says why a part is off while the master switch is off', async () => {
    const llm = llmStatus({
      detection: { state: 'off', pending: 0, done: 0, failed: 0, last_run_at: null, last_error: null },
    });
    llm.config = { ...llm.config, enabled: false, detect: { local: true, external: true } };
    llm.poller = { ...llm.poller, state: 'off' };
    renderSection({}, llm);
    expect((await screen.findByTestId('ml-detection-state')).textContent).toBe('ausExterne KI ist aus.');
    expect(screen.getByTestId('ml-poll-state').textContent).toBe('ausExterne KI ist aus.');
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

  it('explains missing ML packages instead of offering a download', async () => {
    renderSection({
      [`GET ${A}/analysis`]: () =>
        withModels({ ml: false, missing: ['yunet'], missing_mb: 0.2, can_download: false }),
    });
    const box = await screen.findByTestId('ml-packages-missing');
    expect(box.textContent).toContain('KI-Pakete fehlen');
    expect(box.textContent).toContain('VB_ML');
    expect(box.textContent).toContain('Redeploy');
    expect(screen.queryByRole('button', { name: 'Modelle herunterladen' })).toBeNull();
  });

  it('downloads missing models and shows the progress', async () => {
    let status = MISSING;
    const { requests } = renderSection({
      [`GET ${A}/analysis`]: () => status,
      [`POST ${A}/analysis/models/download`]: () => {
        status = withModels({
          ...MISSING.models,
          can_download: false,
          download: {
            state: 'running',
            current: 'face_landmarker',
            models: ['yunet', 'face_landmarker'],
            done_bytes: 1.5 * MB,
            total_bytes: 4 * MB,
            error: null,
            finished_at: null,
          },
        });
        return status;
      },
    });
    const box = await screen.findByTestId('ml-models-missing');
    expect(box.textContent).toContain('2 Modelle fehlen (4\u00a0MB)');
    // the analyzers say why they don't run, and they stay switchable
    expect(within(await analyzerRow('faces')).getByTestId('ml-analyzer-reason').textContent).toContain(
      'Modell fehlt',
    );
    expect(within(await analyzerRow('faces')).getByText('läuft nicht')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Modelle herunterladen' }));
    expect((await screen.findByTestId('ml-models-progress')).textContent).toBe('2 von 4\u00a0MB');
    expect(screen.getByTestId('ml-models-download').textContent).toContain('Gerade: face_landmarker');
    const posts = requests.filter((r) => r.method === 'POST');
    expect(posts).toHaveLength(1);
    // no body: the server alone decides what is downloaded from where
    expect(await must(posts[0]).text()).toBe('');
  });

  it('shows a failed download with its reason and lets the host try again', async () => {
    renderSection({
      [`GET ${A}/analysis`]: () =>
        withModels({
          ...MISSING.models,
          download: {
            ...MISSING.models.download,
            state: 'failed',
            error: 'Herunterladen fehlgeschlagen (yunet: download failed).',
          },
        }),
    });
    expect((await screen.findByTestId('ml-models-error')).textContent).toContain('fehlgeschlagen');
    expect(screen.getByRole('button', { name: 'Modelle herunterladen' })).toHaveProperty('disabled', false);
  });

  it('switches an analyzer that cannot run off and on again', async () => {
    let status = withModels(MISSING.models, (a) =>
      a.name === 'faces' ? { ...a, available: false, reason: 'Modell fehlt: yunet.' } : a,
    );
    const { requests } = renderSection({
      [`GET ${A}/analysis`]: () => status,
      [`PUT ${A}/analysis/analyzers/faces`]: async (req) => {
        const enabled = (await bodyField(req, 'enabled')) === true;
        status = withModels(status.models, (a) =>
          a.name === 'faces' ? { ...a, enabled, available: false, reason: 'Modell fehlt: yunet.' } : a,
        );
        return status;
      },
    });
    await analyzerRow('faces');
    expect(facesSwitch()).toHaveProperty('checked', true);
    expect(facesSwitch()).toHaveProperty('disabled', false);
    fireEvent.click(facesSwitch());
    await waitFor(() => expect(facesSwitch()).toHaveProperty('checked', false));
    expect(facesSwitch()).toHaveProperty('disabled', false);
    fireEvent.click(facesSwitch());
    await waitFor(() => expect(facesSwitch()).toHaveProperty('checked', true));
    const puts = requests.filter((r) => r.method === 'PUT');
    expect(await Promise.all(puts.map((r) => bodyField(r, 'enabled')))).toEqual([false, true]);
  });
});
