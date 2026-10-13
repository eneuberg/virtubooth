import { slug } from './text';
import type { CodePrintInput } from './types';

export type ExportKind = 'png' | 'qr-pdf' | 'poster';

/** "Gorilla 2" (number 2) → "gorilla": the number is in the file name already. */
function nameSlug(input: CodePrintInput): string {
  const name = input.name.trim();
  const trailing = /^(.*?)[\s#-]*(\d+)$/u.exec(name);
  const base = trailing && Number(trailing[2]) === input.number ? (trailing[1] ?? '') : name;
  return slug(base);
}

/**
 * "qr-02-gorilla.png", "qr-02-gorilla-gross.pdf", "plakat-02-gorilla.pdf" (number
 * padded to 2 digits; the slug falls away when the name has no printable letters).
 */
export function exportFileName(input: CodePrintInput, kind: ExportKind): string {
  const number = String(Math.max(0, Math.trunc(input.number))).padStart(2, '0');
  const stem = [kind === 'poster' ? 'plakat' : 'qr', number, nameSlug(input)].filter(Boolean).join('-');
  switch (kind) {
    case 'png':
      return `${stem}.png`;
    case 'qr-pdf':
      return `${stem}-gross.pdf`;
    default:
      return `${stem}.pdf`;
  }
}

const TYPES: Record<string, string> = { pdf: 'application/pdf', png: 'image/png' };

/**
 * Save a file in the browser (an <a download> click on a blob URL). The type is
 * taken from the file name's extension unless given.
 */
export function downloadBlob(data: Blob | Uint8Array, fileName: string, type?: string): void {
  const ext = fileName.split('.').pop()?.toLowerCase() ?? '';
  const mime = type ?? TYPES[ext] ?? 'application/octet-stream';
  const blob = data instanceof Blob ? data : new Blob([new Uint8Array(data)], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  link.rel = 'noopener';
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  // Safari starts the download after the click returns: revoke a little later
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
