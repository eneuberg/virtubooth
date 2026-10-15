import { QueryClientProvider, type QueryKey } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { StopState } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { applyAdminEvent } from '../store/applyEvent';
import { qk } from '../store/keys';
import { bodyField, stubApi, testClient } from '../testing';
import { useSwitchBusy } from './data';
import { QuickControls } from './QuickControls';
import { StatusStrip } from './StatusStrip';

const off: StopState = { enabled: false, since: null, by: null };
// now: the strip says „seit 22:41“ for today, „seit Di, 22:41“ for an earlier day
const SINCE = new Date().toISOString();

/** The server's answer to a switch: the state it asked for. */
async function answer(req: Request) {
  const enabled = (await bodyField(req, 'enabled')) === true;
  return { enabled, since: enabled ? SINCE : null, by: 'admin:1', changed: true };
}

function renderDashboard() {
  const qc = testClient();
  qc.setQueryData(qk.uploadStop, off);
  qc.setQueryData(qk.joinStop, off);
  const requests = stubApi({
    'POST /api/admin/upload-stop': answer,
    'POST /api/admin/join-stop': answer,
  });
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <StatusStrip />
        <QuickControls />
      </UiProvider>
    </QueryClientProvider>,
  );
  return { qc, requests };
}

async function posted(requests: Request[], path: string): Promise<unknown[]> {
  const mine = requests.filter((r) => r.method === 'POST' && new URL(r.url).pathname === path);
  return Promise.all(mine.map((r) => bodyField(r, 'enabled')));
}

afterEach(() => {
  vi.unstubAllGlobals();
  useSwitchBusy.setState({ busy: null });
});

describe('QuickControls and StatusStrip', () => {
  it('stops all uploads in one tap, no confirmation; then only the strip can resume', async () => {
    const { requests } = renderDashboard();
    const stop = screen.getByTestId('quick-upload-stop');
    expect(stop.textContent).toBe('Hochladen stoppen');
    expect(stop.hasAttribute('aria-pressed')).toBe(false);
    expect(screen.queryByTestId('status-strip-uploads')).toBeNull();

    fireEvent.click(stop);
    const strip = await screen.findByTestId('status-strip-uploads');
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(strip.textContent).toContain('Hochladen gestoppt');
    expect(strip.textContent).toMatch(/Für alle, seit \d\d:\d\d\./);
    // the stop button is gone while it is on: "stoppen" can never mean "resume"
    expect(screen.queryByTestId('quick-upload-stop')).toBeNull();
    // the other one is left and spans the row
    const controls = screen.getByTestId('quick-controls');
    expect(controls.children).toHaveLength(1);
    expect(within(controls).getByTestId('quick-join-stop')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Hochladen fortsetzen' }));
    await waitFor(() => expect(screen.queryByTestId('status-strip-uploads')).toBeNull());
    expect(screen.getByTestId('quick-upload-stop')).toBeTruthy();
    expect(await posted(requests, '/api/admin/upload-stop')).toEqual([true, false]);
    // the focus goes back to the stop button (handFocus, after a short delay: the test
    // waits for it, or the delayed hand-off would run after the test environment is gone)
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('quick-upload-stop')));
  });

  it('stops joining next to it, independently', async () => {
    const { requests } = renderDashboard();
    fireEvent.click(screen.getByTestId('quick-join-stop'));
    const strip = await screen.findByTestId('status-strip-join');
    expect(strip.textContent).toContain('Anmeldung gestoppt');
    expect(screen.queryByTestId('quick-join-stop')).toBeNull();
    expect(screen.queryByTestId('status-strip-uploads')).toBeNull();
    expect(screen.getByTestId('quick-upload-stop')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Anmeldung wieder öffnen' }));
    await waitFor(() => expect(screen.queryByTestId('status-strip-join')).toBeNull());
    expect(screen.getByTestId('quick-join-stop')).toBeTruthy();
    expect(await posted(requests, '/api/admin/join-stop')).toEqual([true, false]);
    expect(await posted(requests, '/api/admin/upload-stop')).toEqual([]);
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId('quick-join-stop')));
  });

  it('follows the event stream: another admin switched both on, so the row goes away', async () => {
    const { qc } = renderDashboard();
    const on: StopState = { enabled: true, since: SINCE, by: 'admin:2' };
    const ctx = { qc, invalidate: () => {} };
    act(() => {
      applyAdminEvent({ type: 'settings.upload_stop', id: 'e-1', data: { upload_stop: on } }, ctx);
      applyAdminEvent({ type: 'settings.join_stop', id: 'e-2', data: { join_stop: on } }, ctx);
    });
    await screen.findByTestId('status-strip-join');
    expect(screen.getByTestId('status-strip').getAttribute('data-state')).toBe('on');
    expect(screen.getByTestId('status-strip-uploads')).toBeTruthy();
    expect(screen.queryByTestId('quick-controls')).toBeNull();
  });

  it('keeps the state when the server refuses', async () => {
    const qc = testClient();
    qc.setQueryData(qk.uploadStop, off);
    qc.setQueryData(qk.joinStop, off);
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
          <QuickControls />
        </UiProvider>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByTestId('quick-join-stop'));
    await waitFor(() => expect(useSwitchBusy.getState().busy).toBeNull());
    expect(screen.getByTestId('quick-join-stop').getAttribute('data-state')).toBe('off');
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
