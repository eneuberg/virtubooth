/**
 * The join sheet while the host stopped joining („Anmeldung stoppen“): no button, a
 * calm message, and the button comes back once the session sees joining is open.
 */
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConsentInfo } from '@/api/types';
import { getSession, resetSession, startSession } from '@/sdk/session';
import { UiProvider } from '@/ui/UiProvider';
import { JoinSheet } from './JoinSheet';

vi.mock('@/sdk/device', () => ({
  getDeviceTraits: () => Promise.resolve({ hash: 'ab'.repeat(32), components: {} }),
}));

const join: ConsentInfo = {
  version: '1',
  title: 'Willkommen bei Testparty!',
  paragraphs: ['Fotos.', 'Gerät.', 'Sonst nicht.'],
  instagram_prompt: 'Instagram-Name (freiwillig). Dann können wir dich markieren.',
  accept_label: 'Alles klar, los geht’s!',
  party_name: 'Testparty',
  instagram_account: '@testparty',
  analysis: false,
};

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

/** identify answers needs_consent with `closed()`; join answers `joinAnswer()`. */
function serve(closed: () => boolean, joinAnswer: () => Response) {
  const paths: string[] = [];
  vi.stubGlobal('fetch', async (input: Request) => {
    const path = new URL(input.url).pathname;
    paths.push(path);
    if (path === '/api/identify') {
      return reply(200, { state: 'needs_consent', consent: join, join_closed: closed() });
    }
    if (path === '/api/join') return joinAnswer();
    return reply(404, { error: 'http_404', message: 'Not Found' });
  });
  return paths;
}

function renderSheet() {
  render(
    <UiProvider>
      <JoinSheet join={join} />
    </UiProvider>,
  );
  return screen.getByRole('dialog');
}

beforeEach(() => resetSession());
afterEach(() => vi.unstubAllGlobals());

describe('JoinSheet while joining is closed', () => {
  it('shows a calm message instead of the button, and the button returns on a re-check', async () => {
    let closed = true;
    const paths = serve(
      () => closed,
      () => reply(500, {}),
    );
    await startSession();
    expect(getSession()).toMatchObject({ status: 'needs_join', joinClosed: true });
    const dialog = renderSheet();
    expect(within(dialog).getByTestId('join-closed').textContent).toContain(
      'Gerade kann niemand neu beitreten.',
    );
    expect(within(dialog).queryByRole('button', { name: 'Alles klar, los geht’s!' })).toBeNull();

    closed = false;
    fireEvent.click(within(dialog).getByTestId('join-recheck'));
    await waitFor(() =>
      expect(within(dialog).getByRole('button', { name: 'Alles klar, los geht’s!' })).toBeTruthy(),
    );
    expect(within(dialog).queryByTestId('join-closed')).toBeNull();
    expect(paths.filter((p) => p === '/api/join')).toHaveLength(0);
  });

  it('switches to the message when a join is refused with join_closed', async () => {
    serve(
      () => false,
      () =>
        reply(403, {
          error: 'join_closed',
          message: 'Gerade kann niemand neu beitreten. Versuch es gleich noch mal.',
        }),
    );
    await startSession();
    const dialog = renderSheet();
    await act(async () => {
      fireEvent.click(within(dialog).getByRole('button', { name: 'Alles klar, los geht’s!' }));
    });
    await waitFor(() => expect(within(dialog).getByTestId('join-closed')).toBeTruthy());
    expect(within(dialog).queryByRole('alert')).toBeNull();
    expect(getSession()).toMatchObject({ status: 'needs_join', joinClosed: true });
  });
});
