/**
 * Guest session: identify → join → ready / banned, plus the upload gate.
 * Port of vb.js boot() / askConsent() / setInstagram() / the pause recheck
 * (architecture.md §3.2–§3.4), as a small state machine in a zustand store.
 *
 *   loading ──identify──▶ needs_join ──joinParty──▶ ready ⇄ banned
 *      │                     ▲   │ consent_outdated: identify again, new texts
 *      └──fails──▶ error ────┘   └─ invalid_instagram etc.: stays, the sheet shows it
 *
 * - identify sends the device traits and the localStorage copy of `uid_token`
 *   (key `vb_uid`): when the cookie is gone (cleared, ITP), the server still knows
 *   the guest. Every answer with a `uid_token` refreshes that copy.
 * - refreshSession() re-identifies quietly (no loading state, errors keep the old
 *   state) on focus / visibility, every 30 s while paused, stopped or banned, and
 *   after an upload answered 403. From `error` it retries in full.
 * - noteUploadAnswer() lets an upload answer update paused / stopped at once.
 * - While the host stopped joining (`join_closed`), the join sheet says so instead of
 *   offering the button, and the session re-checks quietly (focus, visibility, every
 *   JOIN_RECHECK_MS) until joining is open again.
 * - Every identified answer carries the join texts (`join_text`, the current
 *   version): useJoinText() for "Was passiert mit meinen Fotos?".
 */
import { useEffect } from 'react';
import { useStore } from 'zustand';
import { createStore } from 'zustand/vanilla';
import { api, unwrap } from '@/api/client';
import { ApiError, isApiError, type ApiErrorCode } from '@/api/errors';
import type { ConsentInfo, GuestUser, IdentifyResponse, JoinResponse, KnownGuest } from '@/api/types';
import { msg } from '@/lib/messages.de';
import { debugLog } from './debug';
import { getDeviceTraits } from './device';
import { isOnline } from './platform';

/** What the join sheet shows (the server's join texts). */
export type JoinInfo = ConsentInfo;

export type SessionState =
  | { status: 'loading' }
  | { status: 'needs_join'; join: JoinInfo; joinClosed: boolean }
  | { status: 'ready'; user: GuestUser; uploadsStopped: boolean }
  | { status: 'banned'; user: GuestUser }
  | { status: 'error'; error: ApiError };

/** How the last join went (the sheet says "Du bist schon dabei als …" for a second tab). */
export interface JoinOutcome {
  alreadyJoined: boolean;
  /** the server kept the handle it had and ignored the one typed in this tab */
  instagramKept: boolean;
  user: GuestUser;
}

interface Store {
  session: SessionState;
  outcome: JoinOutcome | null;
  /** the join texts from the last identified answer (null before one came) */
  joinText: JoinInfo | null;
}

export const UID_KEY = 'vb_uid';
/** where wave 2 cached the accepted texts; the server sends them now (removed on sight) */
const OLD_JOIN_TEXT_KEY = 'vb_join_text';
export const RECHECK_MS = 30_000;
export const JOIN_RECHECK_MS = 15_000;
const QUIET_MS = 2_000;

export const sessionStore = createStore<Store>(() => ({
  session: { status: 'loading' },
  outcome: null,
  joinText: null,
}));

// ------------------------------------------------------------------ storage

function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // private mode, blocked storage
  }
}

function writeStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // private mode: the cookie still works
  }
}

function removeStorage(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // blocked storage: nothing to clean up
  }
}

// ------------------------------------------------------------------ state

function set(session: SessionState): void {
  sessionStore.setState({ session });
}

function get(): SessionState {
  return sessionStore.getState().session;
}

function fromIdentified(res: KnownGuest): SessionState {
  writeStorage(UID_KEY, res.uid_token);
  if (res.state === 'banned' || res.user.banned) return { status: 'banned', user: res.user };
  return { status: 'ready', user: res.user, uploadsStopped: res.uploads_stopped };
}

/** The store update for an identify or join answer. */
function applyIdentify(res: IdentifyResponse, outcome?: JoinOutcome): void {
  if (res.state === 'needs_consent') {
    set({ status: 'needs_join', join: res.consent, joinClosed: res.join_closed });
    return;
  }
  removeStorage(OLD_JOIN_TEXT_KEY);
  sessionStore.setState({
    session: fromIdentified(res),
    joinText: res.join_text,
    ...(outcome ? { outcome } : {}),
  });
}

function asApiError(err: unknown): ApiError {
  if (isApiError(err)) return err;
  const wrapped = new ApiError(0, 'client', msg.generic);
  wrapped.cause = err;
  return wrapped;
}

// ---------------------------------------------------------------- identify

let inflight: Promise<void> | null = null;
let started = false;
let lastQuiet = 0;

async function identify(full: boolean): Promise<void> {
  const uid = readStorage(UID_KEY);
  const fp = full ? await getDeviceTraits() : undefined;
  debugLog('identify', full ? 'full' : 'quiet', fp ? fp.hash.slice(0, 12) : '');
  const res = await unwrap(api.POST('/api/identify', { body: { ...(fp ? { fp } : {}), uid } }));
  applyIdentify(res);
}

function run(task: () => Promise<void>): Promise<void> {
  inflight ??= task().finally(() => {
    inflight = null;
  });
  return inflight;
}

/** Starts the session once per page (main.tsx calls it before the first render). */
export function startSession(): Promise<void> {
  if (started) return inflight ?? Promise.resolve();
  started = true;
  installRechecks();
  return run(async () => {
    try {
      await identify(true);
    } catch (err) {
      set({ status: 'error', error: asApiError(err) });
    }
  });
}

/**
 * Re-identify. Ready / banned: quietly (the state stays on errors, e.g. offline).
 * Error: a full retry through `loading`. Needs-join: fetches the join texts again.
 */
export function refreshSession(): Promise<void> {
  if (!started) return startSession();
  return run(async () => {
    const s = get();
    if (s.status === 'error') set({ status: 'loading' });
    const quiet = s.status === 'ready' || s.status === 'banned' || joinClosed(s);
    try {
      await identify(!quiet);
    } catch (err) {
      if (!quiet) set({ status: 'error', error: asApiError(err) });
      else debugLog('recheck failed', String(err));
    }
  });
}

/** The current session (useSyncExternalStore over the store); starts it on first use. */
export function useSession(): SessionState {
  useEffect(() => {
    void startSession();
  }, []);
  return useStore(sessionStore, (s) => s.session);
}

/** The outcome of the last join in this tab (null before). */
export function useJoinOutcome(): JoinOutcome | null {
  return useStore(sessionStore, (s) => s.outcome);
}

/** True while the host stopped joining and this device has not joined. */
export function useJoinClosed(): boolean {
  return useStore(sessionStore, (s) => joinClosed(s.session));
}

/** The join texts for a joined guest to read again (null until identified). */
export function useJoinText(): JoinInfo | null {
  return useStore(sessionStore, (s) => s.joinText);
}

/** The current state outside React. */
export function getSession(): SessionState {
  return get();
}

// ------------------------------------------------------------------ actions

/**
 * POST /api/join with the version of the texts the guest saw, the optional
 * Instagram name, „Meine Fotos nicht automatisch auswerten“ (`analysisOptOut`) and
 * „Keine Weitergabe an externe KI“ (`aiOptOut`).
 * Rejects with the ApiError (the sheet shows its message).
 * `consent_outdated`: the texts changed meanwhile; the session identifies again, so
 * the sheet shows the new texts (or closes when another tab joined), then rejects.
 */
export async function joinParty(input: {
  instagram: string | null;
  analysisOptOut?: boolean;
  aiOptOut?: boolean;
}): Promise<void> {
  const s = get();
  if (s.status !== 'needs_join') return;
  const fp = await getDeviceTraits();
  const instagram = input.instagram?.trim() || null;
  const analysis_opt_out = input.analysisOptOut ?? false;
  const ai_opt_out = input.aiOptOut ?? false;
  let res: JoinResponse;
  try {
    res = await unwrap(
      api.POST('/api/join', {
        body: { accept: true, version: s.join.version, instagram, fp, analysis_opt_out, ai_opt_out },
      }),
    );
  } catch (err) {
    if (isApiError(err) && err.code === 'consent_outdated') {
      try {
        await identify(true);
      } catch {
        // keep the old texts; the next try reports the problem
      }
    }
    const now = get();
    if (isApiError(err) && err.code === 'join_closed' && now.status === 'needs_join') {
      set({ ...now, joinClosed: true });
    }
    throw err;
  }
  applyIdentify(res, {
    alreadyJoined: res.already_joined,
    instagramKept: res.instagram_kept,
    user: res.user,
  });
}

/** Runs a /api/me change and puts the answer's user into the session. */
async function changeMe(request: () => Promise<{ user: GuestUser }>): Promise<GuestUser> {
  try {
    const { user } = await request();
    const s = get();
    if (s.status === 'ready') set({ ...s, user });
    else if (s.status === 'banned') set({ ...s, user });
    return user;
  } catch (err) {
    if (isApiError(err) && (err.code === 'banned' || err.code === 'needs_consent')) void refreshSession();
    throw err;
  }
}

/** PATCH /api/me; null or blank clears the name. Rejects with the ApiError. */
export function setInstagram(handle: string | null): Promise<GuestUser> {
  const instagram = handle?.trim().replace(/^@+/, '') || null;
  return changeMe(() => unwrap(api.PATCH('/api/me', { body: { instagram } })));
}

/**
 * PATCH /api/me with only `display_name`: the name others see (null or blank: back to
 * the default, the Instagram name or the random name). Rejects with the ApiError
 * (`invalid_display_name`, `display_name_taken`: the sheet shows its message).
 */
export function setDisplayName(name: string | null): Promise<GuestUser> {
  const display_name = name?.trim() || null;
  return changeMe(() => unwrap(api.PATCH('/api/me', { body: { display_name } })));
}

/**
 * PUT /api/me/analysis: „Meine Fotos nicht automatisch auswerten“ on (true) or off.
 * Rejects with the ApiError.
 */
export function setAnalysisOptOut(optOut: boolean): Promise<GuestUser> {
  return changeMe(() => unwrap(api.PUT('/api/me/analysis', { body: { opt_out: optOut } })));
}

/** PUT /api/me/external-ai: „Keine Weitergabe an externe KI“ on (true) or off. */
export function setExternalAiOptOut(optOut: boolean): Promise<GuestUser> {
  return changeMe(() => unwrap(api.PUT('/api/me/external-ai', { body: { opt_out: optOut } })));
}

/**
 * What an upload answer says about the gate (call it for every answer, AC's
 * upload.ts does): 'ok' clears paused and stopped; `uploads_paused` /
 * `uploads_stopped` set them at once and the session re-checks; `banned` and
 * `needs_consent` re-identify.
 */
export function noteUploadAnswer(code: 'ok' | ApiErrorCode): void {
  const s = get();
  if (code === 'banned' || code === 'needs_consent') {
    void refreshSession();
    return;
  }
  if (s.status !== 'ready') return;
  if (code === 'ok') {
    if (s.user.uploads_paused || s.uploadsStopped) {
      set({ ...s, user: { ...s.user, uploads_paused: false }, uploadsStopped: false });
    }
  } else if (code === 'uploads_paused') {
    set({ ...s, user: { ...s.user, uploads_paused: true } });
    void refreshSession();
  } else if (code === 'uploads_stopped') {
    set({ ...s, user: { ...s.user, uploads_paused: false }, uploadsStopped: true });
    void refreshSession();
  }
}

/**
 * Whether the guest may upload right now, and why not. Precedence as on the server
 * (architecture.md §5): banned > paused (this guest) > stopped (everyone).
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

// ------------------------------------------------------------------ rechecks

function joinClosed(s: SessionState): boolean {
  return s.status === 'needs_join' && s.joinClosed;
}

function blocked(s: SessionState): boolean {
  return s.status === 'banned' || (s.status === 'ready' && (s.user.uploads_paused || s.uploadsStopped));
}

/**
 * Focus, visibility, back online: a quick re-identify (not while the join sheet is up,
 * unless joining is closed: then it checks whether it opened again).
 */
function onWake(): void {
  if (document.visibilityState === 'hidden') return;
  const s = get();
  if ((s.status === 'needs_join' && !s.joinClosed) || s.status === 'loading') return;
  if (s.status === 'error' && !isOnline()) return;
  const now = Date.now();
  if (now - lastQuiet < QUIET_MS) return;
  lastQuiet = now;
  void refreshSession();
}

let installed = false;

function installRechecks(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  document.addEventListener('visibilitychange', onWake);
  window.addEventListener('focus', onWake);
  window.addEventListener('online', onWake);
  setInterval(() => {
    if (document.visibilityState !== 'hidden' && blocked(get())) void refreshSession();
  }, RECHECK_MS);
  setInterval(() => {
    if (document.visibilityState !== 'hidden' && joinClosed(get())) void refreshSession();
  }, JOIN_RECHECK_MS);
}

/** Back to the start (tests only). */
export function resetSession(): void {
  started = false;
  inflight = null;
  lastQuiet = 0;
  sessionStore.setState({ session: { status: 'loading' }, outcome: null, joinText: null });
}
