/**
 * /admin/login: one password field. Wrong password and the lockout are said inline
 * (the lockout with the wait in words); afterwards back to `?next=` (validated). One
 * white card on the light surface, like the manage area.
 */
import { LockKeyhole } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { isApiError } from '@/api/client';
import { msg } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { TextField } from '@/ui/TextField';
import { useMediaQuery } from '../lib/browser';
import { safeNext } from '../lib/nav';
import { fetchSession } from '../store/api';
import { login } from '../store/actions';
import { lockoutText } from './lockout';

export function LoginPage() {
  const next = safeNext(new URLSearchParams(location.search).get('next'));
  const desktop = useMediaQuery('(pointer: fine)');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [welcome, setWelcome] = useState(false);
  const [lockedUntil, setLockedUntil] = useState<number | null>(null);
  const input = useRef<HTMLInputElement>(null);

  // already signed in: straight on
  useEffect(() => {
    let alive = true;
    fetchSession().then(
      (ok) => {
        if (ok && alive) location.replace(next);
      },
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [next]);

  useEffect(() => {
    if (lockedUntil === null) return undefined;
    const timer = window.setTimeout(() => setLockedUntil(null), Math.max(0, lockedUntil - Date.now()));
    return () => window.clearTimeout(timer);
  }, [lockedUntil]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || lockedUntil !== null) return;
    if (!password) {
      setError('Bitte das Passwort eingeben.');
      input.current?.focus();
      return;
    }
    setPending(true);
    setError(null);
    try {
      await login(password);
      setWelcome(true);
      location.replace(next);
    } catch (err) {
      const locked = lockoutText(err);
      setError(locked ?? (isApiError(err) ? err.message : msg.generic));
      if (locked && isApiError(err) && err.retryAfter) setLockedUntil(Date.now() + err.retryAfter * 1000);
      setPending(false);
      input.current?.select();
    }
  };

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="grid w-full max-w-[24rem] gap-6 rounded-card border border-line bg-surface-raised p-6 sm:p-8">
        <div className="grid gap-3">
          <span
            aria-hidden="true"
            className="grid size-11 place-items-center rounded-control bg-surface-sunk text-ink"
          >
            <LockKeyhole className="size-5.5" strokeWidth={2} />
          </span>
          <div className="grid gap-1">
            <h1 className="text-xl font-bold">Admin</h1>
            <p className="text-sm text-ink-muted">
              Moderation für die Party: Fotos ausblenden, Gäste verwalten.
            </p>
          </div>
        </div>
        <form noValidate onSubmit={(e) => void submit(e)} className="grid gap-4" data-testid="login-form">
          <TextField
            id="password"
            name="password"
            label="Passwort"
            type="password"
            autoComplete="current-password"
            maxLength={256}
            autoFocus={desktop}
            value={password}
            onChange={(value) => {
              setPassword(value);
              if (lockedUntil === null) setError(null);
            }}
            errorMessage={error}
            inputRef={input}
          />
          <p role="alert" className="sr-only" data-testid="login-error">
            {error ?? ''}
          </p>
          <Button
            type="submit"
            variant="primary"
            size="lg"
            block
            isPending={pending}
            pendingLabel="Prüfe…"
            isDisabled={lockedUntil !== null}
            data-testid="login-submit"
          >
            {welcome ? 'Willkommen!' : 'Anmelden'}
          </Button>
        </form>
      </div>
    </main>
  );
}
