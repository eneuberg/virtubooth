import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type * as Client from '../api/client';
import { LoginScreen } from './Screens';

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof Client>()),
  login: vi.fn<typeof Client.login>(() => Promise.resolve({ ok: true, via: 'password' })),
}));

describe('the wall login', () => {
  it('blurs the password field before the live wall takes over', async () => {
    // a password manager's button on the field closes on focusout; removing a focused
    // field does not reliably fire one, and the button stayed on the TV (Bitwarden's shield)
    const events: string[] = [];
    const onDone = vi.fn<() => void>(() => {
      events.push('done');
    });
    render(<LoginScreen onDone={onDone} onNoPassword={() => undefined} />);
    const input = screen.getByLabelText<HTMLInputElement>('Passwort');
    input.addEventListener('focusout', () => events.push('focusout'));
    input.focus();
    expect(document.activeElement).toBe(input);
    fireEvent.change(input, { target: { value: 'wall-geheim' } });
    fireEvent.click(screen.getByRole('button', { name: 'Live-Wall starten' }));
    await waitFor(() => expect(onDone).toHaveBeenCalledOnce());
    expect(events).toEqual(['focusout', 'done']);
    expect(document.activeElement).not.toBe(input);
  });
});
