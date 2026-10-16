import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AdminExtension } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { bodyField, json, must, stubApi, testClient, type Route } from '../testing';
import { analysisStatus } from '../wall/fixtures';
import { llmStatus, properties, testResult } from './fixtures';
import { MlSection } from './MlSection';
import { DETECTION_MODES, type LlmStatus } from './types';
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
    expect(titles).toEqual(['Modelle', 'Testbild', 'Externe KI', 'Eigenschaften', 'Budget']);
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
        llm = llmStatus({
          key: { set: true, set_at: '2026-10-15T20:00:00Z', provider: 'anthropic', valid: true },
        });
        return llm.key;
      },
    });
    expect((await screen.findByTestId('ml-key-state')).textContent).toBe('nicht gesetzt');
    expect(screen.getByTestId('ml-key-overview').textContent).toContain('Anthropic: –');
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
    expect(screen.getByTestId('ml-key-overview').textContent).toContain('Anthropic: gesetzt');
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
    expect(screen.getByRole('checkbox', { name: 'Auch an die KI schicken (kostet)' })).toHaveProperty(
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
    // an AI's frame is dashed (who found it); its colour is the thing's, as on Live
    expect(objectFrames()[0]?.dataset.outline).toBe('dashed');
    // the local model's: one object
    fireEvent.click(within(result).getByRole('tab', { name: /Lokales Modell/ }));
    await waitFor(() => expect(objectFrames().map((b) => b.textContent)).toEqual(['Weinglas']));
    // the local model's solid, in the wine glass's colour everywhere (labelColors.ts)
    expect(objectFrames()[0]?.dataset.outline).toBe('solid');
    expect(objectFrames()[0]?.style.borderColor).toBe('#a855f7');
  });

  it('„Erkennung auf“: original or filtered photo, next to the detection choice', async () => {
    const { requests } = renderSection({
      [`PUT ${A}/analysis/image`]: () => ({ ...analysisStatus, image: 'filtered' }),
    });
    const block = await screen.findByTestId('ml-analysis-image-block');
    expect(screen.getByTestId('ml-object-detection-block').contains(block)).toBe(true);
    const choice = within(block).getByTestId('ml-analysis-image');
    expect(within(choice).getByRole('radio', { name: 'Original' })).toHaveProperty('checked', true);
    fireEvent.click(within(choice).getByRole('radio', { name: 'Mit Filter' }));
    await waitFor(() =>
      expect(within(choice).getByRole('radio', { name: 'Mit Filter' })).toHaveProperty('checked', true),
    );
    const put = must(requests.find((r) => r.method === 'PUT'));
    expect(put.url).toContain('/analysis/image');
    expect(await bodyField(put, 'use')).toBe('filtered');
  });

  it('object detection is either/or: one choice over the local and the AI row', async () => {
    const key = { set: true, set_at: null, provider: 'anthropic', valid: true };
    let llm = llmStatus({ key });
    const { requests } = renderSection(
      {
        [`GET ${A}/llm`]: () => llm,
        [`PUT ${A}/llm/object-detection`]: async (req) => {
          const sent = await bodyField(req, 'mode');
          const mode = DETECTION_MODES.find((m) => m === sent) ?? 'off';
          llm = {
            ...llm,
            config: { ...llm.config, detect: { external: mode === 'ai' } },
            detection: { ...llm.detection, mode, state: mode === 'ai' ? 'idle' : 'off' },
          };
          return llm;
        },
      },
      llm,
    );
    const choice = await screen.findByTestId('ml-object-detection');
    const local = await analyzerRow('objects');
    const ai = await analyzerRow('objects-ai');
    // adjacent rows, the local one without its own switch
    expect(local.nextElementSibling).toBe(ai);
    expect(within(local).queryByRole('switch')).toBeNull();
    expect(within(choice).getByRole('radio', { name: 'Lokal' })).toHaveProperty('checked', true);
    expect(within(local).getByTestId('ml-local-detect-active').textContent).toBe('aktiv');
    expect(within(ai).getByTestId('ml-ai-detect-active').textContent).toBe('inaktiv');
    // one framed block: the choice on top, both detectors under it, the inactive greyed out
    const block = screen.getByTestId('ml-object-detection-block');
    expect(block.contains(choice) && block.contains(local) && block.contains(ai)).toBe(true);
    expect(choice.compareDocumentPosition(local) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(local.dataset.inactive).toBeUndefined();
    expect(ai.dataset.inactive).toBe('true');
    expect(ai.querySelector('.opacity-55')).not.toBeNull();
    expect(within(ai).getByTestId('ml-ai-detect-model').textContent).toContain('Anthropic (Claude, USA)');
    expect(within(ai).getByTestId('ml-ai-detect-stats').textContent?.replaceAll('\u00a0', ' ')).toBe(
      'Ø 2.400 ms · zuletzt 1.900 ms · 4 Fotos · 0 Fehler · bisher 0,40 $',
    );
    expect(within(ai).getByTestId('ml-ai-detect-size').textContent).toBe('Größe: –');
    expect(screen.getByTestId('ml-object-detection-block').textContent).toContain(
      'ältere Fotos werden nicht nachträglich geschickt',
    );

    fireEvent.click(within(choice).getByRole('radio', { name: 'KI' }));
    await waitFor(() => expect(within(ai).getByTestId('ml-ai-detect-active').textContent).toBe('aktiv'));
    expect(within(local).getByTestId('ml-local-detect-active').textContent).toBe('inaktiv');
    expect(local.dataset.inactive).toBe('true');
    expect(local.className).toContain('opacity-55');
    expect(ai.dataset.inactive).toBeUndefined();
    expect(within(ai).getByTestId('ml-detection-state').textContent).toBe('bereit');
    const put = must(requests.find((r) => r.method === 'PUT'));
    expect(put.url).toContain('/llm/object-detection');
    expect(await bodyField(put, 'mode')).toBe('ai');
    // no other request switched anything
    expect(requests.filter((r) => r.method === 'PUT')).toHaveLength(1);
  });

  it('shows no fallback line while the AI delivered every photo', async () => {
    const llm = llmStatus();
    renderSection({}, llm);
    const quiet = await analyzerRow('objects-ai');
    expect(within(quiet).queryByTestId('ml-ai-detect-fallback')).toBeNull();
  });

  it('shows „N Fotos lokal statt KI“ with the latest reason and the live hint', async () => {
    const llm = llmStatus();
    llm.config = { ...llm.config, detect: { external: true } };
    llm.detection = {
      ...llm.detection,
      mode: 'ai',
      state: 'blocked',
      fallback: 3,
      fallback_reason: 'Budget aufgebraucht',
      fallback_now: 'Budget aufgebraucht',
    };
    renderSection({}, llm);
    const ai = await analyzerRow('objects-ai');
    expect(within(ai).getByTestId('ml-ai-detect-fallback-count').textContent).toBe(
      '3 Fotos lokal statt KI · zuletzt: Budget aufgebraucht',
    );
    expect(within(ai).getByTestId('ml-ai-detect-fallback-now').textContent).toContain(
      'Gerade erkennt das lokale Modell statt der KI (Budget aufgebraucht)',
    );
  });

  it('keeps the count but drops the live hint once the AI takes photos again (or is not the detector)', async () => {
    const llm = llmStatus();
    llm.detection = {
      ...llm.detection,
      fallback: 1,
      fallback_reason: 'Kein API-Schlüssel',
      fallback_now: 'x',
    };
    renderSection({}, llm);
    const ai = await analyzerRow('objects-ai');
    expect(within(ai).getByTestId('ml-ai-detect-fallback-count').textContent).toBe(
      '1 Foto lokal statt KI · zuletzt: Kein API-Schlüssel',
    );
    // mode „local“: the AI is not the detector, nothing stands in for it now
    expect(within(ai).queryByTestId('ml-ai-detect-fallback-now')).toBeNull();
  });

  it('says up front why „KI“ cannot be chosen (no vision)', async () => {
    const llm = llmStatus();
    llm.config = { ...llm.config, provider: 'deutschlandgpt', model: 'claude-haiku-5.5' };
    llm.detection = {
      ...llm.detection,
      ai_unavailable: 'DeutschlandGPT (Claude, Deutschland) kann keine Fotos ansehen.',
    };
    renderSection({}, llm);
    await screen.findByTestId('ml-object-detection');
    expect(screen.getByTestId('ml-ai-detect-unavailable').textContent).toBe(
      '„KI“ geht gerade nicht: DeutschlandGPT (Claude, Deutschland) kann keine Fotos ansehen.',
    );
    // the Externe-KI card says so too, and that it bills in euros
    const notes = screen.getByTestId('ml-llm-provider-notes').textContent ?? '';
    expect(notes).toContain('nur Eigenschaften, keine Objekterkennung');
    expect(notes).toContain('1 € = 1,10 $');
  });

  it('refuses „KI“ without a key with a red error and stays „Lokal“', async () => {
    const reason = 'Kein API-Schlüssel für Anthropic (Claude, USA) gesetzt.';
    const llm = llmStatus();
    llm.detection = { ...llm.detection, ai_unavailable: reason };
    const { requests } = renderSection(
      {
        [`PUT ${A}/llm/object-detection`]: () =>
          json(409, {
            error: 'ai_detection_unavailable',
            message: `„KI“ geht gerade nicht: ${reason} Die Objekterkennung bleibt beim lokalen Modell.`,
          }),
      },
      llm,
    );
    const choice = await screen.findByTestId('ml-object-detection');
    // before choosing: the reason is already there
    expect(screen.getByTestId('ml-ai-detect-unavailable').textContent).toContain(reason);
    fireEvent.click(within(choice).getByRole('radio', { name: 'KI' }));
    const error = await screen.findByTestId('ml-object-detection-error');
    expect(error.getAttribute('role')).toBe('alert');
    expect(error.className).toContain('text-danger');
    expect(error.textContent).toContain(reason);
    expect(error.textContent).toContain('bleibt beim lokalen Modell');
    // the server's state is shown again: „Lokal“, the local row active
    await waitFor(() =>
      expect(within(choice).getByRole('radio', { name: 'Lokal' })).toHaveProperty('checked', true),
    );
    const local = await analyzerRow('objects');
    expect(within(local).getByTestId('ml-local-detect-active').textContent).toBe('aktiv');
    expect(requests.filter((r) => r.method === 'GET' && r.url.endsWith('/llm')).length).toBeGreaterThan(1);
  });

  it('shows the automatic switch to „Lokal“ with its reason in red', async () => {
    const llm = llmStatus();
    llm.detection = {
      ...llm.detection,
      mode: 'local',
      fallback: 2,
      fallback_reason: 'Budget aufgebraucht',
      notice: 'Budget erreicht: 5,00 $ für die Party.',
      notice_at: '2026-10-16T09:40:00Z',
    };
    renderSection({}, llm);
    const notice = await screen.findByTestId('ml-object-detection-notice');
    expect(notice.textContent).toContain('Automatisch auf „Lokal“ umgestellt');
    expect(notice.textContent).toContain('Budget erreicht: 5,00 $ für die Party.');
    expect(screen.getByTestId('ml-object-detection-block').contains(notice)).toBe(true);
    // the count of photos the local detector took stays
    const ai = await analyzerRow('objects-ai');
    expect(within(ai).getByTestId('ml-ai-detect-fallback-count').textContent).toBe(
      '2 Fotos lokal statt KI · zuletzt: Budget aufgebraucht',
    );
    expect(within(ai).getByTestId('ml-ai-detect-active').textContent).toBe('inaktiv');
  });

  it('keeps the Externe-KI card to switch, provider, model, Denkaufwand and key', async () => {
    const llm = llmStatus({ key: { set: true, set_at: null, provider: 'anthropic', valid: true } });
    const { requests } = renderSection({ [`PUT ${A}/llm/config`]: () => llm }, llm);
    const card = await screen.findByTestId('wall-card-externe-ki');
    expect(within(card).getByRole('heading', { level: 2 }).textContent).toBe('Externe KI');
    // no detection or poll controls here (they live in Modelle and Eigenschaften)
    for (const id of ['ml-detect-external', 'ml-detect-local', 'ml-llm-poll', 'ml-llm-minutes']) {
      expect(within(card).queryByTestId(id)).toBeNull();
    }
    expect(within(card).queryByRole('checkbox')).toBeNull();
    expect(within(card).getByTestId('ml-llm-effort')).toBeTruthy();
    // Mistral has no thinking: no Denkaufwand
    fireEvent.click(within(within(card).getByTestId('ml-llm-provider')).getByRole('button'));
    fireEvent.click(await screen.findByRole('option', { name: 'Mistral AI (EU)' }));
    await waitFor(() => expect(within(card).queryByTestId('ml-llm-effort')).toBeNull());
    fireEvent.click(within(card).getByTestId('ml-llm-enabled'));
    fireEvent.click(screen.getByTestId('ml-llm-save'));
    await waitFor(() => expect(requests.some((r) => r.method === 'PUT')).toBe(true));
    const put = must(requests.find((r) => r.method === 'PUT'));
    expect(JSON.parse(await put.clone().text())).toEqual({
      enabled: false,
      provider: 'mistral',
      model: 'mistral-small-2506',
      effort: 'low',
    });
  });

  it('keeps one key per provider: the picked provider’s key is shown, saved and tested', async () => {
    let llm = llmStatus({ key: { set: true, set_at: null, provider: 'anthropic', valid: true } });
    const { requests } = renderSection(
      {
        [`GET ${A}/llm`]: () => llm,
        [`PUT ${A}/llm/key`]: () => {
          const mistral = { set: true, set_at: null, provider: 'mistral', valid: true };
          llm = { ...llm, keys: llm.keys.map((k) => (k.provider === 'mistral' ? mistral : k)) };
          return mistral;
        },
        [`POST ${A}/llm/key/test`]: () => ({
          ok: false,
          message:
            'Mistral AI (EU): Das Modell „mistral-small-2506“ gibt es bei diesem Anbieter nicht (Schlüssel funktioniert).',
        }),
      },
      llm,
    );
    const card = await screen.findByTestId('wall-card-externe-ki');
    expect(within(card).getByTestId('ml-key-state').textContent).toBe('gesetzt');
    // another provider picked (not saved yet): its own key, none stored
    fireEvent.click(within(within(card).getByTestId('ml-llm-provider')).getByRole('button'));
    fireEvent.click(await screen.findByRole('option', { name: 'Mistral AI (EU)' }));
    await waitFor(() => expect(within(card).getByTestId('ml-key-state').textContent).toBe('nicht gesetzt'));
    expect(within(card).getByTestId('ml-key').textContent).toContain('für Mistral AI');
    expect(within(card).getByTestId('ml-key-overview').textContent).toContain('Anthropic: gesetzt');
    fireEvent.change(within(card).getByLabelText('API-Schlüssel'), { target: { value: 'mistral-key-0123' } });
    fireEvent.click(within(card).getByTestId('ml-key-save'));
    await waitFor(() => expect(within(card).getByTestId('ml-key-state').textContent).toBe('gesetzt'));
    const put = must(requests.find((r) => r.method === 'PUT' && r.url.endsWith('/llm/key')));
    expect(await bodyField(put, 'provider')).toBe('mistral');
    // „Testen“ asks that provider with its model, the answer stays readable in the card
    fireEvent.click(within(card).getByTestId('ml-key-test'));
    const result = await within(card).findByTestId('ml-key-test-result');
    expect(result.textContent).toContain('gibt es bei diesem Anbieter nicht');
    expect(result.className).toContain('text-danger');
    const test = must(requests.find((r) => r.method === 'POST' && r.url.endsWith('/llm/key/test')));
    expect(JSON.parse(await test.clone().text())).toEqual({
      provider: 'mistral',
      model: 'mistral-small-2506',
    });
  });

  it('has the poll in the Eigenschaften card, saved on its own', async () => {
    const llm = llmStatus({
      key: { set: true, set_at: null, provider: 'anthropic', valid: true },
      poller: { state: 'idle', last_poll_at: null, next_poll_at: null, last_error: 'Zeitüberschreitung' },
    });
    const { requests } = renderSection({ [`PUT ${A}/llm/config`]: () => llm }, llm);
    const card = await screen.findByTestId('wall-card-eigenschaften');
    const poll = within(card).getByTestId('ml-part-poll');
    expect(within(poll).getByRole('switch', { name: 'Eigenschaften abfragen' })).toHaveProperty(
      'checked',
      true,
    );
    expect(within(poll).getByTestId('ml-poll-state').textContent).toBe('wartet');
    expect(within(poll).getByTestId('ml-poll-cost').textContent).toContain('8 Aufrufe');
    expect(within(poll).getByTestId('ml-poller-error').textContent).toBe('Zeitüberschreitung');
    expect(within(poll).getByTestId('ml-poll-now')).toHaveProperty('disabled', false);
    expect(within(poll).queryByTestId('ml-ai-off-hint')).toBeNull();
    fireEvent.change(within(poll).getByRole('textbox', { name: 'Abfrage alle … Minuten' }), {
      target: { value: '5' },
    });
    fireEvent.click(within(poll).getByRole('switch', { name: 'Eigenschaften abfragen' }));
    fireEvent.click(within(poll).getByTestId('ml-poll-save'));
    await waitFor(() => expect(requests.some((r) => r.method === 'PUT')).toBe(true));
    const put = must(requests.find((r) => r.method === 'PUT'));
    expect(JSON.parse(await put.clone().text())).toEqual({ poll: false, poll_interval_s: 300 });
  });

  it('shows the red hint at every AI feature while external AI is off', async () => {
    const llm = llmStatus({ key: { set: true, set_at: null, provider: 'anthropic', valid: true } });
    llm.config = { ...llm.config, enabled: false, detect: { external: true } };
    llm.detection = { ...llm.detection, mode: 'ai', state: 'off' };
    llm.poller = { ...llm.poller, state: 'off' };
    renderSection({}, llm);
    const ai = await analyzerRow('objects-ai');
    await waitFor(() => expect(screen.getAllByTestId('ml-ai-off-hint')).toHaveLength(3));
    for (const hint of screen.getAllByTestId('ml-ai-off-hint')) {
      expect(hint.textContent).toBe('Externe KI ist aus – unter ‚Externe KI‘ einschalten, um das zu nutzen.');
      expect(hint.dataset.why).toBe('off');
    }
    expect(within(ai).getByTestId('ml-ai-off-hint')).toBeTruthy();
    expect(within(screen.getByTestId('ml-part-poll')).getByTestId('ml-ai-off-hint')).toBeTruthy();
    expect(within(ai).getByTestId('ml-detection-state').textContent).toBe('ausExterne KI ist aus.');
    expect(screen.getByTestId('ml-poll-state').textContent).toBe('ausExterne KI ist aus.');
    // the link scrolls to the card
    const card = screen.getByTestId('wall-card-externe-ki');
    let scrolled = false;
    card.scrollIntoView = () => {
      scrolled = true;
    };
    fireEvent.click(within(within(ai).getByTestId('ml-ai-off-hint')).getByRole('button'));
    expect(scrolled).toBe(true);
  });

  it('says „kein Schlüssel“ in the hint when the key is missing', async () => {
    renderSection();
    const poll = await screen.findByTestId('ml-part-poll');
    const hint = within(poll).getByTestId('ml-ai-off-hint');
    expect(hint.dataset.why).toBe('key');
    expect(hint.textContent).toContain('Kein gültiger API-Schlüssel');
    // the test image's AI checkbox: disabled, with the same hint
    expect(screen.getByRole('checkbox', { name: 'Auch an die KI schicken (kostet)' })).toHaveProperty(
      'disabled',
      true,
    );
    // local detection active: no hint at the AI row
    expect(within(await analyzerRow('objects-ai')).queryByTestId('ml-ai-off-hint')).toBeNull();
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
