import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { auditAction, auditDetails, auditTarget } from '../lib/labels';
import { parseCodeParam } from '../manage/manageUrl';
import { applyAdminEvent } from '../store/applyEvent';
import { codesKey, withCode, type CodesList } from './keys';
import { code, list } from './testing';

describe('withCode', () => {
  it('replaces a code and recounts', () => {
    const before = list([code({ id: 1 }), code({ id: 2 })]);
    const revoked = code({ id: 2, active: false, revoked_at: '2026-10-13T21:00:00.000+00:00' });
    const after = withCode(before, revoked);
    expect(after.codes.map((c) => c.active)).toEqual([true, false]);
    expect([after.active, after.revoked]).toEqual([1, 1]);
    expect(before.codes[1]?.active).toBe(true); // a copy
  });

  it('adds a new code in number order', () => {
    const after = withCode(list([code({ id: 1 }), code({ id: 4 })]), code({ id: 3 }));
    expect(after.codes.map((c) => c.id)).toEqual([1, 3, 4]);
    expect(after.active).toBe(3);
  });

  it('keeps the same object when nothing changed', () => {
    const one = code();
    const before = list([one]);
    expect(withCode(before, one)).toBe(before);
  });
});

describe('the code.changed event', () => {
  it('patches the cached list', () => {
    const qc = new QueryClient();
    qc.setQueryData(codesKey, list([code({ id: 1 })]));
    const invalidated: unknown[] = [];
    applyAdminEvent(
      {
        type: 'code.changed',
        id: 'abcd1234-2',
        data: { code: code({ id: 2, note: 'Bar' }), change: 'created' },
      },
      { qc, invalidate: (keys) => invalidated.push(...keys) },
    );
    const cached = qc.getQueryData<CodesList>(codesKey);
    expect(cached?.codes.map((c) => c.id)).toEqual([1, 2]);
    expect(cached?.codes[1]?.note).toBe('Bar');
    expect(invalidated).toEqual([codesKey, ['admin', 'audit']]);
  });

  it('leaves an empty cache alone', () => {
    const qc = new QueryClient();
    applyAdminEvent(
      { type: 'code.changed', id: 'abcd1234-3', data: { code: code(), change: 'edited' } },
      { qc, invalidate: () => undefined },
    );
    expect(qc.getQueryData(codesKey)).toBeUndefined();
  });
});

describe('links and the audit log', () => {
  it('reads the code deep link', () => {
    expect(parseCodeParam(new URLSearchParams('tab=qr&code=12'))).toBe(12);
    expect(parseCodeParam(new URLSearchParams('tab=qr&code=0'))).toBeNull();
    expect(parseCodeParam(new URLSearchParams('tab=qr&code=x'))).toBeNull();
    expect(parseCodeParam(new URLSearchParams('tab=qr'))).toBeNull();
  });

  it('names code entries', () => {
    expect(auditTarget('code:3')).toEqual({ kind: 'code', id: 3 });
    expect(auditTarget('code:x')).toEqual({ kind: 'text', text: 'code:x' });
    expect(auditAction('code.create')).toBe('QR-Code angelegt');
    expect(auditAction('code.token')).toBe('QR-Token geändert');
    expect(
      auditDetails({
        details: { name: 'Gorilla 2', target: '', note: 'Bar', token: 'erzeugt', token_end: 'x9_Q' },
      }),
    ).toBe('Name: Gorilla 2, Ziel: –, Notiz: Bar, Token: erzeugt, Token endet auf: x9_Q');
  });
});
