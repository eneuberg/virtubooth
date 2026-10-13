/**
 * Photo upload over XHR (fetch has no upload progress). OWNER: wave 2 "AC".
 * Port of vb.js uploadJpeg(): POST /api/x/<ext>/upload with the raw JPEG,
 * `Content-Type: image/jpeg`, `X-VB-Meta: encodeURIComponent(JSON.stringify(meta))`
 * only when meta is non-empty, a 60 s timeout, errors through errorFromResponse()
 * (Retry-After included) and unreachable().
 *
 * Every answer goes to the session (`noteUploadAnswer`: paused/stopped change at once,
 * a 403 re-identifies, like vb.js) and to the upload-answer listeners (the outbox).
 */
import { ApiError, errorFromResponse, unreachable } from '@/api/errors';
import type { UploadResponse } from '@/api/types';
import { msg } from '@/lib/messages.de';
import { noteUploadAnswer } from './session';

export type UploadMeta = Record<string, string | number | boolean | null>;

export interface UploadOptions {
  meta?: UploadMeta;
  /** 0…1 */
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
}

export type UploadResult = UploadResponse;

export const UPLOAD_TIMEOUT_MS = 60_000;
/** The server refuses longer X-VB-Meta headers (architecture.md §2.5, step 9). */
export const META_MAX_CHARS = 2048;

/** The X-VB-Meta header value, or null when there is nothing to send. */
export function encodeMeta(meta: UploadMeta | null | undefined): string | null {
  if (!meta || Object.keys(meta).length === 0) return null;
  return encodeURIComponent(JSON.stringify(meta));
}

/** The meta the header carries (the server's decoding, for tests). */
export function decodeMeta(header: string): UploadMeta {
  const value: unknown = JSON.parse(decodeURIComponent(header));
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('meta must be an object');
  const out: UploadMeta = {};
  for (const [key, v] of Object.entries(value)) {
    if (v === null || typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') out[key] = v;
  }
  return out;
}

/** 'ok' or the error code of an upload answer. */
export type UploadAnswer = 'ok' | ApiError['code'];

const answerListeners = new Set<(answer: UploadAnswer) => void>();

/** Hears every upload answer (the session's paused/stopped state, the outbox). */
export function subscribeUploadAnswers(listener: (answer: UploadAnswer) => void): () => void {
  answerListeners.add(listener);
  return () => {
    answerListeners.delete(listener);
  };
}

/** Codes that mean "this guest may not upload right now": the session state is stale. */
export const GATE_CODES: ReadonlySet<string> = new Set(['uploads_paused', 'uploads_stopped', 'banned']);

function noteAnswer(answer: UploadAnswer): void {
  try {
    noteUploadAnswer(answer);
  } catch {
    // the session's bug must not break the upload
  }
  for (const listener of answerListeners) {
    try {
      listener(answer);
    } catch {
      // a listener's bug must not break the upload
    }
  }
}

function abortError(): DOMException {
  return new DOMException('Upload abgebrochen', 'AbortError');
}

/** POST the JPEG; resolves the server's answer (`photo` + the extension's fields). */
export function uploadPhoto(ext: string, blob: Blob, options: UploadOptions = {}): Promise<UploadResult> {
  const { meta, onProgress, signal } = options;
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/x/${encodeURIComponent(ext)}/upload`);
    xhr.setRequestHeader('Content-Type', 'image/jpeg');
    xhr.setRequestHeader('Accept', 'application/json');
    const header = encodeMeta(meta);
    if (header) xhr.setRequestHeader('X-VB-Meta', header);
    xhr.responseType = 'json';
    xhr.timeout = UPLOAD_TIMEOUT_MS;
    if (onProgress) {
      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable && e.total > 0) onProgress(Math.min(1, e.loaded / e.total));
      });
    }
    const onAbort = () => xhr.abort();
    signal?.addEventListener('abort', onAbort, { once: true });
    const done = () => signal?.removeEventListener('abort', onAbort);
    xhr.addEventListener('load', () => {
      done();
      const data: unknown = xhr.response;
      if (xhr.status >= 200 && xhr.status < 300 && data && typeof data === 'object') {
        onProgress?.(1);
        noteAnswer('ok');
        // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- trust boundary: the server's JSON
        resolve(data as UploadResult);
        return;
      }
      const err = errorFromResponse(xhr.status, data, xhr.getResponseHeader('Retry-After'), msg.uploadFailed);
      noteAnswer(err.code);
      reject(err);
    });
    // uploads go to /api/x/<ext>/upload, which blockers leave alone: a failure is the network
    xhr.addEventListener('error', () => {
      done();
      reject(unreachable(msg.uploadOffline));
    });
    xhr.addEventListener('timeout', () => {
      done();
      reject(new ApiError(0, 'timeout', msg.uploadTimeout));
    });
    xhr.addEventListener('abort', () => {
      done();
      reject(abortError());
    });
    xhr.send(blob);
  });
}

export function isAbortError(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError';
}

/** Retries can't fix these: the photo itself or the request is refused for good. */
export function isPermanentUploadError(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false;
  if (err.code === 'scan_qr') return false; // the page reloads into the gate; keep the photo
  return [400, 404, 413, 415, 422].includes(err.status);
}

/** Seconds the server asked us to wait (429 Retry-After), else 0. */
export function retryAfterSeconds(err: unknown): number {
  if (!(err instanceof ApiError)) return 0;
  const seconds = Math.ceil(err.retryAfter ?? 0);
  return Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
}
