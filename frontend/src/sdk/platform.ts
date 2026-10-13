/**
 * Platform checks. OWNER: wave 2 "GP". Ported from core/camera.js (kept as is).
 */

export function isIOS(ua: string = navigator.userAgent): boolean {
  return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

/** Instagram, Facebook, TikTok & co. open links in their own browser, often without camera access. */
export function isInAppBrowser(ua: string = navigator.userAgent): boolean {
  return /Instagram|FBAN|FBAV|FB_IAB|Line\/|Snapchat|TikTok|musical_ly|Twitter|LinkedInApp|GSA\//i.test(ua);
}
