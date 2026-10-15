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

/** „Keine Weitergabe an externe KI“ (join sheet while the host has it on, and the „Du“ sheet). */
export const EXTERNAL_AI_OPT_OUT = {
  label: 'Keine Weitergabe an externe KI',
  help: 'Deine Fotos und Namen gehen nie an einen externen KI-Dienst. Die Auswertung hier auf dem Server läuft trotzdem.',
} as const;

/** The „Anzeigename“ field of the „Du“ sheet. */
export const DISPLAY_NAME = {
  label: 'Anzeigename',
  help: 'So sehen dich die anderen. Standard: dein Instagram-Name, sonst dein Zufallsname.',
  max: 24,
} as const;

/** The name the guest is shown with by default: „@<instagram>“, else the random name. */
export function defaultName(user: { instagram: string | null; name: string }): string {
  return user.instagram ? `@${user.instagram}` : user.name;
}

/**
 * The guest pass's first line: the chosen display name, else the handle, else the
 * random name without its number.
 */
export function passName(user: {
  display_name: string | null;
  instagram: string | null;
  name: string;
}): string {
  return user.display_name ?? (user.instagram ? `@${user.instagram}` : shortName(user.name));
}

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
