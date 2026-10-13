/**
 * Guest session: identify → join → ready/banned, plus the upload gate.
 * OWNER: wave 2 "GP" (guest platform). Interface fixed by PLAN §4; bodies are TODO.
 * Port of vb.js boot()/identify/join/setInstagram (architecture.md §3.2–§3.4).
 */
import type { ApiError } from '@/api/errors';
import type { ConsentInfo, GuestUser } from '@/api/types';
import { msg } from '@/lib/messages.de';

/** What the join sheet shows (the server's consent texts). */
export type JoinInfo = ConsentInfo;

export type SessionState =
  | { status: 'loading' }
  | { status: 'needs_join'; join: JoinInfo }
  | { status: 'ready'; user: GuestUser; uploadsStopped: boolean }
  | { status: 'banned'; user: GuestUser }
  | { status: 'error'; error: ApiError };

const TODO = (what: string) => new Error(`TODO(wave 2, GP): sdk/session ${what}`);

/** The current session (useSyncExternalStore over a module store). */
export function useSession(): SessionState {
  // TODO(wave 2, GP): identify on first use (POST /api/identify with device traits + stored uid)
  return { status: 'loading' };
}

/** Re-identify (after visibility change, every 30 s while paused/stopped, after upload answers). */
export function refreshSession(): Promise<void> {
  return Promise.reject(TODO('refreshSession'));
}

/** POST /api/join with the consent version and the optional Instagram name. */
export function joinParty(input: { instagram: string | null }): Promise<void> {
  void input;
  return Promise.reject(TODO('joinParty'));
}

/** PATCH /api/me; null or blank clears the name. */
export function setInstagram(handle: string | null): Promise<GuestUser> {
  void handle;
  return Promise.reject(TODO('setInstagram'));
}

/**
 * Whether the guest may upload right now, and why not. Precedence as on the server
 * (architecture.md §5): banned > paused (this guest) > stopped (everyone).
 * Implemented already: pure, and the camera pages need it from day one.
 */
export function canUpload(
  s: SessionState,
): { ok: true } | { ok: false; reason: 'paused' | 'stopped' | 'banned' | 'not_ready'; message: string } {
  if (s.status === 'banned' || (s.status === 'ready' && s.user.banned)) {
    return { ok: false, reason: 'banned', message: msg.bannedShort };
  }
  if (s.status !== 'ready') return { ok: false, reason: 'not_ready', message: msg.generic };
  if (s.user.uploads_paused) return { ok: false, reason: 'paused', message: msg.pausedText };
  if (s.uploadsStopped) return { ok: false, reason: 'stopped', message: msg.stoppedText };
  return { ok: true };
}
