/**
 * The QR codes' query key (under ['admin', …], so `stream.resync` refetches it) and
 * the one cache patch the event stream needs (store/applyEvent.ts `code.changed`).
 */
import type { AdminCode, CodesList } from '@/api/types';
import { sortedCopy } from '../lib/browser';

export const codesKey = ['admin', 'codes'] as const;

export type { AdminCode, CodesList };

/** `list` with `code` replaced (or added, by number), the counts recomputed. */
export function withCode(list: CodesList, code: AdminCode): CodesList {
  const i = list.codes.findIndex((c) => c.id === code.id);
  if (i !== -1 && list.codes[i] === code) return list;
  const codes =
    i === -1
      ? sortedCopy([...list.codes, code], (a, b) => a.id - b.id)
      : list.codes.map((c) => (c.id === code.id ? code : c));
  const active = codes.filter((c) => c.active).length;
  return { ...list, codes, active, revoked: codes.length - active };
}
