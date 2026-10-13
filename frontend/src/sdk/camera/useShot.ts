/**
 * The life of one photo on a camera page. OWNER: wave 2 "AC".
 * capture → into the outbox (on disk first) → upload with progress → the result print.
 * A failed upload stays in the outbox: "Erneut senden" retries, and the outbox sends
 * it by itself later (online, visible, every 30 s, next visit). Only a refusal no
 * retry can fix (bad image, too big) drops it.
 */
import { useEffect, useState } from 'react';
import { ApiError } from '@/api/errors';
import { formatFrame } from '@/lib/format';
import { msg } from '@/lib/messages.de';
import { showToast } from '@/ui/Toast';
import {
  addToOutbox,
  newShotId,
  removeFromOutbox,
  sendFromOutbox,
  subscribeOutboxEvents,
  type OutboxEvent,
} from '../outbox';
import {
  GATE_CODES,
  isPermanentUploadError,
  retryAfterSeconds,
  type UploadMeta,
  type UploadResult,
} from '../upload';

export type ShotStatus =
  /** the first upload (or a retry) runs */
  | 'uploading'
  /** the server has it */
  | 'done'
  /** failed for now (network, server, rate limit): waits in the outbox */
  | 'waiting'
  /** the guest may not upload right now (paused, stopped, banned): waits in the outbox */
  | 'held'
  /** refused for good (bad image, …): not in the outbox */
  | 'failed';

export interface Shot {
  id: string;
  ext: string;
  blob: Blob;
  /** object URL of the JPEG (the result print) */
  url: string;
  meta: UploadMeta;
  status: ShotStatus;
  /** 0…1 while uploading */
  progress: number;
  error: ApiError | null;
  result: UploadResult | null;
  /** kept on disk until sent */
  stored: boolean;
  /** rate limited: no retry before this (epoch ms) */
  waitUntil: number;
}

function statusFor(error: ApiError): ShotStatus {
  if (isPermanentUploadError(error)) return 'failed';
  return GATE_CODES.has(error.code) ? 'held' : 'waiting';
}

function toApiError(err: unknown): ApiError | null {
  return err instanceof ApiError ? err : null;
}

export function useShot(ext: string) {
  const [shot, setShot] = useState<Shot | null>(null);

  const patch = (id: string, change: Partial<Shot>) => {
    setShot((current) => (current && current.id === id ? { ...current, ...change } : current));
  };

  const send = async (id: string): Promise<UploadResult | null> => {
    patch(id, { status: 'uploading', progress: 0, error: null, waitUntil: 0 });
    try {
      const result = await sendFromOutbox(id, { onProgress: (progress) => patch(id, { progress }) });
      patch(id, { status: 'done', progress: 1, result });
      return result;
    } catch (err) {
      const error = toApiError(err);
      if (!error) {
        patch(id, { status: 'waiting' });
        return null;
      }
      const wait = retryAfterSeconds(error);
      patch(id, { status: statusFor(error), error, waitUntil: wait ? Date.now() + wait * 1000 : 0 });
      return null;
    }
  };

  /** Shows the photo as the result and sends it. Resolves the server's answer (null: not sent). */
  const take = async (blob: Blob, meta: UploadMeta): Promise<UploadResult | null> => {
    const id = newShotId();
    const url = URL.createObjectURL(blob);
    setShot({
      id,
      ext,
      blob,
      url,
      meta,
      status: 'uploading',
      progress: 0,
      error: null,
      result: null,
      stored: false,
      waitUntil: 0,
    });
    const stored = await addToOutbox({ id, ext, meta, blob });
    patch(id, { stored });
    return send(id);
  };

  /** "Erneut senden". */
  const retry = async (): Promise<UploadResult | null> => {
    if (!shot || shot.status === 'uploading' || shot.status === 'done' || shot.status === 'failed')
      return null;
    return send(shot.id);
  };

  /** Leaves the result (the photo stays in the outbox unless it was sent or refused). */
  const dismiss = () => {
    setShot(null); // the effect below revokes the object URL
  };

  /** Throws the photo away for good (only offered when it can never be sent). */
  const discard = async () => {
    if (!shot) return;
    await removeFromOutbox(shot.id);
    dismiss();
  };

  // the outbox may send this photo by itself (back online) while the print is shown
  const shotId = shot?.id ?? null;
  useEffect(() => {
    if (!shotId) return undefined;
    return subscribeOutboxEvents((e: OutboxEvent) => {
      if (e.item.id !== shotId || e.type !== 'sent') return;
      setShot((current) =>
        current && current.id === shotId
          ? { ...current, status: 'done', progress: 1, result: e.result, error: null }
          : current,
      );
    });
  }, [shotId]);

  // the object URL dies with the page
  const url = shot?.url ?? null;
  useEffect(() => {
    if (!url) return undefined;
    return () => URL.revokeObjectURL(url);
  }, [url]);

  return { shot, take, retry, dismiss, discard };
}

/**
 * Toasts for photos the outbox sent or dropped in the background (not the one on
 * screen): "Foto 0019 von vorhin ist jetzt hochgeladen."
 */
export function useOutboxToasts(attachedId: string | null): void {
  useEffect(
    () =>
      subscribeOutboxEvents((e) => {
        if (e.item.id === attachedId) return;
        if (e.type === 'sent') {
          const when = e.item.resumed ? ' von vorhin ist jetzt' : ' ist';
          if (e.item.ext === 'beer') {
            showToast({ message: `Dein Bier${when} gezählt.`, tone: 'success' });
          } else {
            const n = e.result.booth_number ?? e.result.photo.seq;
            showToast({ message: `Foto ${formatFrame(n)}${when} hochgeladen.`, tone: 'success' });
          }
        } else if (e.type === 'dropped') {
          showToast({ message: `Ein Foto lässt sich nicht hochladen: ${e.error.message}`, tone: 'error' });
        }
      }),
    [attachedId],
  );
}

/** What went wrong with a shot's upload, in one short sentence (the print says the rest). */
export function shotErrorText(error: ApiError | null, waitSeconds: number): string {
  if (!error) return '';
  switch (error.code) {
    case 'rate_limited':
      return waitSeconds > 0
        ? `Langsam! Zu viele Fotos auf einmal. In ${waitSeconds}\u00a0s nochmal.`
        : 'Langsam! Zu viele Fotos auf einmal. Versuch es gleich nochmal.';
    case 'network':
      return error.offline ? 'Keine Verbindung.' : 'Keine Verbindung zum Server.';
    case 'timeout':
      return 'Das Hochladen hat zu lange gedauert.';
    // the guest's words for the gate (the status slot says the same), not the server's
    case 'uploads_paused':
      return msg.pausedText;
    case 'uploads_stopped':
      return msg.stoppedText;
    case 'banned':
      return msg.bannedShort;
    default:
      return error.message;
  }
}

/** Ticks once a second while `active` (rate-limit countdowns). */
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}
