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

/** Instagram, Facebook, TikTok & co.: no address bar, often no camera. Send the guest out. */
export const IN_APP_HINT =
  'In dieser App geht die Kamera nicht. Öffne die Seite über das ⋯-Menü in deinem Browser (Safari oder Chrome).';

export const CAMERA_TEXT = {
  insecure: 'Die Kamera funktioniert nur über eine sichere Verbindung (https).',
  unsupported: 'Dein Browser unterstützt keine Kamera. Nimm Safari oder Chrome.',
  deniedIOS:
    'Kamera-Zugriff wurde verweigert. Tippe in der Adressleiste auf „aA“ › Website-Einstellungen › Kamera › Erlauben und lade die Seite neu.',
  deniedTouch:
    'Kamera-Zugriff wurde verweigert. Tippe auf das Schloss in der Adressleiste, erlaube die Kamera und lade die Seite neu.',
  deniedDesktop:
    'Kamera-Zugriff wurde verweigert. Klick in der Adressleiste auf das Kamera-Symbol, erlaube die Kamera und lade die Seite neu.',
  notFound: 'Keine passende Kamera gefunden.',
  busy: 'Die Kamera wird gerade von einer anderen App benutzt. Schließ sie und versuch es nochmal.',
  timeout: 'Die Kamera startet nicht. Lade die Seite neu.',
  unknown: 'Die Kamera konnte nicht gestartet werden.',
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
