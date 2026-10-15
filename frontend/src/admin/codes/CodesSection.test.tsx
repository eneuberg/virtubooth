import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Router } from 'wouter';
import { memoryLocation } from 'wouter/memory-location';
import type { AdminExtension, AdminSettings, PublicAddress } from '@/api/types';
import { clearToasts, ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { settingsKey } from '../settings/keys';
import { qk } from '../store/keys';
import { bodyField, json, must, stubApi, testClient } from '../testing';
import { CodesSection } from './CodesSection';
import { codesKey } from './keys';
import { code, list } from './testing';

const PRINTED = 'printed-token-0123456789';

function extension(id: string, title: string): AdminExtension {
  return {
    id,
    title,
    emoji: '📸',
    tagline: '',
    loaded: true,
    meta_labels: {},
    uploads: true,
    url: `/x/${id}/`,
  };
}

const AUTO: PublicAddress = {
  address: null,
  effective: 'http://localhost:3000',
  source: 'auto',
  check: { status: 'auto', url: null, at: null, message: '' },
};

function settings(address: PublicAddress): AdminSettings {
  return {
    event: { name: 'Party', default_name: 'Party', custom: false, updated_at: null, by: null },
    password: { source: 'env', changed_at: null },
    public_address: address,
  };
}

function renderSection(
  search = 'tab=qr',
  routes: Parameters<typeof stubApi>[0] = {},
  address: PublicAddress = AUTO,
) {
  const qc = testClient();
  qc.setQueryData(settingsKey, settings(address));
  qc.setQueryData(qk.extensions, [extension('booth', 'Fotobox'), extension('beer', 'Beer Cam')]);
  const codes = list([
    code({ id: 1, stats: { ...code().stats, scans: 12, people: 9, guests: 7, photos: 30 } }),
    code({ id: 2, name: 'Uhu 2', animal: 'Uhu', active: false, revoked_at: '2026-10-13T20:41:00.000Z' }),
    code({ id: 3, name: 'Gnu 3', animal: 'Gnu', target: 'booth', note: 'Bar' }),
  ]);
  const created = code({ id: 4, name: 'Pfau 4', animal: 'Pfau', target: 'booth', token: PRINTED });
  const requests = stubApi({
    'GET /api/admin/codes': () => codes,
    'POST /api/admin/codes': () => json(201, { code: created, changed: true }),
    'POST /api/admin/codes/3/token': async (req) => ({
      code: code({ id: 3, name: 'Gnu 3', token: String(await bodyField(req, 'token')), token_gen: 2 }),
      changed: true,
    }),
    'PATCH /api/admin/codes/3': async (req) => ({
      code: code({ id: 3, name: 'Gnu 3', target: String(await bodyField(req, 'target')) }),
      changed: true,
    }),
    ...routes,
  });
  qc.setQueryData(codesKey, codes);
  const memory = memoryLocation({ path: '/manage', searchPath: search, record: true });
  render(
    <QueryClientProvider client={qc}>
      <Router hook={memory.hook} searchHook={memory.searchHook}>
        <UiProvider>
          <CodesSection />
          <ToastSlot />
        </UiProvider>
      </Router>
    </QueryClientProvider>,
  );
  return { qc, requests, memory };
}

const rows = () => screen.getAllByTestId('code-row');
const sent = (requests: Request[], method: string, path: string) =>
  requests.filter((r) => r.method === method && new URL(r.url).pathname === path);

afterEach(() => {
  vi.unstubAllGlobals();
  clearToasts();
});

describe('CodesSection: the public address', () => {
  const at = new Date().toISOString();
  const set = (check: Partial<PublicAddress['check']>): PublicAddress => ({
    address: 'https://party.example.com',
    effective: 'https://party.example.com',
    source: 'setting',
    check: { status: 'ok', url: 'https://party.example.com', at, message: 'Erreichbar.', ...check },
  });

  it('no warning while automatic or checked OK', () => {
    renderSection();
    expect(screen.queryByTestId('address-warning')).toBeNull();
  });

  it('warns while unreachable and links to Allgemeines', () => {
    const { requests } = renderSection('tab=qr', {}, set({ status: 'unreachable' }));
    const warning = screen.getByTestId('address-warning');
    expect(warning.textContent).toContain(
      'Die öffentliche Adresse ist nicht geprüft oder nicht erreichbar. Prüfe sie unter „Allgemeines“, bevor du druckst.',
    );
    expect(within(warning).getByRole('link', { name: 'Zu „Allgemeines“' }).getAttribute('href')).toContain(
      'tab=allgemein',
    );
    // checked a moment ago: no new check
    expect(sent(requests, 'POST', '/api/admin/settings/public-address/check')).toHaveLength(0);
  });

  it('re-checks a stale check on open and follows the answer', async () => {
    const old = new Date(Date.now() - 11 * 60_000).toISOString();
    const { requests } = renderSection(
      'tab=qr',
      { 'POST /api/admin/settings/public-address/check': () => ({ ...set({}).check }) },
      set({ status: 'unchecked', at: old }),
    );
    expect(screen.getByTestId('address-warning')).toBeTruthy();
    await waitFor(() => expect(screen.queryByTestId('address-warning')).toBeNull());
    expect(sent(requests, 'POST', '/api/admin/settings/public-address/check')).toHaveLength(1);
  });
});

describe('CodesSection', () => {
  it('lists the active codes; revoked ones on request, grey', () => {
    renderSection();
    expect(screen.getByTestId('code-count').textContent).toBe('2 aktiv · 1 gelöscht');
    expect(rows().map((r) => r.dataset['id'])).toEqual(['1', '3']);
    const first = within(must(rows()[0]));
    expect(first.getByText('#1')).toBeTruthy();
    expect(first.getByText('Gorilla 1')).toBeTruthy();
    expect(first.getByText('Start')).toBeTruthy();
    expect(first.getByText('Aktiv')).toBeTruthy();
    expect(within(must(rows()[1])).getByText('Fotobox')).toBeTruthy();

    fireEvent.click(screen.getByText('Gelöschte zeigen'));
    expect(rows().map((r) => r.dataset['revoked'])).toEqual(['false', 'true', 'false']);
    expect(within(must(rows()[1])).getByText('Gelöscht')).toBeTruthy();
  });

  it('opens a code from a deep link, with its link and numbers', async () => {
    renderSection('tab=qr&code=1');
    const sheet = await screen.findByTestId('code-sheet');
    expect(within(sheet).getByText('Gorilla 1')).toBeTruthy();
    expect(within(sheet).getByText('QR-Code Nr. 1')).toBeTruthy();
    expect(within(sheet).getByTestId('code-url').textContent).toBe(
      `${window.location.origin}/?t=token-of-code-1-abcdef`,
    );
    // Testing Library normalizes the NBSP to a space
    expect(within(sheet).getByText('12-mal von 9 Personen')).toBeTruthy();
    expect(within(sheet).getByTestId('code-stat-guests').textContent).toBe('7');
    expect(within(sheet).getByTestId('code-token')).toBeTruthy();
  });

  it('creates a code from a pasted link: token and Ziel as in the link', async () => {
    const { requests, memory } = renderSection();
    fireEvent.click(screen.getByTestId('new-code'));
    const sheet = await screen.findByTestId('new-code-sheet');
    fireEvent.click(within(sheet).getByText('Eigenes'));
    const input = within(sheet).getByLabelText('Token oder Link');
    fireEvent.change(input, {
      target: { value: `${window.location.origin}/x/booth/?t=${PRINTED}` },
    });
    expect(within(sheet).getByTestId('token-target-note').textContent).toBe(
      'Ziel auf „Fotobox“ gesetzt, wie im Link.',
    );
    fireEvent.click(within(sheet).getByTestId('code-create'));
    await waitFor(() => expect(sent(requests, 'POST', '/api/admin/codes')).toHaveLength(1));
    const [post] = sent(requests, 'POST', '/api/admin/codes');
    expect(await must(post).clone().json()).toEqual({ token: PRINTED, target: 'booth', note: '' });
    expect(await screen.findByText('QR-Code Pfau 4 angelegt.')).toBeTruthy();
    await waitFor(() => expect(memory.history.at(-1)).toContain('code=4'));
  });

  it('shows the server refusing a token at the field', async () => {
    const { requests } = renderSection('tab=qr', {
      'POST /api/admin/codes': () =>
        json(409, {
          error: 'token_taken',
          message: 'Dieses Token hatte schon ein QR-Code. Ein Token wird nie zweimal vergeben.',
        }),
    });
    fireEvent.click(screen.getByTestId('new-code'));
    const sheet = await screen.findByTestId('new-code-sheet');
    fireEvent.click(within(sheet).getByText('Eigenes'));
    // a link without token never reaches the server
    fireEvent.change(within(sheet).getByLabelText('Token oder Link'), {
      target: { value: 'https://party.example/x/booth/' },
    });
    fireEvent.click(within(sheet).getByTestId('code-create'));
    expect(await within(sheet).findByText('In diesem Link steckt kein Token (…?t=…).')).toBeTruthy();
    expect(sent(requests, 'POST', '/api/admin/codes')).toHaveLength(0);

    fireEvent.change(within(sheet).getByLabelText('Token oder Link'), { target: { value: PRINTED } });
    fireEvent.click(within(sheet).getByTestId('code-create'));
    expect(
      await within(sheet).findByText(
        'Dieses Token hatte schon ein QR-Code. Ein Token wird nie zweimal vergeben.',
      ),
    ).toBeTruthy();
  });

  it('changes a token with a pasted link and takes its Ziel', async () => {
    const { requests } = renderSection('tab=qr&code=3');
    const sheet = await screen.findByTestId('code-sheet');
    fireEvent.click(within(sheet).getByTestId('code-token'));
    const tokenSheet = await screen.findByTestId('token-sheet');
    expect(within(tokenSheet).getByText('Token ändern: Gnu 3')).toBeTruthy();
    fireEvent.click(within(tokenSheet).getByText('Eigenes'));
    fireEvent.change(within(tokenSheet).getByLabelText('Token oder Link'), {
      target: { value: `https://elsewhere.example/x/beer/?t=${PRINTED}` },
    });
    expect(within(tokenSheet).getByTestId('token-host-warning').textContent).toContain(
      'Der Link zeigt auf elsewhere.example',
    );
    fireEvent.click(within(tokenSheet).getByTestId('token-save'));
    expect(await screen.findByText('Token von Gnu 3 geändert.')).toBeTruthy();
    const [post] = sent(requests, 'POST', '/api/admin/codes/3/token');
    expect(await bodyField(must(post), 'token')).toBe(PRINTED);
    const [patch] = sent(requests, 'PATCH', '/api/admin/codes/3');
    expect(await bodyField(must(patch), 'target')).toBe('beer');
  });

  it('warns before revoking the last active code', async () => {
    const qc = renderSection('tab=qr&code=1').qc;
    qc.setQueryData(
      codesKey,
      list([code({ id: 1 }), code({ id: 2, active: false, revoked_at: '2026-10-13T20:41:00.000Z' })]),
    );
    const sheet = await screen.findByTestId('code-sheet');
    fireEvent.click(within(sheet).getByTestId('code-delete'));
    const dialog = await screen.findByTestId('code-delete-dialog');
    expect(within(dialog).getByText('Gorilla 1 löschen?')).toBeTruthy();
    expect(within(dialog).getByTestId('last-code-warning')).toBeTruthy();
  });
});
