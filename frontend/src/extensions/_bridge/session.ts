/**
 * TEMPORARY stand-in for GP's `@/sdk/session` (wave 2: GP and AC worked in parallel and
 * GP's module was a stub while the camera pages were written). DELETE WHEN GP MERGES:
 * replace the `@/extensions/_bridge/*` imports in src/extensions/beer and booth with
 *   `@/extensions/_bridge/session`   → `@/sdk/session`              (useSession, refreshSession)
 *   `@/extensions/_bridge/share`     → `@/sdk/share`                (saveImage)
 *   `@/extensions/_bridge/GuestPass` → `@/sdk/components/GuestPass` (GuestPass)
 * and delete this folder (`grep -rn _bridge src/`). Same names and signatures.
 *
 * What it does: identifies the device (POST /api/identify with the stored `vb_uid`),
 * keeps paused/stopped/banned in sync with upload answers, rechecks every 30 s while
 * blocked and when the tab comes back. No join sheet: e2e tests join through the API.
 */
import { useSyncExternalStore } from 'react';
import { apiFetch } from '@/api/client';
import { ApiError, isApiError } from '@/api/errors';
import type { IdentifyResponse } from '@/api/types';
import { msg } from '@/lib/messages.de';
import type { SessionState } from '@/sdk/session';
import { subscribeUploadAnswers } from '@/sdk/upload';

export type { SessionState } from '@/sdk/session';
export { canUpload } from '@/sdk/session';

const UID_KEY = 'vb_uid';
const RECHECK_MS = 30_000;

let state: SessionState = { status: 'loading' };
let started = false;
let inflight: Promise<void> | null = null;
let recheck: ReturnType<typeof setInterval> | undefined;
const listeners = new Set<() => void>();

function set(next: SessionState): void {
  state = next;
  for (const listener of listeners) listener();
  syncRecheck();
}

function blocked(): boolean {
  return state.status === 'ready' && (state.user.uploads_paused || state.uploadsStopped);
}

function syncRecheck(): void {
  if (blocked() && recheck === undefined) {
    recheck = setInterval(() => {
      if (document.visibilityState === 'visible') void refreshSession().catch(() => undefined);
    }, RECHECK_MS);
  } else if (!blocked() && recheck !== undefined) {
    clearInterval(recheck);
    recheck = undefined;
  }
}

function storedUid(): string | null {
  try {
    return localStorage.getItem(UID_KEY);
  } catch {
    return null;
  }
}

async function identify(): Promise<void> {
  const uid = storedUid();
  const res = await apiFetch<IdentifyResponse>('/api/identify', {
    method: 'POST',
    json: uid ? { uid } : {},
  });
  if (res.state === 'needs_consent') {
    set({ status: 'needs_join', join: res.consent });
    return;
  }
  try {
    localStorage.setItem(UID_KEY, res.uid_token);
  } catch {
    // private mode: the cookie still works
  }
  set(
    res.state === 'banned' || res.user.banned
      ? { status: 'banned', user: res.user }
      : { status: 'ready', user: res.user, uploadsStopped: res.uploads_stopped },
  );
}

/** Re-identify. A failure keeps a known state (flaky network); only the first one shows. */
export function refreshSession(): Promise<void> {
  inflight ??= identify()
    .catch((err: unknown) => {
      if (state.status === 'loading' || state.status === 'error') {
        set({
          status: 'error',
          error: isApiError(err) ? err : new ApiError(0, 'network', msg.noAnswer),
        });
      }
      throw err;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

function start(): void {
  if (started) return;
  started = true;
  void refreshSession().catch(() => undefined);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && state.status !== 'loading') {
      void refreshSession().catch(() => undefined);
    }
  });
  subscribeUploadAnswers((answer) => {
    if (state.status !== 'ready') {
      if (answer === 'banned' && state.status !== 'banned') void refreshSession().catch(() => undefined);
      return;
    }
    const { user } = state;
    if (answer === 'ok' && (user.uploads_paused || state.uploadsStopped)) {
      set({ status: 'ready', user: { ...user, uploads_paused: false }, uploadsStopped: false });
    } else if (answer === 'uploads_paused') {
      set({ status: 'ready', user: { ...user, uploads_paused: true }, uploadsStopped: state.uploadsStopped });
    } else if (answer === 'uploads_stopped') {
      set({ status: 'ready', user: { ...user, uploads_paused: false }, uploadsStopped: true });
    } else if (answer === 'banned') {
      set({ status: 'banned', user: { ...user, banned: true } });
    }
  });
}

function subscribe(listener: () => void): () => void {
  start();
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function getSnapshot(): SessionState {
  return state;
}

/** The current session (same contract as GP's useSession). */
export function useSession(): SessionState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
