/**
 * Camera errors with German messages. OWNER: wave 2 "AC".
 * Port of core/camera.js CameraError + cameraErrorMessage (insecure context,
 * in-app browser hint, denied on iOS / touch / desktop, not found, busy, …).
 */

export type CameraErrorCode =
  'insecure' | 'in_app' | 'denied' | 'not_found' | 'busy' | 'unsupported' | 'unknown';

export class CameraError extends Error {
  override name = 'CameraError';
  readonly code: CameraErrorCode;

  constructor(code: CameraErrorCode, message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.code = code;
  }
}

/** The German text for a getUserMedia failure (shown as is). */
export function cameraErrorMessage(err: unknown): string {
  void err;
  throw new Error('TODO(wave 2, AC): sdk/camera/errors cameraErrorMessage');
}
