/**
 * Platform checks. isIOS / isInAppBrowser are ported from core/camera.js; the
 * in-app browser list also knows WhatsApp now (only used for hints).
 */

interface NavigatorPlatform {
  /** deprecated, but the only iPadOS-as-Mac tell */
  platform?: string;
  maxTouchPoints?: number;
}

export function isIOS(ua: string = navigator.userAgent): boolean {
  const nav: NavigatorPlatform = typeof navigator === 'undefined' ? {} : navigator;
  return /iPad|iPhone|iPod/.test(ua) || (nav.platform === 'MacIntel' && (nav.maxTouchPoints ?? 0) > 1);
}

export function isAndroid(ua: string = navigator.userAgent): boolean {
  return /Android/i.test(ua);
}

const IN_APP: ReadonlyArray<readonly [RegExp, string]> = [
  [/Instagram/i, 'Instagram'],
  [/FBAN|FBAV|FB_IAB|FBIOS/i, 'Facebook'],
  [/WhatsApp/i, 'WhatsApp'],
  [/Snapchat/i, 'Snapchat'],
  [/TikTok|musical_ly|BytedanceWebview/i, 'TikTok'],
  [/Line\//, 'LINE'],
  [/Twitter/i, 'X'],
  [/LinkedInApp/i, 'LinkedIn'],
  [/GSA\//, 'Google'],
];

/** The app whose built-in browser this is ("Instagram"), or null in a real browser. */
export function inAppBrowserName(ua: string = navigator.userAgent): string | null {
  for (const [re, name] of IN_APP) if (re.test(ua)) return name;
  return null;
}

/** Instagram, Facebook, TikTok & co. open links in their own browser, often without camera access. */
export function isInAppBrowser(ua: string = navigator.userAgent): boolean {
  return inAppBrowserName(ua) !== null;
}

/** navigator.onLine (true where unknown). */
export function isOnline(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine;
}

/** Calls back on online/offline changes; returns the unsubscribe. */
export function subscribeOnline(callback: () => void): () => void {
  window.addEventListener('online', callback);
  window.addEventListener('offline', callback);
  return () => {
    window.removeEventListener('online', callback);
    window.removeEventListener('offline', callback);
  };
}
