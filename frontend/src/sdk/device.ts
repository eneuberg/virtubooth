/**
 * Device traits for moderation hints (the server stores a hash; it is only a hint).
 * OWNER: wave 2 "GP". Port of core/device.js + vb.js getFingerprint().
 *
 * Rules (architecture.md §5, stack.md "Content blockers"):
 * - neutral names only: never fingerprint/track in file, function or URL names;
 * - the trait collector is loaded with import() inside try/catch, so a blocked or
 *   failing optional chunk can never stop the page; the fallback is a coarse hash of
 *   what every browser exposes (user agent, language, screen, time zone);
 * - never rejects: joining requires a value.
 */

export interface DeviceTraits {
  /** hex, 16–64 chars (^[0-9a-f]{16,64}$) */
  hash: string;
  /** at most 32 keys; values bool/number/null or strings ≤ 200 chars */
  components: Record<string, string | number | boolean | null>;
}

/** Collects (and caches) the traits. Never rejects. */
export function getDeviceTraits(): Promise<DeviceTraits> {
  // TODO(wave 2, GP): import('./device-traits') with the coarse sha256 fallback
  return Promise.reject(new Error('TODO(wave 2, GP): sdk/device getDeviceTraits'));
}
