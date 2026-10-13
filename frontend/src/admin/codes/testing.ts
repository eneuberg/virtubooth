/** Test data for the QR codes' tests: a code and a list as the server sends them. */
import type { AdminCode, CodesList } from './keys';

export function code(over: Partial<AdminCode> = {}): AdminCode {
  const id = over.id ?? 1;
  return {
    id,
    name: `Gorilla ${id}`,
    animal: 'Gorilla',
    token: `token-of-code-${id}-abcdef`,
    token_gen: 1,
    target: '',
    note: '',
    entry_path: `/?t=token-of-code-${id}-abcdef`,
    active: true,
    created_at: '2026-10-13T20:00:00.000+00:00',
    created_by: 'system',
    updated_at: '2026-10-13T20:00:00.000+00:00',
    revoked_at: null,
    revoked_by: null,
    stats: {
      scans: 0,
      people: 0,
      guests: 0,
      not_joined: 0,
      photos: 0,
      active_now: 0,
      first_scan_at: null,
      last_scan_at: null,
    },
    ...over,
  };
}

export function list(codes: AdminCode[]): CodesList {
  const active = codes.filter((c) => c.active).length;
  return { codes, base_url: null, active, revoked: codes.length - active };
}
