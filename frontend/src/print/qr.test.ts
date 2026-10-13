import { decode as decodePng, toRGBA8 } from '@cantoo/pdf-lib/upng';
import { decodeQR } from 'qr/decode.js';
import { describe, expect, it } from 'vitest';
import { qrPixels, qrPngBytes } from './png';
import { darkRuns, qrMatrix } from './qr';

const TOKEN = 'a'.repeat(20) + 'B7xQ-_9'.repeat(6) + 'zz'; // 64 characters
const URLS = [
  'https://party.example.com/',
  `https://party.example.com/?t=${TOKEN}`,
  `https://lenas-30.party.example.com/x/booth/?t=${TOKEN}`,
  `http://192.168.178.24:8000/x/beer/?t=${TOKEN}&src=plakat`,
];

/** Scan the code from its pixels, like a phone would. */
function scan(matrix: boolean[][], scale = 6): string {
  const { data, size } = qrPixels(matrix, 4, scale);
  return decodeQR({ width: size, height: size, data });
}

describe('qrMatrix', () => {
  it.each(URLS)('decodes back to the URL: %s', (url) => {
    const matrix = qrMatrix(url);
    expect(matrix.length).toBeGreaterThanOrEqual(21);
    expect(matrix.every((row) => row.length === matrix.length)).toBe(true);
    expect(scan(matrix)).toBe(url);
  });

  it('uses error correction "high" (a bigger code than "low")', () => {
    const url = URLS[1] ?? '';
    expect(qrMatrix(url).length).toBeGreaterThan(41); // "low" fits a 64-char token URL in version 5 (37)
  });

  it('merges dark modules into runs that cover exactly the dark modules', () => {
    const matrix = qrMatrix(URLS[2] ?? '');
    const covered = matrix.map((row) => row.map(() => false));
    for (const run of darkRuns(matrix)) {
      expect(run.length).toBeGreaterThan(0);
      for (let x = run.x; x < run.x + run.length; x++) {
        const row = covered[run.y];
        expect(row?.[x]).toBe(false);
        if (row) row[x] = true;
      }
    }
    expect(covered).toEqual(matrix);
    const dark = matrix.flat().filter(Boolean).length;
    expect(darkRuns(matrix).length).toBeLessThan(dark / 1.5);
  });
});

describe('qrPng', () => {
  it('is a PNG of at least 1600 px that scans', () => {
    const url = URLS[2] ?? '';
    const png = qrPngBytes(url);
    expect(Array.from(png.subarray(0, 8))).toEqual([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    const image = decodePng(png.buffer);
    expect(image.width).toBeGreaterThanOrEqual(1600);
    expect(image.height).toBe(image.width);
    // whole pixels per module, 4 modules of quiet zone
    const modules = qrMatrix(url).length + 8;
    expect(image.width % modules).toBe(0);
    const rgba = new Uint8Array(toRGBA8(image)[0] ?? new ArrayBuffer(0));
    expect(decodeQR({ width: image.width, height: image.height, data: rgba })).toBe(url);
    // small: two colours compress well
    expect(png.length).toBeLessThan(60_000);
  });

  it('honours a bigger minimum size', () => {
    const image = decodePng(qrPngBytes(URLS[0] ?? '', 3000).buffer);
    expect(image.width).toBeGreaterThanOrEqual(3000);
  });
});
