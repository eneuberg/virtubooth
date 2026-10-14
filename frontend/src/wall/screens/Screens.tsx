/**
 * The wall's full-screen states: login, no password, connecting, empty, offline hint.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { login, WallApiError } from '../api/client';

export function LoginScreen({ onDone, onNoPassword }: { onDone: () => void; onNoPassword: () => void }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => inputRef.current?.focus(), []);

  async function submit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (pending || !password) return;
    setPending(true);
    setError(null);
    try {
      await login(password);
      onDone();
    } catch (err) {
      if (err instanceof WallApiError && err.status === 409) {
        onNoPassword();
        return;
      }
      setError(err instanceof Error ? err.message : 'Das hat nicht geklappt.');
      setPending(false);
      inputRef.current?.select();
    }
  }

  return (
    <div className="wall-screen" data-testid="wall-login">
      <form className="wall-panel" onSubmit={(e) => void submit(e)}>
        <h1 className="wall-title">Live-Wall</h1>
        <label className="wall-field">
          <span>Passwort</span>
          <input
            ref={inputRef}
            className="wall-input"
            type="password"
            name="password"
            autoComplete="current-password"
            maxLength={256}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? 'wall-login-error' : undefined}
          />
        </label>
        {error ? (
          <p className="wall-error" id="wall-login-error" role="alert">
            {error}
          </p>
        ) : null}
        <button className="wall-button" type="submit" disabled={pending || !password}>
          Live-Wall starten
        </button>
      </form>
    </div>
  );
}

export function NoPasswordScreen() {
  return (
    <div className="wall-screen" data-testid="wall-no-password">
      <div className="wall-panel">
        <h1 className="wall-title">Live-Wall</h1>
        <p className="wall-text">Für die Live-Wall ist noch kein Passwort gesetzt.</p>
        <p className="wall-hint">Im Admin unter „Live-Wall“ ein Passwort setzen, dann hier neu laden.</p>
      </div>
    </div>
  );
}

export function ConnectingScreen({ wakeLockHint }: { wakeLockHint: boolean }) {
  return (
    <div className="wall-screen" data-testid="wall-connecting">
      <div className="wall-panel wall-panel--quiet">
        <span className="wall-spinner" aria-hidden="true" />
        <output className="wall-text">Verbinde …</output>
        {wakeLockHint ? <p className="wall-hint">Tipp: Bildschirmschoner am Fernseher ausschalten.</p> : null}
      </div>
    </div>
  );
}

export function EmptyScreen() {
  return (
    <div className="wall-screen" data-testid="wall-empty">
      <div className="wall-empty">
        <span className="wall-empty-icon" aria-hidden="true">
          📸
        </span>
        <p className="wall-empty-title">Noch keine Fotos.</p>
        <p className="wall-text">Die ersten erscheinen hier, sobald jemand knipst.</p>
      </div>
    </div>
  );
}

export function OfflineHint() {
  return (
    <output className="wall-offline" data-testid="wall-offline">
      <span className="wall-offline-dot" aria-hidden="true" />
      Verbindung weg – versuche es weiter …
    </output>
  );
}
