/**
 * The admin event stream: `GET /api/admin/events` (SSE, named events, architecture.md §2.8).
 *
 * This module only types the events and wraps one EventSource. The reconnect /
 * polling / visibility state machine (poll every 5 s while down, re-check the session
 * on CLOSED, resync on visibilitychange) belongs to wave-2's `useAdminEvents()` hook.
 */
import type { components } from './schema.gen';
import type { ExportJob } from './types';

type SchemaEvent = components['schemas']['AdminEvent'];
/** The schema variant without its required `id`: `stream.resync` has none on the wire. */
type WireEvent<E> = E extends { type: infer T; data: infer D } ? { type: T; data: D; id?: string } : never;

/**
 * One message of the stream: `type` is the SSE event name, `data` the parsed payload,
 * `id` the SSE id (`<epoch>-<n>`, absent on `stream.resync`). Typed from the OpenAPI
 * union (contracts/api.md §4).
 */
export type AdminEvent =
  | WireEvent<SchemaEvent>
  // TODO(wave 2 merge): comes from the schema once BE-features' exports land.
  | { type: 'export.updated'; data: { job: ExportJob }; id?: string };

export type AdminEventType = AdminEvent['type'];

/** Payload of one event type: `AdminEventData<'photo.hidden'>` → `{ photo: AdminPhoto }`. */
export type AdminEventData<K extends AdminEventType> = Extract<AdminEvent, { type: K }>['data'];

export const ADMIN_EVENT_TYPES = [
  'photo.created',
  'photo.hidden',
  'photo.unhidden',
  'photo.deleted',
  'user.created',
  'user.banned',
  'user.unbanned',
  'fingerprint.banned',
  'fingerprint.unbanned',
  'user.uploads_changed',
  'settings.upload_stop',
  'settings.upload_pause',
  'export.updated',
  'stream.resync',
] as const satisfies readonly AdminEventType[];

const READY_STATE_CLOSED = 2; // EventSource.CLOSED

export type StreamStatus = 'connecting' | 'live' | 'reconnecting' | 'closed';

export interface AdminEventsOptions {
  onEvent: (event: AdminEvent) => void;
  onStatus?: (status: StreamStatus) => void;
  url?: string;
  /**
   * `X-VB-Event-Id` of the page's first admin fetch: the server replays what happened
   * between that fetch and this stream (contracts/api.md §4).
   */
  since?: string | null;
}

export interface AdminEventsHandle {
  close(): void;
}

/**
 * Opens the stream and reports every named event. The browser reconnects on its own
 * after network errors (`retry: 3000`); a 401 or a server-side end leaves it CLOSED,
 * which is reported as 'closed' so the caller can check the session and reopen.
 */
export function openAdminEvents({
  onEvent,
  onStatus,
  url = '/api/admin/events',
  since = null,
}: AdminEventsOptions): AdminEventsHandle {
  if (typeof EventSource === 'undefined') {
    onStatus?.('closed');
    return { close() {} };
  }
  const href = since ? `${url}?since=${encodeURIComponent(since)}` : url;
  const source = new EventSource(href, { withCredentials: false });
  onStatus?.('connecting');

  const listeners = ADMIN_EVENT_TYPES.map((type) => {
    const listener = (e: Event) => {
      if (!(e instanceof MessageEvent) || typeof e.data !== 'string') return;
      let data: unknown;
      try {
        data = JSON.parse(e.data);
      } catch {
        return; // a malformed frame is dropped, the next resync repairs the view
      }
      const id = e.lastEventId || undefined;
      // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- trust boundary: the event name fixes the payload shape
      onEvent({ type, data, id } as AdminEvent);
    };
    source.addEventListener(type, listener);
    return [type, listener] as const;
  });

  source.addEventListener('open', () => onStatus?.('live'));
  source.addEventListener('error', () => {
    onStatus?.(source.readyState === READY_STATE_CLOSED ? 'closed' : 'reconnecting');
  });

  return {
    close() {
      for (const [type, listener] of listeners) source.removeEventListener(type, listener);
      source.close();
      onStatus?.('closed');
    },
  };
}
