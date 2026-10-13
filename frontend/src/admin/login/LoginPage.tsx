/**
 * /admin/login: one password field. Wrong password and the lockout are said inline
 * (the lockout with the wait in words); afterwards back to `?next=` (validated).
 */
import { LockKeyhole } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { isApiError } from '@/api/client';
import { msg } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { FilmEdge } from '@/ui/FilmEdge';
import { TextField } from '@/ui/TextField';
import { useMediaQuery } from '../lib/browser';
import { safeNext } from '../lib/nav';
import { fetchSession } from '../store/api';
import { login } from '../store/actions';
import { useDocumentSurface } from '../surface';
import { lockoutText } from './lockout';

export function LoginPage() {
  useDocumentSurface('dark');
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
    <main className="mx-auto grid min-h-dvh w-full max-w-[24rem] content-center gap-6 px-6 py-10">
      <div className="grid gap-4">
        <FilmEdge label="Kontaktbogen" end="nur für Gastgeber" holes="both" className="-mx-6 sm:mx-0" />
        <div className="grid gap-2">
          <h1 className="flex items-center gap-2.5 text-2xl font-bold">
            <LockKeyhole aria-hidden="true" className="size-7 text-accent" strokeWidth={2} />
            Admin
          </h1>
          <p className="text-md text-ink-muted">
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
    </main>
  );
}
