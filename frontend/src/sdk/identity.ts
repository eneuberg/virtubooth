/**
 * Small helpers around the guest's identity: the pseudonym and the Instagram name.
 */

/** "Verrückte Ente #3" → "Verrückte Ente" */
export function shortName(name: string): string {
  return name.replace(/\s*#\d+$/, '');
}

/** „Meine Fotos nicht automatisch auswerten“ (join sheet and the „Du“ sheet). */
export const ANALYSIS_OPT_OUT = {
  label: 'Meine Fotos nicht automatisch auswerten',
  help: 'Dann zählt die Live-Wall auf deinen Fotos keine Gesichter oder Hände, nur Helligkeit und Farben.',
} as const;

/** 30 characters is Instagram's limit */
export const HANDLE_MAX = 30;

/** "@party.anna" → "party.anna"; leading spaces and @ go. */
export function cleanHandle(value: string): string {
  return value.replace(/^[\s@]+/, '');
}

/** The handle inside a pasted profile link, or null for plain text. */
export function handleFromLink(text: string): string | null {
  const m = /instagram\.com\/([A-Za-z0-9._]+)/i.exec(text);
  return m?.[1] ?? null;
}
