import { QueryClientProvider, type QueryKey } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { PauseState, StopState } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { useSwitchBusy } from '../dashboard/data';
import { applyAdminEvent } from '../store/applyEvent';
import { qk } from '../store/keys';
import { bodyField, stubApi, testClient } from '../testing';
import { PartyControls, PartyStateBadges } from './PartyControls';

const off: StopState = { enabled: false, since: null, by: null };
// today: the state line says „seit 22:41“
const SINCE = new Date().toISOString();
const pauseOff: PauseState = {
  enabled: false,
  since: null,
  period: null,
  by: null,
  affected: 0,
  paused_total: 0,
};
const pauseOn = (affected: number): PauseState => ({
  enabled: true,
  since: SINCE,
  period: 2,
  by: 'admin:1',
  affected,
  paused_total: affected + 1,
});

/** The server's answer to a stop switch: the state it asked for. */
async function answer(req: Request) {
  const enabled = (await bodyField(req, 'enabled')) === true;
  return { enabled, since: enabled ? SINCE : null, by: 'admin:1', changed: true };
}

function renderControls(pause: PauseState = pauseOff, layout?: 'stack' | 'row' | 'sidebar') {
  const qc = testClient();
  qc.setQueryData(qk.uploadStop, off);
  qc.setQueryData(qk.joinStop, off);
  qc.setQueryData(qk.uploadPause, pause);
  const requests = stubApi({
    'POST /api/admin/upload-stop': answer,
    'POST /api/admin/join-stop': answer,
    'POST /api/admin/upload-pause': async (req) => {
      const enabled = (await bodyField(req, 'enabled')) === true;
      const restore = await bodyField(req, 'restore');
      const affected = pause.affected;
      return {
        enabled,
        since: enabled ? SINCE : null,
        period: enabled ? 3 : null,
        by: 'admin:1',
        affected: 0,
        paused_total: restore ? 1 : pause.paused_total,
        changed: true,
        restored: !enabled && restore ? affected : 0,
        kept: !enabled && restore === false ? affected : 0,
      };
    },
  });
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <PartyStateBadges />
        <PartyControls layout={layout} />
      </UiProvider>
    </QueryClientProvider>,
  );
  return { qc, requests };
}

function bodies(requests: Request[], path: string): Promise<unknown[]> {
  return Promise.all(
    requests
      .filter((r) => r.method === 'POST' && new URL(r.url).pathname === path)
      .map((r) => r.clone().json()),
  );
}

/** The hidden input React Aria renders for a switch (role="switch", checked state). */
function input(testId: string): HTMLInputElement {
  const el = screen.getByTestId(testId).querySelector('input');
  if (!el) throw new Error(`no input in ${testId}`);
  return el;
}

afterEach(() => {
  vi.unstubAllGlobals();
  useSwitchBusy.setState({ busy: null });
});

describe('PartyControls', () => {
  it('shows all three switches at once, as real labelled switches', () => {
    renderControls();
    for (const [id, name] of [
      ['upload-stop-switch', /Hochladen für alle stoppen/],
      ['join-stop-switch', /Anmeldung stoppen/],
      ['upload-pause-switch', /Neue Gäste pausieren/],
    ] as const) {
      expect(screen.getByRole('switch', { name })).toBe(input(id));
      expect(input(id).checked).toBe(false);
      expect(screen.getByTestId(id).getAttribute('data-state')).toBe('off');
    }
    expect(screen.getByTestId('upload-stop-switch').textContent).toContain('Alle können hochladen.');
    // nothing on: no badges, no paused-guests link
    expect(screen.queryByTestId('party-badges')).toBeNull();
    expect(screen.queryByTestId('uploads-paused-list')).toBeNull();
  });

  it('stops all uploads in one tap, no confirmation, and resumes with the same switch', async () => {
    const { requests } = renderControls();
    fireEvent.click(input('upload-stop-switch'));
    await waitFor(() =>
      expect(screen.getByTestId('upload-stop-switch').getAttribute('data-state')).toBe('on'),
    );
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(input('upload-stop-switch').checked).toBe(true);
    expect(screen.getByTestId('upload-stop-switch').textContent).toMatch(/Gestoppt seit \d\d:\d\d\./);
    expect(screen.getByTestId('party-badges').textContent).toContain('Hochladen gestoppt');
    expect(screen.getByTestId('party-summary').textContent).toMatch(/^Hochladen für alle gestoppt seit/);

    fireEvent.click(input('upload-stop-switch'));
    await waitFor(() =>
      expect(screen.getByTestId('upload-stop-switch').getAttribute('data-state')).toBe('off'),
    );
    expect(await bodies(requests, '/api/admin/upload-stop')).toEqual([{ enabled: true }, { enabled: false }]);
    expect(await bodies(requests, '/api/admin/join-stop')).toEqual([]);
  });

  it('stops joining independently', async () => {
    const { requests } = renderControls(pauseOff, 'sidebar');
    fireEvent.click(input('join-stop-switch'));
    await waitFor(() => expect(screen.getByTestId('join-stop-switch').getAttribute('data-state')).toBe('on'));
    expect(screen.getByTestId('upload-stop-switch').getAttribute('data-state')).toBe('off');
    expect(screen.getByTestId('party-badges').textContent).toBe('Anmeldung gestoppt');
    expect(await bodies(requests, '/api/admin/join-stop')).toEqual([{ enabled: true }]);
  });

  it('pauses new guests in one tap and links to the paused guests', async () => {
    const { requests } = renderControls(pauseOn(0));
    expect(input('upload-pause-switch').checked).toBe(true);
    expect(screen.getByTestId('upload-pause-switch').textContent).toMatch(/noch niemand betroffen/);
    const link = screen.getByTestId('uploads-paused-list');
    expect(link.textContent).toBe('1\u00a0Gast pausiert');
    expect(link.getAttribute('href')).toBe('/manage?tab=gaeste&show=paused');
    // nobody joined during the pause: switching it off does not ask
    fireEvent.click(input('upload-pause-switch'));
    await waitFor(() => expect(input('upload-pause-switch').checked).toBe(false));
    expect(screen.queryByTestId('pause-end')).toBeNull();
    expect(await bodies(requests, '/api/admin/upload-pause')).toEqual([{ enabled: false, restore: true }]);
  });

  it('asks before ending a pause guests joined during: release them, or keep them paused', async () => {
    const { requests } = renderControls(pauseOn(2));
    fireEvent.click(input('upload-pause-switch'));
    const text = await screen.findByTestId('pause-end-text');
    expect(text.textContent).toContain('2 Gäste sind während der Pause beigetreten');
    // still on until the host decides
    expect(input('upload-pause-switch').checked).toBe(true);
    fireEvent.click(screen.getByTestId('pause-end-back'));
    await waitFor(() => expect(screen.queryByTestId('pause-end-text')).toBeNull());
    expect(await bodies(requests, '/api/admin/upload-pause')).toEqual([]);

    fireEvent.click(input('upload-pause-switch'));
    fireEvent.click(await screen.findByTestId('pause-end-keep'));
    await waitFor(() => expect(input('upload-pause-switch').checked).toBe(false));
    await waitFor(() => expect(screen.queryByTestId('pause-end-text')).toBeNull());
    expect(await bodies(requests, '/api/admin/upload-pause')).toEqual([{ enabled: false, restore: false }]);
  });

  it('follows the event stream: another admin switched both stops on', async () => {
    const { qc } = renderControls();
    const on: StopState = { enabled: true, since: SINCE, by: 'admin:2' };
    const ctx = { qc, invalidate: () => {} };
    act(() => {
      applyAdminEvent({ type: 'settings.upload_stop', id: 'e-1', data: { upload_stop: on } }, ctx);
      applyAdminEvent({ type: 'settings.join_stop', id: 'e-2', data: { join_stop: on } }, ctx);
    });
    await waitFor(() => expect(input('join-stop-switch').checked).toBe(true));
    expect(input('upload-stop-switch').checked).toBe(true);
    expect(screen.getByTestId('party-summary').textContent).toContain('Anmeldung gestoppt seit');
  });

  it('keeps the state when the server refuses', async () => {
    const qc = testClient();
    qc.setQueryData(qk.uploadStop, off);
    qc.setQueryData(qk.joinStop, off);
    qc.setQueryData(qk.uploadPause, pauseOff);
    stubApi({
      'POST /api/admin/join-stop': () =>
        new Response(
          JSON.stringify({ error: 'bad_origin', message: 'Anfrage von fremder Seite abgelehnt.' }),
          {
            status: 403,
            headers: { 'Content-Type': 'application/json' },
          },
        ),
    });
    render(
      <QueryClientProvider client={qc}>
        <UiProvider>
          <PartyControls />
        </UiProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(input('join-stop-switch'));
    await waitFor(() => expect(useSwitchBusy.getState().busy).toBeNull());
    expect(screen.getByTestId('join-stop-switch').getAttribute('data-state')).toBe('off');
    expect(qc.getQueryData<StopState>(qk.joinStop)?.enabled).toBe(false);
  });

  it('refreshes the overview on events that change its numbers', () => {
    const qc = testClient();
    const invalidate = vi.fn<(keys: ReadonlyArray<QueryKey>) => void>();
    applyAdminEvent(
      {
        type: 'user.created',
        id: 'e-3',
        data: {
          id: 1,
          name: 'Ente',
          instagram: null,
          banned: false,
          auto_banned: false,
          uploads_paused: false,
        },
      },
      { qc, invalidate },
    );
    expect(invalidate).toHaveBeenCalledWith([qk.overview]);
    invalidate.mockClear();
    applyAdminEvent({ type: 'settings.join_stop', id: 'e-4', data: { join_stop: off } }, { qc, invalidate });
    expect(invalidate).not.toHaveBeenCalledWith([qk.overview]);
  });
});
