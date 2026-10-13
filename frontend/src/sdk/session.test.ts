import { describe, expect, it } from 'vitest';
import type { GuestUser } from '@/api/types';
import { canUpload, type SessionState } from './session';

const user = (over: Partial<GuestUser> = {}): GuestUser => ({
  name: 'Verrückte Ente',
  instagram: null,
  banned: false,
  uploads_paused: false,
  ...over,
});

describe('canUpload', () => {
  it('allows a ready guest', () => {
    expect(canUpload({ status: 'ready', user: user(), uploadsStopped: false })).toEqual({ ok: true });
  });

  it('follows the server precedence: banned > paused > stopped', () => {
    const both: SessionState = {
      status: 'ready',
      user: user({ uploads_paused: true }),
      uploadsStopped: true,
    };
    expect(canUpload(both)).toMatchObject({ ok: false, reason: 'paused' });
    const banned: SessionState = { status: 'banned', user: user({ banned: true, uploads_paused: true }) };
    expect(canUpload(banned)).toMatchObject({ ok: false, reason: 'banned' });
    expect(canUpload({ status: 'ready', user: user(), uploadsStopped: true })).toMatchObject({
      ok: false,
      reason: 'stopped',
    });
  });

  it('is not ready while loading or joining', () => {
    expect(canUpload({ status: 'loading' })).toMatchObject({ ok: false, reason: 'not_ready' });
  });
});
