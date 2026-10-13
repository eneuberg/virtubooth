import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { AdminExtension } from '@/api/types';
import { clearToasts, ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { applyAdminEvent } from '../store/applyEvent';
import { qk } from '../store/keys';
import { bodyField, json, must, stubApi, testClient, type Route } from '../testing';
import type { AdminSettings, BoothFilterSettings } from './api';
import { boothFiltersKey } from './api';
import { settingsKey } from './keys';
import { SettingsSection } from './SettingsSection';

const SETTINGS: AdminSettings = {
  event: { name: 'Party', default_name: 'Party', custom: false, updated_at: null, by: null },
  password: { source: 'env', changed_at: null },
};

const BOOTH: AdminExtension = {
  id: 'booth',
  title: 'Fotobox',
  emoji: '📸',
  tagline: '',
  url: '/x/booth/',
  uploads: true,
  loaded: true,
  meta_labels: {},
};

function filters(...on: string[]): BoothFilterSettings {
  return {
    filters: ['normal', 'bw', 'neon'].map((id) => ({
      id,
      name: id === 'neon' ? 'Neon' : id,
      icon: '',
      enabled: on.includes(id),
    })),
  };
}

function renderSection(routes: Record<string, Route> = {}, booth: BoothFilterSettings | null = null) {
  const qc = testClient();
  qc.setQueryData(settingsKey, SETTINGS);
  qc.setQueryData(qk.extensions, booth ? [BOOTH] : []);
  if (booth) qc.setQueryData(boothFiltersKey, booth);
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
const isOn = (name: string | RegExp) => input(screen.getByRole('switch', { name })).checked;

afterEach(() => {
  act(() => clearToasts());
});

describe('Einstellungen', () => {
  it('shows the three blocks; the filters only with the Fotobox', () => {
    renderSection({}, filters('normal', 'bw', 'neon'));
    expect(screen.getByRole('heading', { level: 1, name: 'Einstellungen' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Eventname' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Fotobox-Filter' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Admin-Passwort' })).toBeTruthy();
    expect(screen.getByTestId('password-source').textContent).toBe(
      'Gerade gilt das Passwort aus VB_ADMIN_PASSWORD.',
    );
    cleanupAndRenderWithoutBooth();
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

describe('Fotobox-Filter', () => {
  it('keeps the last filter on: its switch is disabled and says why', () => {
    renderSection({}, filters('neon'));
    const list = screen.getByTestId('booth-filter-list');
    expect(input(within(list).getByRole('switch', { name: /Neon/ })).disabled).toBe(true);
    expect(within(list).getByText('Mindestens ein Filter bleibt an.')).toBeTruthy();
    expect(input(within(list).getByRole('switch', { name: 'bw' })).disabled).toBe(false);
  });

  it('saves a switch at once with the whole list', async () => {
    const { requests, qc } = renderSection(
      {
        'PUT /api/admin/x/booth/filters': async (req) => {
          const enabled = await bodyField(req, 'enabled');
          return filters(...(Array.isArray(enabled) ? enabled.map(String) : []));
        },
      },
      filters('normal', 'bw', 'neon'),
    );
    fireEvent.click(screen.getByRole('switch', { name: 'Neon' }));
    // optimistic: off at once
    expect(isOn('Neon')).toBe(false);
    await screen.findByText('„Neon“ ist aus.');
    expect(await bodyField(must(requests[0]), 'enabled')).toEqual(['normal', 'bw']);
    expect(qc.getQueryData<BoothFilterSettings>(boothFiltersKey)).toEqual(filters('normal', 'bw'));

    fireEvent.click(screen.getByRole('switch', { name: 'Neon' }));
    await screen.findByText('„Neon“ ist wieder an.');
    expect(await bodyField(must(requests[1]), 'enabled')).toEqual(['normal', 'bw', 'neon']);
  });

  it('rolls back with a toast when the server refuses', async () => {
    const { qc } = renderSection(
      {
        'PUT /api/admin/x/booth/filters': () =>
          json(400, { error: 'no_filter_enabled', message: 'Mindestens ein Filter muss an bleiben.' }),
      },
      filters('normal', 'bw', 'neon'),
    );
    fireEvent.click(screen.getByRole('switch', { name: 'bw' }));
    await screen.findByText('Mindestens ein Filter muss an bleiben.');
    expect(isOn('bw')).toBe(true);
    expect(qc.getQueryData<BoothFilterSettings>(boothFiltersKey)).toEqual(filters('normal', 'bw', 'neon'));
  });
});

function cleanupAndRenderWithoutBooth() {
  // a second render in the same test: without the Fotobox there is no filter block
  const qc = testClient();
  qc.setQueryData(settingsKey, SETTINGS);
  qc.setQueryData(qk.extensions, []);
  const { container } = render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <SettingsSection />
      </UiProvider>
    </QueryClientProvider>,
  );
  expect(within(container).queryByTestId('settings-booth-filters')).toBeNull();
  expect(within(container).getByTestId('settings-event')).toBeTruthy();
}
