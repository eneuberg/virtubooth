import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  BROWSER_HINT,
  CAMERA_TEXT,
  CameraError,
  cameraErrorCode,
  cameraErrorMessage,
  IN_APP_HINT,
  toCameraError,
} from './errors';

const ANDROID =
  'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/140.0.0.0 Mobile Safari/537.36';
const IPHONE =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 Version/18.5 Mobile/15E148 Safari/604.1';
const DESKTOP = 'Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0';

function secure(value: boolean) {
  Object.defineProperty(window, 'isSecureContext', { configurable: true, get: () => value });
}

function device(ua: string, touch: number) {
  secure(true);
  vi.spyOn(navigator, 'userAgent', 'get').mockReturnValue(ua);
  vi.spyOn(navigator, 'maxTouchPoints', 'get').mockReturnValue(touch);
  vi.spyOn(window, 'matchMedia').mockImplementation(
    // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- the two fields errors.ts reads
    (q: string) => ({ matches: touch > 0 && q.includes('coarse'), media: q }) as MediaQueryList,
  );
}

const named = (name: string) => new DOMException('x', name);

afterEach(() => {
  vi.restoreAllMocks();
});

describe('cameraErrorMessage', () => {
  it.each([
    ['NotFoundError', CAMERA_TEXT.notFound],
    ['OverconstrainedError', CAMERA_TEXT.notFound],
    ['NotReadableError', CAMERA_TEXT.busy],
    ['AbortError', CAMERA_TEXT.busy],
    ['TypeError', CAMERA_TEXT.unknown],
  ])('%s', (name, text) => {
    device(ANDROID, 5);
    expect(cameraErrorMessage(named(name))).toBe(text);
  });

  it('tells each device how to allow the camera again', () => {
    device(IPHONE, 5);
    expect(cameraErrorMessage(named('NotAllowedError'))).toBe(CAMERA_TEXT.deniedIOS);
    device(ANDROID, 5);
    expect(cameraErrorMessage(named('NotAllowedError'))).toBe(CAMERA_TEXT.deniedTouch);
    expect(cameraErrorMessage(named('SecurityError'))).toBe(CAMERA_TEXT.deniedTouch);
    device(DESKTOP, 0);
    expect(cameraErrorMessage(named('NotAllowedError'))).toBe(CAMERA_TEXT.deniedDesktop);
    expect(CAMERA_TEXT.deniedTouch).toContain('Kamera-Zugriff wurde verweigert. Tippe auf das Schloss');
    expect(CAMERA_TEXT.deniedDesktop).toContain(
      'Kamera-Zugriff wurde verweigert. Klick in der Adressleiste auf das Kamera-Symbol',
    );
  });

  it('sends in-app browsers out first', () => {
    device(`${ANDROID} Instagram 300.0.0.0`, 5);
    expect(cameraErrorMessage(named('NotAllowedError'))).toBe(IN_APP_HINT);
    expect(cameraErrorCode(named('NotFoundError'))).toBe('in_app');
  });

  it('needs https before anything else', () => {
    device(ANDROID, 5);
    secure(false);
    expect(cameraErrorMessage(named('NotAllowedError'))).toBe(CAMERA_TEXT.insecure);
  });

  it('suggests another browser after the first fix, except where no browser helps', () => {
    expect(BROWSER_HINT).toBe(
      'Klappt’s nicht? Probier einen anderen Browser, z.\u00a0B. Safari oder Chrome, und scanne den QR-Code dafür nochmal.',
    );
    for (const key of [
      'deniedIOS',
      'deniedTouch',
      'deniedDesktop',
      'notFound',
      'busy',
      'timeout',
      'unknown',
    ] as const) {
      // the „Kamera erlauben“ steps (or what else to do) first, the browser as the fallback
      expect(CAMERA_TEXT[key].endsWith(` ${BROWSER_HINT}`)).toBe(true);
      expect(CAMERA_TEXT[key].indexOf(BROWSER_HINT)).toBeGreaterThan(0);
    }
    // a browser without a camera and the in-app browsers: another browser is the advice
    expect(CAMERA_TEXT.unsupported).toMatch(
      /^Dieser Browser kann die Kamera nicht nutzen\. Probier einen anderen/,
    );
    expect(IN_APP_HINT).toContain('Öffne die Seite in einem anderen Browser, z.\u00a0B. Safari oder Chrome');
    expect(IN_APP_HINT).toContain('Scanne den QR-Code dafür mit der Kamera-App');
    // plain http: the host's setup, no browser fixes it
    expect(CAMERA_TEXT.insecure).not.toContain('Browser');
  });

  it('keeps a CameraError as it is', () => {
    const err = new CameraError('timeout', CAMERA_TEXT.timeout);
    expect(cameraErrorMessage(err)).toBe(CAMERA_TEXT.timeout);
    expect(toCameraError(err)).toBe(err);
    device(ANDROID, 5);
    const wrapped = toCameraError(named('NotReadableError'));
    expect(wrapped).toBeInstanceOf(CameraError);
    expect(wrapped.code).toBe('busy');
    expect(wrapped.message).toBe(CAMERA_TEXT.busy);
  });
});
