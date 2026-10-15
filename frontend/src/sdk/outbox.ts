/**
 * The shared outbox ("never lose a shot", PLAN §1). OWNER: wave 2 "AC".
 *
 * Every photo goes into the outbox BEFORE its first upload and leaves it only when the
 * server has it (or can never take it). So a failed upload, a reload, a closed tab or
 * the back button never lose a shot; the outbox sends what waits on `online`, when the
 * tab becomes visible, every 30 s while something waits, and when the app starts.
 *
 * Storage: IndexedDB `vb-booth` v1, store `outbox` (keyPath `id`), records
 * `{id, ext, meta, at, type, data: Blob | ArrayBuffer}`: the pre-overhaul Fotobox
 * schema plus `ext`. Old records without `ext` are Fotobox photos. WebKit versions that
 * can't store Blobs get the bytes (ArrayBuffer). Without IndexedDB (private mode, some
 * in-app WebViews, storage full) photos are kept in memory only (`stored: false`) and
 * the pages warn before leaving.
 */
import { useSyncExternalStore } from 'react';
import { ApiError } from '@/api/errors';
import {
  GATE_CODES,
  isPermanentUploadError,
  retryAfterSeconds,
  subscribeUploadAnswers,
  uploadPhoto,
  type UploadMeta,
  type UploadResult,
} from './upload';

export type OutboxState =
  /** just taken, first upload running (not "waiting" yet) */
  | 'new'
  /** a retry is running */
  | 'sending'
  /** failed for a reason that passes (network, server, rate limit): retried automatically */
  | 'waiting'
  /** the guest may not upload right now (paused, stopped, banned): kept until allowed */
  | 'held';

export interface OutboxItem {
  id: string;
  /** extension id, e.g. "booth", "beer" */
  ext: string;
  meta: UploadMeta;
  /** epoch ms when taken */
  at: number;
  blob: Blob;
  /** the unfiltered original (Fotobox with a filter), sent with the photo */
  raw: Blob | null;
  state: OutboxState;
  /** on disk (IndexedDB); false: memory only, lost with the tab */
  stored: boolean;
  /** kept from an earlier visit */
  resumed: boolean;
  error: ApiError | null;
  /** rate limited: no retry before this (epoch ms) */
  waitUntil: number;
}

export type OutboxEvent =
  | { type: 'sent'; item: OutboxItem; result: UploadResult }
  | { type: 'failed'; item: OutboxItem; error: ApiError }
  | { type: 'dropped'; item: OutboxItem; error: ApiError };

// ------------------------------------------------------------------ storage

/** The DB record (the shape `test_booth_e2e.py` and older phones know). */
export interface OutboxRecord {
  id: string;
  ext?: string;
  meta: UploadMeta;
  at: number;
  type: string;
  data: Blob | ArrayBuffer;
  /** the unfiltered original (newer records only) */
  raw?: Blob | ArrayBuffer | null;
}

export interface OutboxStore {
  put(record: OutboxRecord): Promise<void>;
  delete(id: string): Promise<void>;
  getAll(): Promise<OutboxRecord[]>;
}

export const DB_NAME = 'vb-booth';
export const DB_VERSION = 1;
export const STORE = 'outbox';
/** Records from before the overhaul were all Fotobox photos. */
export const LEGACY_EXT = 'booth';

export function toRecord(
  item: Pick<OutboxItem, 'id' | 'ext' | 'meta' | 'at' | 'blob'> & { raw?: Blob | null },
): OutboxRecord {
  const record: OutboxRecord = {
    id: item.id,
    ext: item.ext,
    meta: item.meta,
    at: item.at,
    type: item.blob.type || 'image/jpeg',
    data: item.blob,
  };
  if (item.raw) record.raw = item.raw;
  return record;
}

function isMeta(value: unknown): value is UploadMeta {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/** A stored record as an item, or null when it is broken. Old records get the Fotobox. */
export function fromRecord(value: unknown): OutboxItem | null {
  if (!value || typeof value !== 'object') return null;
  const r = value as Partial<OutboxRecord>;
  if (typeof r.id !== 'string' || !r.id || !isMeta(r.meta) || !r.data) return null;
  const type = typeof r.type === 'string' && r.type ? r.type : 'image/jpeg';
  const blob = r.data instanceof Blob ? r.data : new Blob([r.data], { type });
  const raw =
    r.raw instanceof Blob
      ? r.raw
      : r.raw instanceof ArrayBuffer
        ? new Blob([r.raw], { type: 'image/jpeg' })
        : null;
  return {
    id: r.id,
    ext: typeof r.ext === 'string' && r.ext ? r.ext : LEGACY_EXT,
    meta: r.meta,
    at: typeof r.at === 'number' ? r.at : 0,
    blob,
    raw,
    state: 'waiting',
    stored: true,
    resumed: true,
    error: null,
    waitUntil: 0,
  };
}

function idbStore(): OutboxStore | null {
  if (typeof indexedDB === 'undefined' || !indexedDB) return null;
  let dbPromise: Promise<IDBDatabase> | null = null;
  const open = () => {
    dbPromise ??= new Promise<IDBDatabase>((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.addEventListener('upgradeneeded', () => {
        if (!req.result.objectStoreNames.contains(STORE))
          req.result.createObjectStore(STORE, { keyPath: 'id' });
      });
      req.addEventListener('success', () => resolve(req.result));
      req.addEventListener('error', () => reject(req.error ?? new Error('IndexedDB open failed')));
      req.addEventListener('blocked', () => reject(new Error('IndexedDB blocked')));
    }).catch((err: unknown) => {
      dbPromise = null; // try again next time
      throw err;
    });
    return dbPromise;
  };
  const run = async <T>(
    mode: IDBTransactionMode,
    fn: (store: IDBObjectStore) => IDBRequest<T>,
  ): Promise<T> => {
    const db = await open();
    return new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      let result: T | undefined;
      const req = fn(tx.objectStore(STORE)); // may throw (DataCloneError): rejects
      req.addEventListener('success', () => {
        result = req.result;
      });
      // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- set by the request's success before complete
      tx.addEventListener('complete', () => resolve(result as T));
      tx.addEventListener('error', () => reject(tx.error ?? new Error('IndexedDB error')));
      tx.addEventListener('abort', () => reject(tx.error ?? new Error('IndexedDB aborted')));
    });
  };
  return {
    async put(record) {
      await run('readwrite', (s) => s.put(record));
    },
    async delete(id) {
      await run('readwrite', (s) => s.delete(id));
    },
    async getAll() {
      const all: unknown[] = await run('readonly', (s) => s.getAll());
      // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- validated by fromRecord
      return all as OutboxRecord[];
    },
  };
}

let store: OutboxStore | null | undefined;

function getStore(): OutboxStore | null {
  if (store === undefined) {
    try {
      store = idbStore();
    } catch {
      store = null;
    }
  }
  return store;
}

/** Tests: swap the storage (null = none). Resets the in-memory state. */
export function setOutboxStore(next: OutboxStore | null | undefined): void {
  store = next;
  resetOutbox();
}

async function persist(item: OutboxItem): Promise<boolean> {
  const s = getStore();
  if (!s) return false;
  const record = toRecord(item);
  try {
    await s.put(record);
    return true;
  } catch {
    // some WebKit versions can't store Blobs: the bytes then
    try {
      await s.put({
        ...record,
        data: await item.blob.arrayBuffer(),
        ...(item.raw ? { raw: await item.raw.arrayBuffer() } : {}),
      });
      return true;
    } catch {
      return false;
    }
  }
}

async function unpersist(id: string): Promise<void> {
  try {
    await getStore()?.delete(id);
  } catch {
    // stays on disk; the next visit sends it (the server may then get it twice)
  }
}

// -------------------------------------------------------------- the queue

const items = new Map<string, OutboxItem>();
const inFlight = new Set<string>();
const listeners = new Set<() => void>();
const eventListeners = new Set<(e: OutboxEvent) => void>();
let snapshot: { pending: number; atRisk: number; items: ReadonlyArray<OutboxItem> } = {
  pending: 0,
  atRisk: 0,
  items: [],
};
let installed = false;
let loaded: Promise<void> | null = null;
/** the last answer said "you may not upload": automatic flushes wait for an explicit one */
let gateClosed = false;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let flushing: Promise<number> | null = null;

/** Oldest first. Sorts the (fresh) array in place: toSorted() is missing in Firefox ≤ 114, a build target. */
function byAge(list: OutboxItem[]): OutboxItem[] {
  // oxlint-disable-next-line unicorn/no-array-sort -- a fresh copy; see above
  return list.sort((a, b) => a.at - b.at);
}

/** Retry automatically this often while something waits. */
export const RETRY_EVERY_MS = 30_000;

function emitChange(): void {
  const list = byAge([...items.values()]);
  snapshot = {
    pending: list.filter((i) => i.state !== 'new').length,
    atRisk: list.filter((i) => !i.stored).length,
    items: list,
  };
  for (const listener of listeners) listener();
  scheduleRetry();
}

function emit(event: OutboxEvent): void {
  for (const listener of eventListeners) {
    try {
      listener(event);
    } catch {
      // ignore a listener's bug
    }
  }
}

function update(id: string, patch: Partial<OutboxItem>): OutboxItem | null {
  const item = items.get(id);
  if (!item) return null;
  const next = { ...item, ...patch };
  items.set(id, next);
  emitChange();
  return next;
}

function scheduleRetry(): void {
  if (typeof window === 'undefined') return;
  clearTimeout(retryTimer);
  retryTimer = undefined;
  const waiting = [...items.values()].filter((i) => i.state === 'waiting');
  if (!installed || waiting.length === 0) return;
  const now = Date.now();
  const soonest = Math.min(...waiting.map((i) => Math.max(i.waitUntil - now, 0)));
  const delay = soonest > 0 ? soonest + 250 : RETRY_EVERY_MS;
  retryTimer = setTimeout(() => {
    retryTimer = undefined;
    if (document.visibilityState === 'visible') void flushOutbox();
    else scheduleRetry();
  }, delay);
}

/** A fresh id for a shot. */
export function newShotId(): string {
  const random = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2, 12);
  return `${Date.now().toString(36)}-${random}`;
}

/**
 * Stores a photo before it is sent; resolves whether it is on disk (false: kept in
 * memory only, so the page should warn before leaving).
 */
export async function addToOutbox(item: {
  id: string;
  ext: string;
  meta: UploadMeta;
  blob: Blob;
  raw?: Blob | null;
  at?: number;
}): Promise<boolean> {
  const entry: OutboxItem = {
    id: item.id,
    ext: item.ext,
    meta: item.meta,
    at: item.at ?? Date.now(),
    blob: item.blob,
    raw: item.raw ?? null,
    state: 'new',
    stored: false,
    resumed: false,
    error: null,
    waitUntil: 0,
  };
  items.set(entry.id, entry);
  emitChange();
  const stored = await persist(entry);
  if (items.has(entry.id)) {
    update(entry.id, { stored });
  } else if (stored) {
    void unpersist(entry.id); // sent (or dropped) while it was being written
  }
  return stored;
}

/** Forgets a photo for good (sent elsewhere, or the guest discarded it). */
export async function removeFromOutbox(id: string): Promise<void> {
  if (items.delete(id)) emitChange();
  await unpersist(id);
}

/**
 * Uploads one photo of the outbox now (the page's own upload, with progress). Resolves
 * the server's answer; rejects with the ApiError. The outbox keeps or drops the photo
 * by the error: gone for good on a permanent refusal, kept otherwise.
 */
export async function sendFromOutbox(
  id: string,
  options: { onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<UploadResult> {
  const item = items.get(id);
  if (!item) throw new ApiError(0, 'not_found', 'Dieses Foto ist nicht mehr da.');
  if (inFlight.has(id)) throw new ApiError(0, 'busy', 'Dieses Foto wird gerade gesendet.');
  inFlight.add(id);
  if (item.state !== 'new') update(id, { state: 'sending', error: null });
  try {
    const result = await uploadPhoto(item.ext, item.blob, {
      meta: item.meta,
      raw: item.raw,
      ...(options.onProgress ? { onProgress: options.onProgress } : {}),
      ...(options.signal ? { signal: options.signal } : {}),
    });
    const sent = items.get(id) ?? item;
    items.delete(id);
    emitChange();
    void unpersist(id);
    gateClosed = false;
    emit({ type: 'sent', item: sent, result });
    return result;
  } catch (err) {
    const error = err instanceof ApiError ? err : null;
    if (!error) {
      // aborted: back to waiting, the next flush sends it
      update(id, { state: 'waiting' });
      throw err;
    }
    const current = items.get(id) ?? item;
    if (isPermanentUploadError(error)) {
      items.delete(id);
      emitChange();
      void unpersist(id);
      emit({ type: 'dropped', item: current, error });
    } else {
      const held = GATE_CODES.has(error.code);
      if (held) gateClosed = true;
      const wait = retryAfterSeconds(error);
      const next = update(id, {
        state: held ? 'held' : 'waiting',
        error,
        waitUntil: wait ? Date.now() + wait * 1000 : 0,
      });
      emit({ type: 'failed', item: next ?? current, error });
    }
    throw error;
  } finally {
    inFlight.delete(id);
  }
}

/** Reads what earlier visits kept (once per page load). */
function loadStored(): Promise<void> {
  loaded ??= (async () => {
    const s = getStore();
    if (!s) return;
    let records: unknown[] = [];
    try {
      records = await s.getAll();
    } catch {
      return;
    }
    let added = false;
    for (const record of records) {
      const item = fromRecord(record);
      if (item && !items.has(item.id)) {
        items.set(item.id, item);
        added = true;
      }
    }
    if (added) emitChange();
  })();
  return loaded;
}

/**
 * Uploads what waits, oldest first (skipping what is in flight or rate limited); stops
 * at the first failure that isn't permanent. Resolves the number sent. Automatic
 * flushes pause after a "you may not upload" answer; `force` (the guest's "Erneut
 * senden", or the session saying uploads are allowed again) sends anyway.
 */
export function flushOutbox(options: { force?: boolean } = {}): Promise<number> {
  if (options.force) gateClosed = false;
  if (flushing) return flushing;
  flushing = (async () => {
    await loadStored();
    let sent = 0;
    if (gateClosed) return sent;
    const now = Date.now();
    const queue = byAge(
      [...items.values()].filter((i) => i.state !== 'new' && !inFlight.has(i.id) && i.waitUntil <= now),
    );
    for (const item of queue) {
      if (!items.has(item.id) || inFlight.has(item.id)) continue;
      try {
        // oxlint-disable-next-line no-await-in-loop -- one upload after the other, oldest first
        await sendFromOutbox(item.id);
        sent += 1;
      } catch (err) {
        if (err instanceof ApiError && isPermanentUploadError(err)) continue;
        break;
      }
    }
    return sent;
  })().finally(() => {
    flushing = null;
  });
  return flushing;
}

const onOnline = () => {
  void flushOutbox();
};
const onVisible = () => {
  if (document.visibilityState === 'visible') void flushOutbox();
};

/**
 * Starts the automatic sending (online, visible again, every 30 s while waiting) and
 * sends what earlier visits kept. Idempotent; useOutbox() calls it.
 */
export function installOutbox(): void {
  if (installed || typeof window === 'undefined') return;
  installed = true;
  window.addEventListener('online', onOnline);
  document.addEventListener('visibilitychange', onVisible);
  subscribeUploadAnswers((answer) => {
    if (answer === 'ok') gateClosed = false;
  });
  void flushOutbox();
}

/** Tests: forget everything (memory only) and the listeners. */
export function resetOutbox(): void {
  items.clear();
  inFlight.clear();
  loaded = null;
  gateClosed = false;
  flushing = null;
  clearTimeout(retryTimer);
  retryTimer = undefined;
  if (installed && typeof window !== 'undefined') {
    window.removeEventListener('online', onOnline);
    document.removeEventListener('visibilitychange', onVisible);
  }
  installed = false;
  snapshot = { pending: 0, atRisk: 0, items: [] };
}

export function subscribeOutbox(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Sent, failed and dropped photos (background toasts, the beer counter). */
export function subscribeOutboxEvents(listener: (e: OutboxEvent) => void): () => void {
  eventListeners.add(listener);
  return () => {
    eventListeners.delete(listener);
  };
}

export function getOutbox(): typeof snapshot {
  return snapshot;
}

/**
 * Live view of the outbox: `pending` photos wait (the status slot's "1 Foto wartet"),
 * `atRisk` exist in memory only. Installs the automatic sending on first use.
 */
export function useOutbox(): { pending: number; atRisk: number; items: ReadonlyArray<OutboxItem> } {
  return useSyncExternalStore(subscribeAndInstall, getOutbox, getOutbox);
}

function subscribeAndInstall(listener: () => void): () => void {
  installOutbox();
  return subscribeOutbox(listener);
}
