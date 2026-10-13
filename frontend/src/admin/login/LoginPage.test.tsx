import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { setNoAccessHandler } from '@/api/errors';
import { UiProvider } from '@/ui/UiProvider';
import { json, stubApi, testClient } from '../testing';
import { LoginPage } from './LoginPage';

function renderLogin(loginAnswer: () => Response) {
  setNoAccessHandler(() => undefined);
  stubApi({
    'GET /api/admin/session': () => ({ authenticated: false }),
    'POST /api/admin/login': loginAnswer,
  });
  render(
    <QueryClientProvider client={testClient()}>
      <UiProvider>
        <LoginPage />
      </UiProvider>
    </QueryClientProvider>,
  );
}

function submit(password: string) {
  fireEvent.change(screen.getByLabelText('Passwort'), { target: { value: password } });
  fireEvent.submit(screen.getByTestId('login-form'));
}

describe('LoginPage', () => {
  it('asks for a password first', async () => {
    renderLogin(() => json(200, { ok: true }));
    fireEvent.submit(screen.getByTestId('login-form'));
    await waitFor(() =>
      expect(screen.getByTestId('login-error').textContent).toBe('Bitte das Passwort eingeben.'),
    );
  });

  it('says a wrong password inline', async () => {
    renderLogin(() => json(401, { error: 'wrong_password', message: 'Falsches Passwort.' }));
    submit('falsch');
    await waitFor(() => expect(screen.getByTestId('login-error').textContent).toBe('Falsches Passwort.'));
    expect(screen.getByLabelText('Passwort').getAttribute('aria-invalid')).toBe('true');
  });

  it('shows the lockout with the wait in words and blocks the button', async () => {
    renderLogin(() =>
      json(
        429,
        { error: 'login_locked', message: 'Zu viele Fehlversuche. Login ist kurz gesperrt.' },
        { 'Retry-After': '600' },
      ),
    );
    submit('falsch');
    await waitFor(() =>
      expect(screen.getByTestId('login-error').textContent).toMatch(
        /^Zu viele Fehlversuche\. Login ist kurz gesperrt\. Versuch es in 10\u00a0Minuten nochmal \(um \d\d:\d\d\)\.$/,
      ),
    );
    expect(screen.getByTestId('login-submit').hasAttribute('disabled')).toBe(true);
  });
});
