import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GuestUser } from '@/api/types';
import { UiProvider } from '@/ui/UiProvider';
import { resetSession, sessionStore, type SessionState } from '../session';
import { GuestPass } from './GuestPass';
import { StatusSlot } from './StatusSlot';

vi.mock('../device', () => ({
  getDeviceTraits: () => Promise.resolve({ hash: 'ab'.repeat(32), components: {} }),
}));

const user = (over: Partial<GuestUser> = {}): GuestUser => ({
  name: 'Verrückte Ente #3',
  display_name: null,
  shown_name: 'Verrückte Ente #3',
  instagram: null,
  banned: false,
  uploads_paused: false,
  analysis_opt_out: false,
  ai_opt_out: false,
  ...over,
});

function given(session: SessionState) {
  // the session's own identify never answers here: the test sets the state
  vi.stubGlobal('fetch', () => new Promise(() => undefined));
  act(() => sessionStore.setState({ session }));
}

beforeEach(() => {
  resetSession();
});

describe('GuestPass', () => {
  it('shows the short pseudonym, its monogram and an invitation for Instagram', () => {
    given({ status: 'ready', user: user(), uploadsStopped: false });
    render(<GuestPass />, { wrapper: UiProvider });
    const pass = screen.getByTestId('guest-pass');
    expect(pass.textContent).toContain('VE');
    expect(pass.textContent).toContain('Verrückte Ente');
    expect(pass.textContent).not.toContain('#3');
    expect(pass.textContent).toContain('Instagram hinzufügen');
    expect(pass.getAttribute('data-status')).toBe('ok');
  });

  it('shows the handle once there is one, and only the name when compact', () => {
    given({ status: 'ready', user: user({ instagram: 'lena.k' }), uploadsStopped: false });
    const { rerender } = render(<GuestPass />, { wrapper: UiProvider });
    expect(screen.getByTestId('guest-pass').textContent).toContain('@lena.k');
    rerender(<GuestPass compact />);
    expect(screen.getByTestId('guest-pass').textContent).not.toContain('@lena.k');
  });

  it('marks paused, stopped and banned in words, not colour alone', () => {
    given({ status: 'ready', user: user({ uploads_paused: true }), uploadsStopped: false });
    render(<GuestPass />, { wrapper: UiProvider });
    const pass = screen.getByTestId('guest-pass');
    expect(pass.getAttribute('data-status')).toBe('paused');
    expect(pass.textContent).toContain('Hochladen pausiert');
    given({ status: 'ready', user: user(), uploadsStopped: true });
    expect(pass.getAttribute('data-status')).toBe('stopped');
    given({ status: 'banned', user: user({ banned: true }) });
    expect(pass.getAttribute('data-status')).toBe('banned');
    expect(pass.textContent).toContain('Gesperrt');
  });

  it('opens the Du sheet: why the name is random, the Instagram name, the upload state', async () => {
    given({ status: 'ready', user: user({ instagram: 'lena.k' }), uploadsStopped: false });
    render(<GuestPass />, { wrapper: UiProvider });
    fireEvent.click(screen.getByTestId('guest-pass'));
    const sheet = await screen.findByRole('dialog', { name: 'Verrückte Ente #3' });
    expect(sheet.textContent).toContain('zufällig');
    const field = within(sheet).getByRole<HTMLInputElement>('textbox', { name: 'Instagram-Name' });
    expect(field.value).toBe('lena.k');
    expect(field.maxLength).toBe(30);
    expect(within(sheet).getByRole('button', { name: 'Speichern' })).toBeTruthy();
    expect(within(sheet).getByRole('button', { name: 'Entfernen' })).toBeTruthy();
    expect(within(sheet).getByTestId('guest-upload-state').textContent).toContain('Du kannst Fotos machen');
  });

  it('keeps the field to the bare name: a typed @ and a pasted profile link', async () => {
    given({ status: 'ready', user: user(), uploadsStopped: false });
    render(<GuestPass />, { wrapper: UiProvider });
    fireEvent.click(screen.getByTestId('guest-pass'));
    const field = await screen.findByRole<HTMLInputElement>('textbox', { name: 'Instagram-Name' });
    fireEvent.change(field, { target: { value: '@anna' } });
    await waitFor(() => expect(field.value).toBe('anna'));
    fireEvent.paste(field, {
      clipboardData: { getData: () => 'https://www.instagram.com/party.anna/?igsh=xyz' },
    });
    await waitFor(() => expect(field.value).toBe('party.anna'));
  });
});

describe('StatusSlot', () => {
  it('renders nothing while all is well', () => {
    given({ status: 'ready', user: user(), uploadsStopped: false });
    render(<StatusSlot />, { wrapper: UiProvider });
    expect(screen.queryByTestId('status-slot')).toBeNull();
  });

  it('names the state and explains it on tap', async () => {
    given({ status: 'ready', user: user(), uploadsStopped: true });
    render(<StatusSlot />, { wrapper: UiProvider });
    const slot = screen.getByTestId('status-slot');
    expect(slot.getAttribute('data-kind')).toBe('stopped');
    fireEvent.click(slot);
    const sheet = await screen.findByRole('dialog', { name: 'Hochladen ist kurz angehalten' });
    expect(sheet.textContent).toContain('Gleich geht’s weiter');
  });
});
