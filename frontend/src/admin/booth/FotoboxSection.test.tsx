import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { AdminExtension } from '@/api/types';
import { clearToasts, ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { boothFiltersKey, type BoothFilterSettings } from '../settings/api';
import { qk } from '../store/keys';
import { bodyField, json, must, stubApi, testClient, type Route } from '../testing';
import { FotoboxSection } from './FotoboxSection';

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
  qc.setQueryData(qk.extensions, booth ? [BOOTH] : []);
  if (booth) qc.setQueryData(boothFiltersKey, booth);
  const requests = stubApi(routes);
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <FotoboxSection />
        <ToastSlot />
      </UiProvider>
    </QueryClientProvider>,
  );
  return { qc, requests };
}

function input(el: HTMLElement): HTMLInputElement {
  if (!(el instanceof HTMLInputElement)) throw new Error('not an input');
  return el;
}

const isOn = (name: string | RegExp) => input(screen.getByRole('switch', { name })).checked;

afterEach(() => {
  act(() => clearToasts());
});

describe('Fotobox section', () => {
  it('has its own heading and the filters', () => {
    renderSection({}, filters('normal', 'bw', 'neon'));
    expect(screen.getByRole('heading', { level: 1, name: 'Fotobox' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Filter' })).toBeTruthy();
  });

  it('says so when the Fotobox is not loaded', () => {
    renderSection();
    expect(screen.getByText('Die Fotobox ist nicht aktiv')).toBeTruthy();
    expect(screen.queryByTestId('settings-booth-filters')).toBeNull();
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
