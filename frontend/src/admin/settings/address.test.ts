import { describe, expect, it } from 'vitest';
import type { AddressCheck } from './api';
import { addressIsFine, checkIsStale } from './api';
import { addressStatus } from './address';

const at = '2026-10-15T19:14:00.000Z';
const check = (over: Partial<AddressCheck>): AddressCheck => ({
  status: 'ok',
  url: 'https://party.example.com',
  at,
  message: 'Erreichbar.',
  ...over,
});

describe('public address status', () => {
  it('names each state in German', () => {
    expect(addressStatus(check({})).text).toMatch(/^Erreichbar ✓ – geprüft \d\d:14$/);
    const down = addressStatus(check({ status: 'unreachable', message: 'Verbindung abgelehnt.' }));
    expect(down.text).toBe('Nicht erreichbar – QR-Codes würden ins Leere führen.');
    expect(down.detail).toMatch(/^Verbindung abgelehnt\. – geprüft \d\d:14$/);
    expect(down.tone).toBe('warn');
    expect(addressStatus(check({ status: 'mismatch' })).text).toBe(
      'Antwortet, ist aber nicht diese Fotobox.',
    );
    expect(addressStatus(check({ status: 'unchecked', at: null })).text).toBe('Noch nicht geprüft.');
    expect(addressStatus(check({ status: 'auto', url: null, at: null })).tone).toBe('muted');
  });

  it('says when printing is safe and when a check is stale', () => {
    expect(addressIsFine(check({}))).toBe(true);
    expect(addressIsFine(check({ status: 'auto' }))).toBe(true);
    expect(addressIsFine(check({ status: 'unchecked' }))).toBe(false);
    expect(addressIsFine(check({ status: 'mismatch' }))).toBe(false);
    const now = new Date(at).getTime();
    expect(checkIsStale(check({}), now + 9 * 60_000)).toBe(false);
    expect(checkIsStale(check({}), now + 11 * 60_000)).toBe(true);
    expect(checkIsStale(check({ at: null, status: 'unchecked' }), now)).toBe(true);
    expect(checkIsStale(check({ status: 'auto', at: null }), now)).toBe(false);
  });
});
