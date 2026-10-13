import { QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { PauseState, StopState } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { qk } from '../store/keys';
import { bodyField, stubApi, testClient } from '../testing';
import { useUploadSheet } from './sheetStore';
import { UploadControlsSheet } from './UploadControlsSheet';
import { UploadStatusPill } from './UploadStatusPill';

const stopOff: StopState = { enabled: false, since: null, by: null };
const pauseOn: PauseState = {
  enabled: true,
  since: '2026-10-13T20:41:00.000+00:00',
  period: 2,
  by: 'admin:1',
  affected: 2,
  paused_total: 3,
};

function renderSheet() {
  const qc = testClient();
  qc.setQueryData(qk.uploadStop, stopOff);
  qc.setQueryData(qk.uploadPause, pauseOn);
  const requests = stubApi({
    'GET /api/admin/upload-stop': () => stopOff,
    'GET /api/admin/upload-pause': () => pauseOn,
    'GET /api/admin/users': () => ({ users: [], next_offset: null }),
    'POST /api/admin/upload-pause': async (req) => {
      const body = {
        enabled: (await bodyField(req, 'enabled')) === true,
        restore: await bodyField(req, 'restore'),
      };
      return {
        ...pauseOn,
        enabled: body.enabled,
        affected: 0,
        changed: true,
        restored: body.restore ? 2 : 0,
        kept: body.restore ? 0 : 2,
      };
    },
    'POST /api/admin/upload-stop': async (req) => {
      const body = { enabled: (await bodyField(req, 'enabled')) === true };
      return { enabled: body.enabled, since: '2026-10-13T20:50:00.000+00:00', by: 'admin:1', changed: true };
    },
  });
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <UploadStatusPill />
        <UploadControlsSheet />
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

describe('upload controls', () => {
  afterEach(() => act(() => useUploadSheet.getState().setOpen(false)));

  it('the pill shows the state at a glance and opens the sheet', async () => {
    renderSheet();
    const pill = screen.getByTestId('uploads-chip');
    expect(pill.textContent).toContain('Neue pausiert');
    expect(pill.getAttribute('data-state')).toBe('paused-new');
    fireEvent.click(pill);
    expect(await screen.findByRole('dialog')).toBeTruthy();
    expect(screen.getByRole('switch', { name: /Hochladen für alle stoppen/ })).toBeTruthy();
  });

  it('stopping everything is one switch, its state is the feedback', async () => {
    const { requests } = renderSheet();
    act(() => useUploadSheet.getState().setOpen(true));
    fireEvent.click(await screen.findByRole('switch', { name: /Hochladen für alle stoppen/ }));
    await waitFor(() =>
      expect(screen.getByTestId('uploads-result').textContent).toBe('Hochladen für alle gestoppt.'),
    );
    expect(await bodies(requests, '/api/admin/upload-stop')).toEqual([{ enabled: true }]);
    expect(screen.getByTestId('uploads-chip').getAttribute('data-state')).toBe('stopped');
  });

  it('switching the new-guest pause off asks: release or keep', async () => {
    const { requests } = renderSheet();
    act(() => useUploadSheet.getState().setOpen(true));
    fireEvent.click(await screen.findByRole('switch', { name: /Neue Gäste pausieren/ }));
    const text = await screen.findByTestId('pause-end-text');
    expect(text.textContent).toContain('2 Gäste sind während der Pause beigetreten');
    // nothing was sent yet
    expect(await bodies(requests, '/api/admin/upload-pause')).toEqual([]);
    fireEvent.click(screen.getByTestId('pause-end-back'));
    expect(screen.queryByTestId('pause-end-text')).toBeNull();

    fireEvent.click(screen.getByRole('switch', { name: /Neue Gäste pausieren/ }));
    fireEvent.click(await screen.findByTestId('pause-end-keep'));
    await waitFor(() =>
      expect(screen.getByTestId('uploads-result').textContent).toContain('2 Gäste bleiben pausiert'),
    );
    expect(await bodies(requests, '/api/admin/upload-pause')).toEqual([{ enabled: false, restore: false }]);
  });

  it('restoring releases the guests of that pause', async () => {
    const { requests } = renderSheet();
    act(() => useUploadSheet.getState().setOpen(true));
    fireEvent.click(await screen.findByRole('switch', { name: /Neue Gäste pausieren/ }));
    const dialog = screen.getByRole('dialog');
    fireEvent.click(within(dialog).getByTestId('pause-end-restore'));
    await waitFor(() =>
      expect(screen.getByTestId('uploads-result').textContent).toBe('2 Gäste wieder freigeschaltet.'),
    );
    expect(await bodies(requests, '/api/admin/upload-pause')).toEqual([{ enabled: false, restore: true }]);
  });
});
