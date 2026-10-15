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
  is_host: false,
  ...over,
});

function joinText(externalAi: boolean) {
  return {
    version: '1',
    title: 'Willkommen!',
    paragraphs: ['a', 'b', 'c'],
    instagram_prompt: 'Instagram',
    accept_label: 'Los',
    party_name: 'Party',
    instagram_account: '',
    analysis: false,
    external_ai: externalAi,
  };
}

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

  it('shows the handle once there is one (as the name others see), and only the name when compact', () => {
    given({ status: 'ready', user: user({ instagram: 'lena.k' }), uploadsStopped: false });
    const { rerender } = render(<GuestPass />, { wrapper: UiProvider });
    const pass = screen.getByTestId('guest-pass');
    expect(pass.textContent).toBe('L@lena.kName wählen');
    rerender(<GuestPass compact />);
    expect(screen.getByTestId('guest-pass').textContent).toBe('L@lena.k');
  });

  it('shows the display name first, the handle under it', () => {
    given({
      status: 'ready',
      user: user({ display_name: '🎉 Party Fred', shown_name: '🎉 Party Fred', instagram: 'lena.k' }),
      uploadsStopped: false,
    });
    render(<GuestPass />, { wrapper: UiProvider });
    expect(screen.getByTestId('guest-pass').textContent).toBe('🎉P🎉 Party Fred@lena.k');
  });

  it('tells the admin guest, and only it, that it is the admin guest', () => {
    given({
      status: 'ready',
      user: user({ display_name: 'Gastgeber', shown_name: 'Gastgeber', is_host: true }),
      uploadsStopped: false,
    });
    const { rerender } = render(<GuestPass />, { wrapper: UiProvider });
    expect(screen.getByTestId('guest-pass-host').textContent).toBe('Admin-Gast · nur du siehst das');
    rerender(<GuestPass compact />);
    expect(screen.queryByTestId('guest-pass-host')).toBeNull();
    act(() => sessionStore.setState({ session: { status: 'ready', user: user(), uploadsStopped: false } }));
    rerender(<GuestPass />);
    expect(screen.queryByTestId('guest-pass-host')).toBeNull();
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

  it('saves the display name; the default is the placeholder', async () => {
    const requests: Request[] = [];
    given({
      status: 'ready',
      user: user({ instagram: 'lena.k', shown_name: '@lena.k' }),
      uploadsStopped: false,
    });
    vi.stubGlobal('fetch', async (req: Request) => {
      if (req.method !== 'PATCH') return new Promise(() => undefined);
      requests.push(req);
      const named = user({ display_name: 'Fred', shown_name: 'Fred', instagram: 'lena.k' });
      return new Response(JSON.stringify({ user: named }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    render(<GuestPass />, { wrapper: UiProvider });
    fireEvent.click(screen.getByTestId('guest-pass'));
    const field = await screen.findByRole<HTMLInputElement>('textbox', { name: 'Anzeigename' });
    expect(field.placeholder).toBe('@lena.k');
    fireEvent.change(field, { target: { value: '  Fred ' } });
    fireEvent.click(screen.getByTestId('display-name-save'));
    await waitFor(() => expect(requests).toHaveLength(1));
    const req = requests[0];
    if (!req) throw new Error('no request');
    expect(req.method).toBe('PATCH');
    expect(await req.clone().json()).toEqual({ display_name: 'Fred' });
    await waitFor(() => expect(screen.getByTestId('guest-pass').textContent).toContain('Fred'));
  });

  it('shows the server’s refusal of a name at the field', async () => {
    given({ status: 'ready', user: user(), uploadsStopped: false });
    vi.stubGlobal('fetch', async (req: Request) =>
      req.method !== 'PATCH'
        ? new Promise(() => undefined)
        : new Response(
            JSON.stringify({ error: 'display_name_taken', message: 'Dieser Name ist schon vergeben.' }),
            {
              status: 409,
              headers: { 'Content-Type': 'application/json' },
            },
          ),
    );
    render(<GuestPass />, { wrapper: UiProvider });
    fireEvent.click(screen.getByTestId('guest-pass'));
    const field = await screen.findByRole<HTMLInputElement>('textbox', { name: 'Anzeigename' });
    fireEvent.change(field, { target: { value: 'Anna' } });
    fireEvent.click(screen.getByTestId('display-name-save'));
    await screen.findByText('Dieser Name ist schon vergeben.');
    expect(field.getAttribute('aria-invalid')).toBe('true');
  });

  it('offers „Keine Weitergabe an externe KI“ only while the host has external AI on', async () => {
    given({ status: 'ready', user: user(), uploadsStopped: false });
    act(() => sessionStore.setState({ joinText: joinText(false) }));
    const { unmount } = render(<GuestPass />, { wrapper: UiProvider });
    fireEvent.click(screen.getByTestId('guest-pass'));
    await screen.findByTestId('display-name-form');
    expect(screen.queryByTestId('guest-ai-opt-out')).toBeNull();
    unmount();
    act(() => sessionStore.setState({ joinText: joinText(true) }));
    render(<GuestPass />, { wrapper: UiProvider });
    fireEvent.click(screen.getByTestId('guest-pass'));
    expect(await screen.findByRole('switch', { name: /Keine Weitergabe an externe KI/ })).toBeTruthy();
  });

  it('keeps the field to the bare name: a typed @ and a pasted profile link', async () => {
    given({ status: 'ready', user: user(), uploadsStopped: false });
    render(<GuestPass />, { wrapper: UiProvider });
    fireEvent.click(screen.getByTestId('guest-pass'));
    const field = await screen.findByRole<HTMLInputElement>('textbox', { name: 'Instagram-Name' });
    fireEvent.change(field, { target: { value: '@anna' } });
    await waitFor(() => expect(field.value).toBe('anna'));
    fireEvent.change(field, { target: { value: ' ＠an@na' } });
    await waitFor(() => expect(field.value).toBe('anna'));
    // the „@“ sits inside the field, outside the input: never part of the value
    const prefix = field.parentElement?.querySelector('[aria-hidden=true]');
    expect(prefix?.textContent).toBe('@');
    expect(prefix?.className).toContain('select-none');
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
