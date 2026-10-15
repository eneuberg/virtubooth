/**
 * Upload controls as words and states (pure; uploadState.test.ts).
 *
 * The levers, from the BRIEF: "Hochladen für alle stoppen" (emergency switch, nobody
 * uploads), "Anmeldung stoppen", "Neue Gäste pausieren" (who joins from now on waits for
 * approval; switching it off asks: release those guests, or keep them paused) and the
 * per-guest pause.
 */
import type { AdminUser, PauseState, StopState } from '@/api/types';
import { formatDateTime } from '@/lib/format';
import { clock, guestCount } from '../lib/labels';

export interface PartyControlsCopy {
  uploads: string;
  join: string;
  pause: string;
}

/** The state line under each of the three switches (PartyControls). */
export function partyControlsCopy(
  stop: StopState | undefined,
  join: StopState | undefined,
  pause: PauseState | undefined,
  now?: Date,
): PartyControlsCopy {
  const loading = 'Lädt…';
  return {
    uploads: !stop
      ? loading
      : stop.enabled
        ? `Gestoppt seit ${clock(stop.since, now)}.`
        : 'Alle können hochladen.',
    join: !join
      ? loading
      : join.enabled
        ? `Gestoppt seit ${clock(join.since, now)}.`
        : 'Neue Gäste können beitreten.',
    pause: !pause ? loading : pause.enabled ? pauseDescription(pause, now) : 'Neue Gäste laden sofort hoch.',
  };
}

/** One line under "Neue Gäste pausieren". */
export function pauseDescription(pause: PauseState, now?: Date): string {
  if (!pause.enabled) return 'Wer ab jetzt beitritt, kann erst nach Freigabe hochladen.';
  const affected =
    pause.affected === 0 ? 'noch niemand betroffen' : `${guestCount(pause.affected)} betroffen`;
  return `Seit ${clock(pause.since, now)}, ${affected}.`;
}

export interface EndPausePlan {
  /** false: nobody joined during the pause, switch it off without asking */
  ask: boolean;
  affected: number;
  text: string;
  restoreLabel: string;
  keepLabel: string;
}

/** What switching the new-guest pause off has to ask. */
export function endPausePlan(pause: PauseState): EndPausePlan {
  const n = pause.affected;
  const one = n === 1;
  return {
    ask: n > 0,
    affected: n,
    text: one
      ? '1 Gast ist während der Pause beigetreten und kann noch nicht hochladen. Was soll mit ihm passieren?'
      : `${n} Gäste sind während der Pause beigetreten und können noch nicht hochladen. Was soll mit ihnen passieren?`,
    restoreLabel: one ? 'Freischalten' : `Alle ${n} freischalten`,
    keepLabel: one ? 'Pausiert lassen' : `Alle ${n} pausiert lassen`,
  };
}

/** The answer of ending the pause, in one sentence. */
export function endPauseResult(res: { restored: number; kept: number }): string {
  if (res.restored > 0) return `${guestCount(res.restored)} wieder freigeschaltet.`;
  if (res.kept > 0) {
    return `Neue Gäste können wieder hochladen. ${guestCount(res.kept)} ${res.kept === 1 ? 'bleibt' : 'bleiben'} pausiert.`;
  }
  return 'Neue Gäste können wieder hochladen.';
}

/** Why a guest is paused, short (a list row): "automatisch, seit 22:41" / "von Hand, seit 22:41". */
export function pauseSourceShort(
  user: Pick<AdminUser, 'uploads_paused' | 'uploads_paused_source' | 'uploads_paused_at'>,
  now?: Date,
): string | null {
  if (!user.uploads_paused) return null;
  const how = user.uploads_paused_source === 'new_guest_lock' ? 'automatisch' : 'von Hand';
  return `${how}, seit ${clock(user.uploads_paused_at, now)}`;
}

/** Why a guest is paused: by hand, or by the new-guest pause (still running or not). */
export function pauseSource(
  user: Pick<
    AdminUser,
    'uploads_paused' | 'uploads_paused_source' | 'uploads_paused_at' | 'uploads_lock_period'
  >,
  pause: PauseState | undefined,
  now?: Date,
): string | null {
  if (!user.uploads_paused) return null;
  if (user.uploads_paused_source === 'new_guest_lock') {
    if (pause?.enabled && pause.period === user.uploads_lock_period) {
      return `automatisch: neue Gäste pausiert seit ${clock(pause.since, now)}`;
    }
    return `automatisch: während der Pause für neue Gäste beigetreten (${formatDateTime(user.uploads_paused_at ?? '')})`;
  }
  return `von Hand pausiert seit ${clock(user.uploads_paused_at, now)}`;
}

/** The three switches in one sentence, for screen readers (a polite live region). */
export function partySummary(
  stop: StopState | undefined,
  join: StopState | undefined,
  pause: PauseState | undefined,
  now?: Date,
): string {
  if (!stop || !join || !pause) return '';
  const parts = [
    stop.enabled ? `Hochladen für alle gestoppt seit ${clock(stop.since, now)}.` : 'Hochladen läuft.',
    join.enabled ? `Anmeldung gestoppt seit ${clock(join.since, now)}.` : 'Anmeldung offen.',
  ];
  if (pause.enabled) parts.push(`Neue Gäste pausiert seit ${clock(pause.since, now)}.`);
  return parts.join(' ');
}
