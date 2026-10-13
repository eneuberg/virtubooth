/**
 * The export library: a QR code as PNG, a big QR code on A4, the printable poster.
 * Pure and framework-free; admin code loads it only with `await import('@/print')`,
 * and the PDF and PNG writers load on first use (their own chunks).
 *
 *   const print = await import('@/print');
 *   const pdf = await print.posterPdf(code, await loadPosterTemplate());
 *   print.downloadBlob(pdf, print.exportFileName(code, 'poster'));
 *
 * Every PDF has one page and the code's name small in the bottom right corner; text
 * uses the standard PDF fonts (WinAnsi, see text.ts). The token is only in the code.
 */
import type { CodePrintInput, PosterTemplateInput } from './types';

export type { CodePrintInput, PosterTemplateInput, RelRect } from './types';
export { qrMatrix } from './qr';
export { downloadBlob, exportFileName } from './names';
export { PrintError } from './errors';

/** The code as a PNG: black on white, 4-module quiet zone, ≥ `minSize` (1600) px, no label. */
export async function qrPng(input: CodePrintInput, opts: { minSize?: number } = {}): Promise<Blob> {
  const { qrPngBytes } = await import('./png');
  return new Blob([qrPngBytes(input.url, opts.minSize ?? 1600)], { type: 'image/png' });
}

/** A4 portrait with the code ≈ 170 mm wide, the event name above it and the label. */
export async function bigQrPdf(input: CodePrintInput): Promise<Uint8Array> {
  const pdf = await import('./pdf');
  return pdf.bigQrPdf(input);
}

/** One page: the template's chosen page with the code in its square, or the standard poster. */
export async function posterPdf(
  input: CodePrintInput,
  template?: PosterTemplateInput | null,
): Promise<Uint8Array> {
  const pdf = await import('./pdf');
  return pdf.posterPdf(input, template);
}
