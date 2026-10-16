import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { clearToasts, ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { applyAdminEvent } from '../store/applyEvent';
import { bodyField, json, must, stubApi, testClient, type Route } from '../testing';
import type { AdminSettings } from './api';
import { settingsKey } from './keys';
import { SettingsSection } from './SettingsSection';

const AUTO: AdminSettings['public_address'] = {
  address: null,
  effective: 'http://localhost:3000',
  source: 'auto',
  check: { status: 'auto', url: null, at: null, message: 'Automatisch.' },
};

const SETTINGS: AdminSettings = {
  event: { name: 'Party', default_name: 'Party', custom: false, updated_at: null, by: null },
  password: { source: 'env', changed_at: null },
  public_address: AUTO,
};

function renderSection(routes: Record<string, Route> = {}, settings: AdminSettings = SETTINGS) {
  const qc = testClient();
  qc.setQueryData(settingsKey, settings);
  const requests = stubApi(routes);
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <SettingsSection />
        <ToastSlot />
      </UiProvider>
    </QueryClientProvider>,
  );
  return { qc, requests };
}

function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function input(el: HTMLElement): HTMLInputElement {
  if (!(el instanceof HTMLInputElement)) throw new Error('not an input');
  return el;
}

const valueOf = (label: string) => input(screen.getByLabelText(label)).value;

afterEach(() => {
  act(() => clearToasts());
});

describe('Allgemeines', () => {
  it('shows the three blocks, no Fotobox filters, no Erscheinungsbild', () => {
    renderSection();
    expect(screen.getByRole('heading', { level: 1, name: 'Allgemeines' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Eventname' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Öffentliche Adresse' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Admin-Passwort' })).toBeTruthy();
    expect(screen.queryByTestId('settings-booth-filters')).toBeNull();
    // the Erscheinungsbild has its own section (LookSection)
    expect(screen.queryByTestId('settings-theme')).toBeNull();
    expect(screen.getByTestId('password-source').textContent).toBe(
      'Gerade gilt das Passwort aus VB_ADMIN_PASSWORD.',
    );
  });

  it('saves the event name and offers the way back', async () => {
    const { requests, qc } = renderSection({
      'PUT /api/admin/settings/event': async (req) => {
        const name = await bodyField(req, 'name');
        return name === null
          ? { ...SETTINGS.event, changed: true }
          : {
              name,
              default_name: 'Party',
              custom: true,
              updated_at: '2026-10-13T20:00:00Z',
              by: 'admin:1',
              changed: true,
            };
      },
    });
    expect(screen.queryByTestId('event-name-reset')).toBeNull();
    type('Name des Events', 'Sommerfest');
    fireEvent.click(screen.getByTestId('event-name-save'));
    await screen.findByText('Eventname gespeichert.');
    expect(await bodyField(must(requests[0]), 'name')).toBe('Sommerfest');
    expect(qc.getQueryData<AdminSettings>(settingsKey)?.event.name).toBe('Sommerfest');
    const reset = await screen.findByTestId('event-name-reset');
    expect(reset.textContent).toBe('Zurück zu „Party“');

    fireEvent.click(reset);
    await screen.findByText('Eventname zurückgesetzt.');
    expect(await bodyField(must(requests[1]), 'name')).toBeNull();
    expect(valueOf('Name des Events')).toBe('Party');
    expect(screen.queryByTestId('event-name-reset')).toBeNull();
  });

  it('says a blank name at the field instead of resetting', () => {
    const { requests } = renderSection();
    type('Name des Events', '   ');
    fireEvent.click(screen.getByTestId('event-name-save'));
    expect(screen.getByText('Der Name braucht 1 bis 60 Zeichen.')).toBeTruthy();
    expect(requests).toHaveLength(0);
  });

  it('follows a rename by another admin while the field is untouched', async () => {
    const { qc } = renderSection();
    act(() => {
      applyAdminEvent(
        {
          type: 'settings.event',
          id: 'e-1',
          data: { event: { ...SETTINGS.event, name: 'Gartenfest', custom: true } },
        },
        { qc, invalidate: () => {} },
      );
    });
    // React Query tells the component on its next tick
    await waitFor(() => expect(valueOf('Name des Events')).toBe('Gartenfest'));
    expect(screen.getByTestId('event-name-reset')).toBeTruthy();
  });

  it('checks that the two new passwords match before asking the server', () => {
    const { requests } = renderSection();
    type('Aktuelles Passwort', 'the-old-password');
    type('Neues Passwort', 'a-new-password-1');
    type('Neues Passwort wiederholen', 'a-new-password-2');
    fireEvent.click(screen.getByTestId('password-save'));
    expect(screen.getByText('Die beiden neuen Passwörter sind nicht gleich.')).toBeTruthy();
    expect(requests).toHaveLength(0);
  });

  it('changes the password, says how many devices left and clears the fields', async () => {
    const { requests } = renderSection({
      'POST /api/admin/settings/password': () => ({ ok: true, sessions_ended: 2 }),
      'GET /api/admin/settings': () => ({
        ...SETTINGS,
        password: { source: 'admin', changed_at: '2026-10-13T20:41:00.000+00:00' },
      }),
    });
    type('Aktuelles Passwort', 'the-old-password');
    type('Neues Passwort', 'a-new-password-1');
    type('Neues Passwort wiederholen', 'a-new-password-1');
    fireEvent.click(screen.getByTestId('password-save'));
    await screen.findByText('Passwort geändert. 2 andere Geräte abgemeldet.');
    const post = must(requests.find((r) => r.method === 'POST'));
    expect(await post.clone().json()).toEqual({ current: 'the-old-password', new: 'a-new-password-1' });
    for (const label of ['Aktuelles Passwort', 'Neues Passwort', 'Neues Passwort wiederholen']) {
      expect(valueOf(label)).toBe('');
    }
    await waitFor(() =>
      expect(screen.getByTestId('password-source').textContent).toMatch(
        /^Hier geändert am 13\.10\.2026, \d\d:41\. VB_ADMIN_PASSWORD gilt nicht mehr\.$/,
      ),
    );
  });

  it('shows a wrong current password at its field', async () => {
    renderSection({
      'POST /api/admin/settings/password': () =>
        json(403, { error: 'wrong_password', message: 'Das aktuelle Passwort stimmt nicht.' }),
    });
    type('Aktuelles Passwort', 'not-it');
    type('Neues Passwort', 'a-new-password-1');
    type('Neues Passwort wiederholen', 'a-new-password-1');
    fireEvent.click(screen.getByTestId('password-save'));
    await screen.findByText('Das aktuelle Passwort stimmt nicht.');
    expect(screen.getByLabelText('Aktuelles Passwort').getAttribute('aria-invalid')).toBe('true');
    // the new ones stay, to try again
    expect(valueOf('Neues Passwort')).toBe('a-new-password-1');
  });
});

describe('Öffentliche Adresse', () => {
  const ok = {
    address: 'https://party.example.com',
    effective: 'https://party.example.com',
    source: 'setting' as const,
    check: {
      status: 'ok' as const,
      url: 'https://party.example.com',
      at: '2026-10-15T19:14:00Z',
      message: 'Erreichbar.',
    },
  };

  it('is automatic while empty: no check button', () => {
    renderSection();
    expect(screen.getByText('Leer lassen = automatisch aus dem Aufruf')).toBeTruthy();
    expect(screen.getByTestId('address-status').dataset['status']).toBe('auto');
    expect(screen.queryByTestId('public-address-check')).toBeNull();
  });

  it('saves (the server checks) and shows the result', async () => {
    const { requests, qc } = renderSection({ 'PUT /api/admin/settings/public-address': () => ok });
    type('Adresse für QR-Codes und Plakate', ' https://party.example.com ');
    fireEvent.click(screen.getByTestId('public-address-save'));
    await screen.findByText('Adresse gespeichert.');
    expect(await bodyField(must(requests[0]), 'address')).toBe('https://party.example.com');
    expect(qc.getQueryData<AdminSettings>(settingsKey)?.public_address).toEqual(ok);
    const status = await screen.findByTestId('address-status');
    expect(status.textContent).toMatch(/^Erreichbar ✓ – geprüft \d\d:14$/);
    expect(screen.getByTestId('public-address-check')).toBeTruthy();
  });

  it('warns when it does not reach this server, and checks again', async () => {
    const down = {
      ...ok,
      check: { ...ok.check, status: 'unreachable' as const, message: 'Verbindung abgelehnt.' },
    };
    const { requests } = renderSection(
      { 'POST /api/admin/settings/public-address/check': () => ok.check },
      { ...SETTINGS, public_address: down },
    );
    const status = screen.getByTestId('address-status');
    expect(status.dataset['status']).toBe('unreachable');
    expect(status.textContent).toContain('Nicht erreichbar – QR-Codes würden ins Leere führen.');
    expect(status.textContent).toContain('Verbindung abgelehnt.');
    fireEvent.click(screen.getByTestId('public-address-check'));
    await waitFor(() => expect(screen.getByTestId('address-status').dataset['status']).toBe('ok'));
    expect(must(requests[0]).method).toBe('POST');
  });

  it('shows the server’s refusal at the field', async () => {
    renderSection({
      'PUT /api/admin/settings/public-address': () =>
        json(400, {
          error: 'invalid_public_address',
          message: 'Die Adresse muss mit http:// oder https:// beginnen.',
        }),
    });
    type('Adresse für QR-Codes und Plakate', 'party.example.com');
    fireEvent.click(screen.getByTestId('public-address-save'));
    await screen.findByText('Die Adresse muss mit http:// oder https:// beginnen.');
    expect(screen.getByLabelText('Adresse für QR-Codes und Plakate').getAttribute('aria-invalid')).toBe(
      'true',
    );
  });
});
