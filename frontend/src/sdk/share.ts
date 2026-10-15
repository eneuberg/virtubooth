/**
 * Saving a photo on the phone. Port of vb.js saveImage().
 *
 * - With `preferShare` (default: on iOS) and a browser that can share files, the
 *   system share sheet opens (iOS: "Bild sichern" puts it into Photos; a download
 *   would land in the Files app). AbortError (the guest closed the sheet) → 'cancelled'.
 * - Otherwise, or when sharing fails for another reason, a download through
 *   <a download> with an object URL that is revoked after 30 s → 'downloaded'.
 *
 * Android's share sheet usually has no "save to gallery", so „Herunterladen“ downloads
 * there and the viewer offers "Teilen" (shareImage) as a second button.
 * Build the Blob BEFORE the tap and call this synchronously in the press handler:
 * Web Share needs the user activation (WebKit is strict about it).
 */
import { isIOS } from './platform';

export type SaveResult = 'shared' | 'downloaded' | 'cancelled';

function asFile(blob: Blob, name: string): File {
  return new File([blob], name, { type: blob.type || 'image/jpeg' });
}

function canShare(file: File): boolean {
  try {
    return (
      typeof navigator.share === 'function' &&
      typeof navigator.canShare === 'function' &&
      navigator.canShare({ files: [file] })
    );
  } catch {
    return false;
  }
}

/** Whether this browser can hand a photo to the share sheet (decides on a "Teilen" button). */
export function canShareFiles(): boolean {
  return canShare(asFile(new Blob([], { type: 'image/jpeg' }), 'probe.jpg'));
}

function isAbort(err: unknown): boolean {
  return typeof err === 'object' && err !== null && 'name' in err && err.name === 'AbortError';
}

/** A download through a temporary <a download>. */
export function downloadBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.rel = 'noopener';
  a.hidden = true;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export async function saveImage(
  blob: Blob,
  name: string,
  options: { preferShare?: boolean } = {},
): Promise<SaveResult> {
  const preferShare = options.preferShare ?? isIOS();
  const file = asFile(blob, name);
  if (preferShare && canShare(file)) {
    try {
      await navigator.share({ files: [file] });
      return 'shared';
    } catch (err) {
      if (isAbort(err)) return 'cancelled';
      // NotAllowedError (no user activation), DataError, …: download instead
    }
  }
  downloadBlob(blob, name);
  return 'downloaded';
}

/** "Teilen": the share sheet where the browser has one, else a download. */
export function shareImage(blob: Blob, name: string): Promise<SaveResult> {
  return saveImage(blob, name, { preferShare: true });
}
