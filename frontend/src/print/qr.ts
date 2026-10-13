import { encodeQR } from 'qr';

/**
 * The QR code's modules (rows of booleans, true = dark), without a quiet zone.
 * Error correction "high": the code still reads with up to 30 % of it damaged.
 * (qr 0.7 insists on a quiet zone: ask for one module and cut it off.)
 */
export function qrMatrix(url: string): boolean[][] {
  const bordered = encodeQR(url, 'raw', { ecc: 'high', border: 1 });
  return bordered.slice(1, -1).map((row) => row.slice(1, -1));
}

/** A run of dark modules in one row: x, y and length in modules. */
export interface ModuleRun {
  x: number;
  y: number;
  length: number;
}

/** Dark modules merged into horizontal runs (a small PDF: one rectangle per run). */
export function darkRuns(matrix: ReadonlyArray<ReadonlyArray<boolean>>): ModuleRun[] {
  const runs: ModuleRun[] = [];
  matrix.forEach((row, y) => {
    let start = -1;
    for (let x = 0; x <= row.length; x++) {
      const dark = x < row.length && row[x] === true;
      if (dark && start < 0) start = x;
      if (!dark && start >= 0) {
        runs.push({ x: start, y, length: x - start });
        start = -1;
      }
    }
  });
  return runs;
}
