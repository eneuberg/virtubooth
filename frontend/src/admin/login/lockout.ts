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

/** "Zu viele Fehlversuche. Login ist kurz gesperrt. Versuch es in 12 Minuten nochmal (um 22:53)." */
export function lockoutText(err: unknown, now = Date.now()): string | null {
  if (!isApiError(err) || (err.code !== 'login_locked' && err.code !== 'rate_limited')) return null;
  const base = serverText(err).replace(/\s*$/, '');
  if (!err.retryAfter) return base;
  const at = formatTime(now + err.retryAfter * 1000);
  return `${base} Versuch es ${waitInWords(err.retryAfter)} nochmal (um ${at}).`;
}
