/**
 * Dashboard words and numbers (pure; text.test.ts). Glossary: "Hochladen" as in the
 * party switches ("Hochladen für alle stoppen"), "Anmeldung" for joining the party.
 */
import type { Overview } from '@/api/types';
import { NBSP } from '@/lib/format';
import { clock } from '../lib/labels';

/** "5 min" with the NBSP the copy rules want. */
export function minutes(n: number): string {
  return `${n}${NBSP}min`;
}

export interface Stat {
  id: string;
  label: string;
  value: number;
}

/** The compact strip on Live: the six numbers a host glances at. */
export function liveStats(o: Overview): Stat[] {
  return [
    { id: 'active', label: 'Aktiv jetzt', value: o.guests.active_now },
    { id: 'uploading', label: 'Laden hoch', value: o.guests.uploading_now },
    { id: 'recent', label: `Fotos in ${minutes(15)}`, value: o.photos.last_15_min },
    { id: 'scanned', label: 'Gescannt', value: o.scans.scanned },
    { id: 'not-joined', label: 'Nicht beigetreten', value: o.scans.not_joined },
    { id: 'guests', label: 'Gäste', value: o.guests.total },
  ];
}

/** The line under the strip: what "jetzt" means, and how fresh the numbers are. */
export function freshness(o: Overview, now?: Date): string {
  return `„Jetzt“: letzte ${minutes(o.active_minutes)}, Stand ${clock(o.at, now)}.`;
}

/** Since when visitors are counted (older guests have no scan). */
export function scansSince(o: Overview, now?: Date): string {
  return o.scans.since ? `Gezählt seit ${clock(o.scans.since, now)}.` : 'Noch niemand hat gescannt.';
}
