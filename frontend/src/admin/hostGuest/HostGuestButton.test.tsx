import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AdminUser } from '@/api/types';
import { clearToasts, ToastSlot } from '@/ui/Toast';
import { UiProvider } from '@/ui/UiProvider';
import { json, stubApi, testClient, type Route } from '../testing';
import type { HostGuestState } from './api';
import { HostGuestButton } from './HostGuestButton';
import { guestName } from './marks';

const SEEN = '2026-10-13T20:00:00.000+00:00';
const HOST: AdminUser = {
  id: 7,
  name: 'Tanzende Giraffe #7',
  display_name: 'Gastgeber',
  shown_name: 'Gastgeber',
  instagram: null,
  analysis_opt_out: false,
  ai_opt_out: false,
  created_at: SEEN,
  last_seen_at: SEEN,
  consent_at: SEEN,
  consent_version: '1',
  fp_hash: null,
  fp_components: {},
  first_ip: '',
  last_ip: '',
  user_agent: '',
  banned: false,
  banned_at: null,
  ban_reason: null,
  photo_count: 0,
  uploads_paused: false,
  uploads_paused_at: null,
  uploads_paused_source: null,
  uploads_lock_period: null,
  auto_banned: false,
  auto_ban: null,
  online_seconds: 0,
  online_sessions: 0,
  online_now: false,
  code: null,
  is_host: true,
};

function renderButton(state: HostGuestState, post: Route, hint = true) {
  const qc = testClient();
  const requests = stubApi({ 'GET /api/admin/guest': () => state, 'POST /api/admin/guest': post });
  render(
    <QueryClientProvider client={qc}>
      <UiProvider>
        <HostGuestButton hint={hint} />
        <ToastSlot />
      </UiProvider>
    </QueryClientProvider>,
  );
  return requests;
}

/** window.open's tab: the button sets its address once the guest cookie is set. */
function fakeTab() {
  const tab = { opener: {} as unknown, location: { href: '' }, close: vi.fn<() => void>() };
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- the three fields the button uses
  const open = vi.spyOn(window, 'open').mockReturnValue(tab as unknown as Window);
  return { tab, open };
}

const signedIn = (over: Record<string, unknown> = {}) => ({
  user: HOST,
  created: true,
  url: '/',
  replaced: null,
  ...over,
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  clearToasts();
});

describe('HostGuestButton', () => {
  it('says „Als Gast teilnehmen“ before the admin guest exists, and what applies to it', async () => {
    renderButton({ user: null, browser_is_host: false, browser_guest: null }, () => signedIn());
    const button = await screen.findByRole('button', { name: 'Als Gast teilnehmen' });
    const hint = screen.getByTestId('host-guest-hint');
    expect(button.getAttribute('aria-describedby')).toBe(hint.id);
    expect(hint.textContent).toContain('„Hochladen stoppen“ gilt aber auch für dich');
    expect(hint.textContent).not.toContain('ersetzt');
  });

  it('says „Als Gast öffnen“ once it exists, and warns about another guest identity', async () => {
    renderButton({ user: HOST, browser_is_host: false, browser_guest: 'Mutiger Krake #2' }, () => signedIn());
    await screen.findByRole('button', { name: 'Als Gast öffnen' });
    expect(screen.getByTestId('host-guest-hint').textContent).toContain(
      'als Gast „Mutiger Krake #2“ angemeldet: der wird hier durch den Admin-Gast ersetzt',
    );
  });

  it('signs in, opens the guest app in a new tab without a token, and says what it replaced', async () => {
    const { tab, open } = fakeTab();
    const requests = renderButton(
      { user: null, browser_is_host: false, browser_guest: 'Mutiger Krake #2' },
      () => signedIn({ replaced: 'Mutiger Krake #2' }),
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Als Gast teilnehmen' }));
    // the tab opens inside the click (popup blockers), the address follows the answer
    expect(open).toHaveBeenCalledWith('', '_blank');
    await waitFor(() => expect(tab.location.href).toBe('/'));
    expect(tab.opener).toBeNull();
    expect(requests.filter((r) => r.method === 'POST').map((r) => new URL(r.url).pathname)).toEqual([
      '/api/admin/guest',
    ]);
    expect(await screen.findByText(/war als Gast „Mutiger Krake #2“ angemeldet/)).toBeTruthy();
    expect(await screen.findByRole('button', { name: 'Als Gast öffnen' })).toBeTruthy();
    expect(screen.getByTestId('host-guest-hint').textContent).not.toContain('ersetzt');
  });

  it('closes the empty tab and shows the error when the server refuses', async () => {
    const { tab } = fakeTab();
    renderButton(
      { user: null, browser_is_host: false, browser_guest: null },
      () => json(403, { error: 'bad_origin', message: 'Anfrage von fremder Seite abgelehnt.' }),
      false,
    );
    const button = await screen.findByRole('button', { name: 'Als Gast teilnehmen' });
    expect(screen.queryByTestId('host-guest-hint')).toBeNull();
    fireEvent.click(button);
    expect(await screen.findByText('Anfrage von fremder Seite abgelehnt.')).toBeTruthy();
    expect(tab.close).toHaveBeenCalled();
    expect(tab.location.href).toBe('');
  });
});

describe('guestName', () => {
  it('marks the admin guest, nobody else', () => {
    expect(guestName({ name: 'Ente', is_host: false })).toBe('Ente');
    expect(guestName({ name: 'Ente', is_host: true })).toBe('Ente · Admin-Gast');
  });
});
