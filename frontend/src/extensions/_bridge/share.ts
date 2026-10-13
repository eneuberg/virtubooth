/**
 * TEMPORARY stand-in for GP's `@/sdk/share` saveImage (see ./session.ts: delete when GP
 * merges). Port of vb.js saveImage(): on iOS (or with preferShare) the share sheet
 * when it can take files; AbortError → 'cancelled'; anything else downloads through
 * <a download> with an object URL revoked after 30 s.
 */
import { isIOS } from '@/sdk/platform';

export type SaveResult = 'shared' | 'downloaded' | 'cancelled';

export async function saveImage(
  blob: Blob,
  name: string,
  options: { preferShare?: boolean } = {},
): Promise<SaveResult> {
  const file = new File([blob], name, { type: blob.type || 'image/jpeg' });
  const share = options.preferShare ?? isIOS();
  if (share && typeof navigator.canShare === 'function' && navigator.canShare({ files: [file] })) {
    try {
      await navigator.share({ files: [file] });
      return 'shared';
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return 'cancelled';
      // fall through to the download
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
  return 'downloaded';
}
