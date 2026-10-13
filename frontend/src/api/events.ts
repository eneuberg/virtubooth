/**
 * The admin event stream: `GET /api/admin/events` (SSE, named events, architecture.md §2.8).
 *
 * This module only types the events and wraps one EventSource. The reconnect /
 * polling / visibility state machine (poll every 5 s while down, re-check the session
 * on CLOSED, resync on visibilitychange) belongs to wave-2's `useAdminEvents()` hook.
 */
import type {
  AdminPhoto,
  AdminUser,
  AdminUserView,
  ExportJob,
  FpHash,
  PauseState,
  PublicPhotoId,
  StopState,
} from './types';

export type AdminEvent =
  | { type: 'photo.created'; data: { photo: AdminPhoto } }
  | { type: 'photo.hidden'; data: { photo: AdminPhoto } }
  | { type: 'photo.unhidden'; data: { photo: AdminPhoto } }
  | { type: 'photo.deleted'; data: { id: PublicPhotoId; photo: AdminPhoto | null } }
  | { type: 'user.created'; data: { id: number; name: string; banned: boolean; uploads_paused: boolean } }
  | { type: 'user.banned'; data: { user: AdminUserView; photos: AdminPhoto[] } }
  | { type: 'user.unbanned'; data: { user: AdminUserView; photos: AdminPhoto[] } }
  | { type: 'fingerprint.banned'; data: { fp_hash: FpHash; user_id: number } }
  | { type: 'fingerprint.unbanned'; data: { fp_hash: FpHash } }
  | { type: 'user.uploads_changed'; data: { users: AdminUser[]; paused: boolean } }
  | { type: 'settings.upload_stop'; data: { upload_stop: StopState } }
  | {
      type: 'settings.upload_pause';
      data: { upload_pause: PauseState; restored: number[]; kept: number[] };
    }
  | { type: 'export.updated'; data: { job: ExportJob } };

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
] as const satisfies readonly AdminEventType[];

const READY_STATE_CLOSED = 2; // EventSource.CLOSED

export type StreamStatus = 'connecting' | 'live' | 'reconnecting' | 'closed';

export interface AdminEventsOptions {
  onEvent: (event: AdminEvent) => void;
  onStatus?: (status: StreamStatus) => void;
  url?: string;
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
}: AdminEventsOptions): AdminEventsHandle {
  if (typeof EventSource === 'undefined') {
    onStatus?.('closed');
    return { close() {} };
  }
  const source = new EventSource(url, { withCredentials: false });
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
      // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- trust boundary: the event name fixes the payload shape
      onEvent({ type, data } as AdminEvent);
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
