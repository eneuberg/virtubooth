/**
 * The Einstellungen section's rules and copy that need no React (rules.test.ts): the
 * password form's checks and texts, the Fotobox filter switches.
 */
import { isApiError } from '@/api/client';
import { errorText } from '../common/usePhotoActions';
import { lockoutText } from '../login/lockout';
import type { BoothFilterSettings } from './api';

// --------------------------------------------------------------- password

export const MISMATCH = 'Die beiden neuen Passwörter sind nicht gleich.';
const NO_CURRENT = 'Bitte das aktuelle Passwort eingeben.';

export type PasswordField = 'current' | 'next' | 'repeat';
export type PasswordErrors = Partial<Record<PasswordField | 'form', string>>;

/** What the browser checks before asking the server. */
export function checkPasswordForm(current: string, next: string, repeat: string): PasswordErrors {
  if (!current) return { current: NO_CURRENT };
  if (next !== repeat) return { repeat: MISMATCH };
  return {};
}

/** Where a server error belongs: the field it is about, else under the form. */
export function placeServerError(err: unknown): PasswordErrors {
  const locked = lockoutText(err);
  if (locked) return { form: locked };
  if (isApiError(err) && err.code === 'wrong_password') return { current: err.message };
  if (isApiError(err) && (err.code === 'password_too_short' || err.code === 'password_unchanged')) {
    return { next: err.message };
  }
  return { form: errorText(err) };
}

/** "Passwort geändert. 2 andere Geräte abgemeldet." */
export function changedText(ended: number): string {
  if (ended === 0) return 'Passwort geändert.';
  return `Passwort geändert. ${ended === 1 ? '1 anderes Gerät' : `${ended} andere Geräte`} abgemeldet.`;
}

// ---------------------------------------------------------- booth filters

export const LAST_ONE = 'Mindestens ein Filter bleibt an.';

/** The filter that must stay on (the only one left), else null. */
export function lockedFilter(filters: ReadonlyArray<{ id: string; enabled: boolean }>): string | null {
  const on = filters.filter((f) => f.enabled);
  return on.length === 1 && on[0] ? on[0].id : null;
}

/** The settings after switching one filter. */
export function withFilter(data: BoothFilterSettings, id: string, enabled: boolean): BoothFilterSettings {
  return { filters: data.filters.map((f) => (f.id === id ? { ...f, enabled } : f)) };
}
