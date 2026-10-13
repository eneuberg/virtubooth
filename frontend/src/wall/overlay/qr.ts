/**
 * The corner's QR code on a canvas: C's `qrMatrix`, black modules on white with a
 * two-module quiet zone (CSS scales it, pixelated). A path (no VB_PUBLIC_BASE_URL on
 * the server) is resolved against this page's origin.
 */
import { qrMatrix } from '@/print/qr';

const QUIET = 2;
const MODULE_PX = 8;

/** The URL the code opens: absolute as given, a path against this page's origin. */
export function qrTarget(url: string, origin: string = location.origin): string {
  try {
    return new URL(url, origin).href;
  } catch {
    return url;
  }
}

/** Draws `text` as a QR code; false without canvas 2D. */
export function drawQr(canvas: HTMLCanvasElement, text: string): boolean {
  const matrix = qrMatrix(text);
  const size = matrix.length + QUIET * 2;
  canvas.width = size * MODULE_PX;
  canvas.height = size * MODULE_PX;
  const ctx = canvas.getContext('2d');
  if (!ctx) return false;
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#000000';
  matrix.forEach((row, y) => {
    row.forEach((dark, x) => {
      if (dark) ctx.fillRect((x + QUIET) * MODULE_PX, (y + QUIET) * MODULE_PX, MODULE_PX, MODULE_PX);
    });
  });
  return true;
}
