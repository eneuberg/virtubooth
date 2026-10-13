import { describe, expect, it } from 'vitest';
import { ApiError } from '@/api/errors';
import {
  changedText,
  checkPasswordForm,
  lockedFilter,
  MISMATCH,
  placeServerError,
  withFilter,
} from './rules';

describe('the password form', () => {
  it('asks for the current password, then for two equal new ones', () => {
    expect(checkPasswordForm('', 'a-new-password-1', 'a-new-password-1')).toEqual({
      current: 'Bitte das aktuelle Passwort eingeben.',
    });
    expect(checkPasswordForm('old-password', 'a-new-password-1', 'a-new-password-2')).toEqual({
      repeat: MISMATCH,
    });
    expect(MISMATCH).toBe('Die beiden neuen Passwörter sind nicht gleich.');
    // the length is the server's rule (one message, one place)
    expect(checkPasswordForm('old-password', 'short', 'short')).toEqual({});
  });

  it('puts each server error at its field', () => {
    const wrong = new ApiError(403, 'wrong_password', 'Das aktuelle Passwort stimmt nicht.');
    expect(placeServerError(wrong)).toEqual({ current: 'Das aktuelle Passwort stimmt nicht.' });
    const short = new ApiError(400, 'password_too_short', 'Das neue Passwort braucht mindestens 12 Zeichen.');
    expect(placeServerError(short)).toEqual({ next: short.message });
    const same = new ApiError(400, 'password_unchanged', 'Das neue Passwort ist dasselbe wie das alte.');
    expect(placeServerError(same)).toEqual({ next: same.message });
    const locked = new ApiError(429, 'login_locked', 'Zu viele Fehlversuche. Login ist kurz gesperrt.');
    expect(placeServerError(locked).form).toMatch(/^Zu viele Fehlversuche\. Login ist kurz gesperrt\./);
    expect(placeServerError(new Error('boom')).form).toBeTruthy();
  });

  it('says how many other devices were logged out', () => {
    expect(changedText(0)).toBe('Passwort geändert.');
    expect(changedText(1)).toBe('Passwort geändert. 1 anderes Gerät abgemeldet.');
    expect(changedText(3)).toBe('Passwort geändert. 3 andere Geräte abgemeldet.');
  });
});

function filter(id: string, enabled: boolean) {
  return { id, name: id, icon: '', enabled };
}

describe('the Fotobox filter switches', () => {
  it('locks the last filter that is on', () => {
    expect(lockedFilter([filter('normal', true), filter('bw', true)])).toBeNull();
    expect(lockedFilter([filter('normal', false), filter('bw', true)])).toBe('bw');
    expect(lockedFilter([])).toBeNull();
  });

  it('switches one filter and keeps the order', () => {
    const data = { filters: [filter('normal', true), filter('bw', true), filter('neon', true)] };
    expect(withFilter(data, 'bw', false).filters.map((f) => [f.id, f.enabled])).toEqual([
      ['normal', true],
      ['bw', false],
      ['neon', true],
    ]);
    expect(data.filters[1]?.enabled).toBe(true);
  });
});
