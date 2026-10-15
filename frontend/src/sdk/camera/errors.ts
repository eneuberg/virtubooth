/**
 * Camera errors with German messages. OWNER: wave 2 "AC".
 * Port of core/camera.js CameraError + cameraErrorMessage: the checks run in the same
 * order (insecure context, in-app browser, then the DOMException name), and every
 * message says what to do next.
 */
import { isIOS, isInAppBrowser } from '../platform';

export type CameraErrorCode =
  'insecure' | 'in_app' | 'denied' | 'not_found' | 'busy' | 'unsupported' | 'timeout' | 'unknown';

export class CameraError extends Error {
  override name = 'CameraError';
  readonly code: CameraErrorCode;

  constructor(code: CameraErrorCode, message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.code = code;
  }
}

export function isCameraError(err: unknown): err is CameraError {
  return err instanceof CameraError;
}

/** The title of the full-screen camera error (one wording for every activity). */
export const CAMERA_ERROR_TITLE = 'Die Kamera geht nicht';

/**
 * The fallback after every camera error a browser could be behind: another browser.
 * Copying the address would not do: the QR code's token is gone from it (the access is
 * a cookie of this browser), so the other browser needs the QR code again.
 */
export const BROWSER_HINT =
  'Klappt’s nicht? Probier einen anderen Browser, z.\u00a0B. Safari oder Chrome, und scanne den QR-Code dafür nochmal.';

/**
 * Instagram, WhatsApp, Facebook & co. open links in their own browser, often without a
 * camera. "Open in browser" would lose the party access (the token is gone from the
 * address), so: another browser, through the camera app's QR scan (GP's advice on Start, too).
 */
export const IN_APP_HINT =
  'Im Browser dieser App geht die Kamera oft nicht. Öffne die Seite in einem anderen Browser, z.\u00a0B. Safari oder Chrome: Scanne den QR-Code dafür mit der Kamera-App deines Handys.';

/** What to do first, then (except for https, which no browser fixes) another browser. */
export const CAMERA_TEXT = {
  insecure: 'Die Kamera funktioniert nur über eine sichere Verbindung (https).',
  unsupported:
    'Dieser Browser kann die Kamera nicht nutzen. Probier einen anderen, z.\u00a0B. Safari oder Chrome, und scanne den QR-Code dafür nochmal.',
  deniedIOS: `Kamera-Zugriff wurde verweigert. Tippe in der Adressleiste auf „aA“ › Website-Einstellungen › Kamera › Erlauben und lade die Seite neu. ${BROWSER_HINT}`,
  deniedTouch: `Kamera-Zugriff wurde verweigert. Tippe auf das Schloss in der Adressleiste, erlaube die Kamera und lade die Seite neu. ${BROWSER_HINT}`,
  deniedDesktop: `Kamera-Zugriff wurde verweigert. Klick in der Adressleiste auf das Kamera-Symbol, erlaube die Kamera und lade die Seite neu. ${BROWSER_HINT}`,
  notFound: `Keine passende Kamera gefunden. ${BROWSER_HINT}`,
  busy: `Die Kamera wird gerade von einer anderen App benutzt. Schließ sie und versuch es nochmal. ${BROWSER_HINT}`,
  timeout: `Die Kamera startet nicht. Lade die Seite neu. ${BROWSER_HINT}`,
  unknown: `Die Kamera konnte nicht gestartet werden. Lade die Seite neu. ${BROWSER_HINT}`,
} as const;

function errorName(err: unknown): string {
  if (err && typeof err === 'object' && 'name' in err && typeof err.name === 'string') return err.name;
  return '';
}

function isSecure(): boolean {
  return typeof window === 'undefined' || window.isSecureContext;
}

function hasTouch(): boolean {
  try {
    return navigator.maxTouchPoints > 0 || window.matchMedia('(any-pointer: coarse)').matches;
  } catch {
    return false;
  }
}

/** The code for a getUserMedia failure (same order as the message). */
export function cameraErrorCode(err: unknown): CameraErrorCode {
  if (err instanceof CameraError) return err.code;
  if (!isSecure()) return 'insecure';
  if (isInAppBrowser()) return 'in_app';
  switch (errorName(err)) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'denied';
    case 'NotFoundError':
    case 'OverconstrainedError':
      return 'not_found';
    case 'NotReadableError':
    case 'AbortError':
      return 'busy';
    default:
      return 'unknown';
  }
}

/** The German text for a getUserMedia failure (shown as is). */
export function cameraErrorMessage(err: unknown): string {
  if (err instanceof CameraError) return err.message;
  switch (cameraErrorCode(err)) {
    case 'insecure':
      return CAMERA_TEXT.insecure;
    case 'in_app':
      return IN_APP_HINT;
    case 'denied':
      if (isIOS()) return CAMERA_TEXT.deniedIOS;
      // PC (Firefox, Chrome, Edge): a crossed-out camera icon sits in the address bar
      return hasTouch() ? CAMERA_TEXT.deniedTouch : CAMERA_TEXT.deniedDesktop;
    case 'not_found':
      return CAMERA_TEXT.notFound;
    case 'busy':
      return CAMERA_TEXT.busy;
    default:
      return CAMERA_TEXT.unknown;
  }
}

/** Wraps any getUserMedia failure into a CameraError with its German message. */
export function toCameraError(err: unknown): CameraError {
  if (err instanceof CameraError) return err;
  return new CameraError(cameraErrorCode(err), cameraErrorMessage(err), { cause: err });
}

/** Without navigator.mediaDevices (old browsers, in-app WebViews, plain http). */
export function unsupportedError(): CameraError {
  if (!isSecure()) return new CameraError('insecure', CAMERA_TEXT.insecure);
  return isInAppBrowser()
    ? new CameraError('in_app', IN_APP_HINT)
    : new CameraError('unsupported', CAMERA_TEXT.unsupported);
}
