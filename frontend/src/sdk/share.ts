/**
 * Saving a photo on the phone. OWNER: wave 2 "GP".
 * Port of vb.js saveImage(): on iOS (or with preferShare) use navigator.share({files})
 * when canShare; AbortError → 'cancelled'; any other failure falls back to a download
 * through <a download> with an object URL revoked after 30 s.
 * Build the Blob BEFORE the tap and call this synchronously in the press handler
 * (Web Share needs the user activation; check in WebKit, stack.md).
 */

export type SaveResult = 'shared' | 'downloaded' | 'cancelled';

export function saveImage(
  blob: Blob,
  name: string,
  options: { preferShare?: boolean } = {},
): Promise<SaveResult> {
  void blob;
  void name;
  void options;
  return Promise.reject(new Error('TODO(wave 2, GP): sdk/share saveImage'));
}
