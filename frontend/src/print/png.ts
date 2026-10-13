/**
 * The QR code as a PNG: black on white, a 4-module quiet zone, whole pixels per module
 * and at least `minSize` pixels wide. Encoded without a canvas (UPNG from pdf-lib).
 */
import { encode } from '@cantoo/pdf-lib/upng';
import { qrMatrix } from './qr';

export const PNG_QUIET = 4;

/** The RGBA pixels of the code: `scale` pixels per module. */
export function qrPixels(
  matrix: boolean[][],
  quiet: number,
  scale: number,
): { data: Uint8Array<ArrayBuffer>; size: number } {
  const modules = matrix.length + 2 * quiet;
  const size = modules * scale;
  const data = new Uint8Array(new ArrayBuffer(size * size * 4)).fill(255);
  matrix.forEach((row, my) => {
    row.forEach((dark, mx) => {
      if (!dark) return;
      const x0 = (mx + quiet) * scale;
      const y0 = (my + quiet) * scale;
      for (let y = y0; y < y0 + scale; y++) {
        const offset = (y * size + x0) * 4;
        for (let i = 0; i < scale * 4; i += 4) {
          data[offset + i] = 0;
          data[offset + i + 1] = 0;
          data[offset + i + 2] = 0;
        }
      }
    });
  });
  return { data, size };
}

export function qrPngBytes(url: string, minSize = 1600): Uint8Array<ArrayBuffer> {
  const matrix = qrMatrix(url);
  const scale = Math.ceil(Math.max(1, minSize) / (matrix.length + 2 * PNG_QUIET));
  const { data, size } = qrPixels(matrix, PNG_QUIET, scale);
  return new Uint8Array(encode([data.buffer], size, size, 0));
}
