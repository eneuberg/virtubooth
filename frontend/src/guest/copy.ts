/**
 * Presentation of the server's texts (join sheet, taglines) and the guest-side copy
 * that has no better home.
 *
 * The join texts come from the server (ConsentInfo, versioned with VB_CONSENT_VERSION);
 * the client only typesets them: emoji are dropped (Lucide is the icon system, no
 * emoji in chrome), a straight apostrophe between letters becomes ’, spaces collapse.
 * The words stay the server's.
 */
import { isIOS } from '@/sdk/platform';
import type { JoinInfo } from '@/sdk/session';

const EMOJI = /\p{Extended_Pictographic}(?:️|‍\p{Extended_Pictographic})*️?/gu;

/** "Alles klar, los geht's! 🍻" → "Alles klar, los geht’s!" */
export function tidy(text: string): string {
  return text
    .replace(EMOJI, '')
    .replace(/(\p{L})'(\p{L})/gu, '$1’$2')
    .replace(/\s+([!?.,:;])/g, '$1')
    .replace(/\s{2,}/g, ' ')
    .trim();
}

/**
 * The join paragraphs as the sheet shows them: the first and the last paragraph
 * up front (what happens with the photos; what to do if you don't want that), the
 * ones in between (details such as device recognition) behind "Mehr dazu".
 */
export function splitParagraphs(paragraphs: ReadonlyArray<string>): { lead: string[]; more: string[] } {
  const clean = paragraphs.map(tidy).filter(Boolean);
  if (clean.length <= 2) return { lead: clean, more: [] };
  return { lead: [clean[0] ?? '', clean.at(-1) ?? ''], more: clean.slice(1, -1) };
}

/**
 * "Dein Instagram (freiwillig). Dann markieren wir dich!" → label
 * "Dein Instagram (freiwillig)" and helper "Dann markieren wir dich!": a field label
 * is a name, not a sentence.
 */
export function splitPrompt(prompt: string): { label: string; help: string | null } {
  const text = tidy(prompt);
  const m = /^(.+?)[.!:]\s+(.+)$/u.exec(text);
  if (!m?.[1] || !m[2]) return { label: text.replace(/[.:]$/, ''), help: null };
  return { label: m[1], help: m[2] };
}

/**
 * "Was passiert mit meinen Fotos?" before the session knows the server's join texts
 * (every identified answer carries them, so this is a safety net). Says the same as
 * the join texts, in short.
 */
export function fallbackJoinText(instagramAccount: string): string[] {
  const where = instagramAccount ? ` auf Instagram (${instagramAccount})` : ' auf Instagram';
  return [
    `Deine Fotos speichert die Party-Seite, die Gastgeber sehen sie und dürfen sie${where} posten.`,
    'Damit sie Missbrauch verhindern können, erkennt die Seite dein Gerät wieder: eine anonyme Geräte-ID, kein Name.',
    'Wenn du das nicht möchtest, mach hier bitte keine Fotos.',
  ];
}

/** The join texts to show read-only: the server's, else the fallback. */
export function joinTextFor(texts: JoinInfo | null, instagramAccount: string): string[] {
  return texts ? texts.paragraphs.map(tidy).filter(Boolean) : fallbackJoinText(instagramAccount);
}

/**
 * In-app browsers (Instagram, WhatsApp, …) often get no camera, and "open in browser"
 * from their menu loses the party access (the QR token is gone from the address), so
 * the advice is to scan the QR code with the phone's camera app.
 */
export function inAppAdvice(app: string | null): { title: string; text: string } {
  const where = app ? `im Browser von ${app}` : 'im Browser einer App';
  const camera = isIOS() ? 'die Kamera-App' : 'die Kamera-App (oder Google Lens)';
  return {
    title: 'Hier geht die Kamera oft nicht',
    text: `Du bist gerade ${where}. Öffne ${camera} deines Handys und scanne den QR-Code damit: Dann öffnet sich die Seite im richtigen Browser.`,
  };
}
