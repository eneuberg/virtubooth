/**
 * API errors, ported from the pre-overhaul vb.js (`ApiError`, `errorFromResponse`,
 * `unreachable`, `fatal`). Every message is German and safe to show as it is.
 */
import { msg } from '@/lib/messages.de';

/** Error codes the backend sends (architecture.md §2.9) plus the client-only ones. */
export type ErrorCode =
  | 'scan_qr'
  | 'needs_consent'
  | 'banned'
  | 'uploads_paused'
  | 'uploads_stopped'
  | 'rate_limited'
  | 'login_locked'
  | 'wrong_password'
  | 'admin_required'
  | 'bad_origin'
  | 'length_required'
  | 'too_large'
  | 'consent_outdated'
  | 'invalid_instagram'
  | 'join_closed'
  | 'unsupported_type'
  | 'invalid_meta'
  | 'empty_upload'
  | 'invalid_image'
  | 'not_found'
  | 'invalid_filter'
  | 'invalid_cursor'
  | 'no_fingerprint'
  | 'restore_required'
  | 'invalid_request'
  // client-only: the request never got an answer
  | 'network'
  | 'timeout';

/** Known codes keep autocompletion; framework codes like `http_405` still fit. */
export type ApiErrorCode = ErrorCode | (string & {});

export class ApiError extends Error {
  override readonly name = 'ApiError';
  readonly status: number;
  readonly code: ApiErrorCode;
  readonly data: unknown;
  /** Seconds the server asked us to wait (429/503 with Retry-After), else null. */
  retryAfter: number | null = null;
  /**
   * Only for code 'network': true when the device says it is offline. A request a
   * content blocker dropped looks exactly like a dead network otherwise, so false
   * means "unknown", not "online".
   */
  offline = false;

  constructor(status: number, code: ApiErrorCode, message: string, data?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}

/** The vb.js network texts (single source: lib/messages.de.ts). */
export const NETWORK_MESSAGES = {
  offline: msg.offline,
  noAnswer: msg.noAnswer,
  upload: msg.uploadOffline,
  timeout: msg.uploadTimeout,
} as const;

let noAccessHandler: () => void = () => {
  // the server answers every page without access with the "scan the QR code" gate
  location.reload();
};

/** Replace what happens on `scan_qr` (tests; default: reload into the gate page). */
export function setNoAccessHandler(handler: () => void): () => void {
  const previous = noAccessHandler;
  noAccessHandler = handler;
  return () => {
    noAccessHandler = previous;
  };
}

function field(body: unknown, key: 'error' | 'message'): string | null {
  if (body && typeof body === 'object') {
    const value: unknown = Object.getOwnPropertyDescriptor(body, key)?.value;
    if (typeof value === 'string' && value) return value;
  }
  return null;
}

/**
 * The ApiError for a non-2xx answer. On 429/503 with `Retry-After` the message gets
 * the wait appended: "Langsam! … Warte kurz (in 12 s nochmal)." (minutes from 90 s on).
 * `scan_qr` (no party access) triggers the no-access handler.
 */
export function errorFromResponse(
  status: number,
  body: unknown,
  retryAfterHeader: string | null | undefined,
  fallback: string,
): ApiError {
  const err = new ApiError(
    status,
    field(body, 'error') ?? `http_${status}`,
    field(body, 'message') ?? fallback,
    body,
  );
  const wait = Number.parseInt(retryAfterHeader ?? '', 10);
  if ((status === 429 || status === 503) && wait > 0) {
    err.retryAfter = wait;
    const when = wait < 90 ? `${wait}\u00a0s` : `${Math.ceil(wait / 60)}\u00a0min`;
    err.message = `${err.message.replace(/\.\s*$/, '')} (in ${when} nochmal).`;
  }
  if (err.code === 'scan_qr') noAccessHandler();
  return err;
}

/** A request that got no answer: offline, or dropped by a blocker (the browser can't tell). */
export function unreachable(offlineText: string, unknownText: string = offlineText): ApiError {
  const offline = typeof navigator !== 'undefined' && !navigator.onLine;
  const err = new ApiError(0, 'network', offline ? offlineText : unknownText);
  err.offline = offline;
  return err;
}

/** Title and text for a full-screen error (vb.js fatal()). Never shows raw errors. */
export function fatalCopy(err: unknown): { title: string; text: string } {
  if (isApiError(err) && err.code === 'network') {
    return err.offline
      ? { title: msg.offlineTitle, text: msg.offlineText }
      : { title: msg.noAnswerTitle, text: msg.noAnswerText };
  }
  if (
    err instanceof Error &&
    (err.name === 'ApiError' || err.name === 'CameraError') &&
    typeof err.message === 'string' &&
    err.message
  ) {
    return { title: msg.failedTitle, text: err.message };
  }
  return { title: msg.unknownTitle, text: msg.unknownText };
}
