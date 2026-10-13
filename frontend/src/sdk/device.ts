/**
 * Device traits for moderation hints (the server stores a hash; it is only a hint).
 * Port of vb.js getFingerprint() + core/device.js.
 *
 * Rules (architecture.md §5, stack.md "Content blockers"):
 * - neutral names only: never fingerprint/track in file, function or URL names;
 * - the collector (./traits.ts, its own chunk) is loaded with import() inside
 *   try/catch, so a blocked or failing optional chunk can never stop the page; the
 *   fallback is a coarse hash of what every browser exposes (user agent, language,
 *   screen, time zone) with `components.fallback = true`;
 * - never rejects, and runs once per page: joining requires a value.
 */
import { debugLog } from './debug';
import { sha256Hex } from './hash';

export interface DeviceTraits {
  /** hex, 16–64 chars (^[0-9a-f]{16,64}$) */
  hash: string;
  /** at most 32 keys; values bool/number/null or strings ≤ 200 chars */
  components: Record<string, string | number | boolean | null>;
}

let cached: Promise<DeviceTraits> | null = null;
/** true while the collector chunk is being fetched (see the preload-error guard below) */
let loading = false;

/**
 * Vite reports a failed lazy chunk as `vite:preloadError`, and lib/boot.ts answers
 * that with a page reload (meant for chunks that vanished after a deploy). The trait
 * chunk is optional: when a blocker drops it, fall back instead of reloading. This
 * listener is registered when this module loads, i.e. before installPreloadRecovery().
 */
if (typeof window !== 'undefined') {
  window.addEventListener('vite:preloadError', (event) => {
    if (loading) event.stopImmediatePropagation();
  });
}

/** The fallback: what every browser exposes, hashed. */
export async function coarseTraits(): Promise<DeviceTraits> {
  const s = window.screen;
  const ua = navigator.userAgent;
  const basic = [
    ua,
    navigator.language,
    `${s.width}x${s.height}@${window.devicePixelRatio || 1}`,
    Intl.DateTimeFormat().resolvedOptions().timeZone || '',
  ].join('|');
  return { hash: await sha256Hex(basic), components: { ua, fallback: true } };
}

async function load(): Promise<DeviceTraits> {
  loading = true;
  try {
    const mod = await import('./traits');
    loading = false;
    return await mod.collectTraits();
  } catch (err) {
    loading = false;
    debugLog('device traits unavailable', String(err));
    return coarseTraits();
  }
}

/** Collects (and caches) the traits. Never rejects. */
export function getDeviceTraits(): Promise<DeviceTraits> {
  cached ??= load();
  return cached;
}

/** Forget the cached value (tests). */
export function resetDeviceTraits(): void {
  cached = null;
}
