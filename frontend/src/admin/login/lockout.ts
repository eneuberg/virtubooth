/** The login lockout in words (lockout.test.ts). */
import { isApiError } from '@/api/client';
import { formatTime } from '@/lib/format';
import { waitInWords } from '../lib/labels';

function serverText(err: unknown): string {
  if (isApiError(err) && err.data && typeof err.data === 'object') {
    const value: unknown = Object.getOwnPropertyDescriptor(err.data, 'message')?.value;
    if (typeof value === 'string' && value) return value;
  }
  return isApiError(err) ? err.message : 'Login fehlgeschlagen.';
}

/** "um 22:53" from one minute on; a few seconds need no clock time. */
function clockText(seconds: number, now: number): string {
  return seconds >= 60 ? ` (um ${formatTime(now + seconds * 1000)})` : '';
}

/**
 * The lockout in one clean sentence pair:
 * - `login_locked` (too many wrong passwords, server-wide): "Zu viele Fehlversuche. Login
 *   ist kurz gesperrt. Versuch es in 12 Minuten nochmal (um 22:53)."
 * - `rate_limited` (too many tries from this address): "Zu viele Versuche
 *   hintereinander. Versuch es in 3 Sekunden nochmal." The server's general text
 *   ("Langsam! … Warte kurz.") would say the wait twice.
 */
export function lockoutText(err: unknown, now = Date.now()): string | null {
  if (!isApiError(err)) return null;
  const wait = err.retryAfter;
  if (err.code === 'rate_limited') {
    const lead = 'Zu viele Versuche hintereinander.';
    return wait
      ? `${lead} Versuch es ${waitInWords(wait)} nochmal${clockText(wait, now)}.`
      : `${lead} Warte kurz und versuch es dann nochmal.`;
  }
  if (err.code !== 'login_locked') return null;
  const base = serverText(err).replace(/\s*$/, '');
  if (!wait) return base;
  return `${base} Versuch es ${waitInWords(wait)} nochmal (um ${formatTime(now + wait * 1000)}).`;
}
