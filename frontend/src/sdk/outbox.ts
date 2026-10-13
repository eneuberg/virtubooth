/**
 * The shared IndexedDB outbox ("never lose a shot", PLAN §1): photos that could not be
 * uploaded (offline, paused, stopped, errors) wait here and are sent again later.
 * OWNER: wave 2 "AC". Must stay compatible with today's `vb-booth` DB, store `outbox`
 * (keyPath id), records { id, meta, at, type, data: Blob | ArrayBuffer } (WebKit
 * Blob→ArrayBuffer fallback). New: the activity id is stored per item.
 */
import type { UploadMeta } from './upload';

export interface OutboxItem {
  id: string;
  /** extension id, e.g. "booth", "beer" */
  ext: string;
  meta: UploadMeta;
  /** epoch ms */
  at: number;
  blob: Blob;
}

/** Stores a photo; resolves false when it could not be stored (then keep it in memory and warn on leave). */
export function addToOutbox(item: Omit<OutboxItem, 'at'>): Promise<boolean> {
  void item;
  return Promise.reject(new Error('TODO(wave 2, AC): sdk/outbox addToOutbox'));
}

/** Uploads what waits, oldest first; stops at the first transient failure. Resolves the number sent. */
export function flushOutbox(): Promise<number> {
  return Promise.reject(new Error('TODO(wave 2, AC): sdk/outbox flushOutbox'));
}

/** Live view of the outbox for the status slot ("1 Foto wartet"). */
export function useOutbox(): { pending: number; items: ReadonlyArray<OutboxItem> } {
  // TODO(wave 2, AC): useSyncExternalStore over the store
  return { pending: 0, items: [] };
}
