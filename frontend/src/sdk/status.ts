/**
 * The guest's status in one value: banned > paused > stopped > offline > photos
 * waiting > ok. Drives the status slot, the guest pass dot and the "Du" sheet.
 */
import { Ban, CircleCheck, CloudOff, Hourglass, Pause, type LucideIcon } from 'lucide-react';
import { useSyncExternalStore } from 'react';
import { msg, t, waitingPhotos } from '@/lib/messages.de';
import { useOutbox } from './outbox';
import { isOnline, subscribeOnline } from './platform';
import { useSession, type SessionState } from './session';

export type GuestStatusKind = 'ok' | 'banned' | 'paused' | 'stopped' | 'offline' | 'waiting';

export interface GuestStatus {
  kind: GuestStatusKind;
  /** short, for the slot and the guest pass: "Hochladen pausiert" */
  label: string;
  /** the sheet title */
  title: string;
  /** plain words: what it means and what happens next */
  text: string;
  tone: 'ok' | 'warn' | 'danger' | 'muted';
  icon: LucideIcon;
}

const OK: GuestStatus = {
  kind: 'ok',
  label: 'Hochladen an',
  title: 'Alles bereit',
  text: 'Du kannst Fotos machen und hochladen.',
  tone: 'ok',
  icon: CircleCheck,
};

/** navigator.onLine as React state */
export function useOnline(): boolean {
  return useSyncExternalStore(subscribeOnline, isOnline, () => true);
}

/** Pure: the status for a session, connectivity and the number of waiting photos. */
export function guestStatus(session: SessionState, online: boolean, waiting: number): GuestStatus {
  const banned = session.status === 'banned' || (session.status === 'ready' && session.user.banned);
  if (banned) {
    return {
      kind: 'banned',
      label: t.banned,
      title: msg.bannedTitle,
      text: msg.bannedText,
      tone: 'danger',
      icon: Ban,
    };
  }
  if (session.status === 'ready' && session.user.uploads_paused) {
    return {
      kind: 'paused',
      label: t.uploadsPaused,
      title: msg.pausedTitle,
      text: `${msg.pausedText} Du kannst dich weiter umsehen und deinen Instagram-Namen ändern.`,
      tone: 'warn',
      icon: Pause,
    };
  }
  if (session.status === 'ready' && session.uploadsStopped) {
    return {
      kind: 'stopped',
      label: t.uploadsStoppedGuest,
      title: msg.stoppedTitle,
      text: 'Die Gastgeber haben das Hochladen gerade für alle angehalten. Gleich geht’s weiter, dann verschwindet dieser Hinweis von selbst.',
      tone: 'warn',
      icon: Pause,
    };
  }
  if (!online) {
    return {
      kind: 'offline',
      label: msg.offlineShort,
      title: 'Kein Netz',
      text: 'Dein Handy ist gerade offline. Sobald du wieder Netz hast, geht’s weiter.',
      tone: 'muted',
      icon: CloudOff,
    };
  }
  if (waiting > 0) {
    return {
      kind: 'waiting',
      label: waitingPhotos(waiting),
      title: waitingPhotos(waiting),
      text: 'Sie sind auf deinem Handy gespeichert und werden gesendet, sobald es wieder geht.',
      tone: 'muted',
      icon: Hourglass,
    };
  }
  return OK;
}

/** The guest's current status (session, connectivity, outbox). */
export function useGuestStatus(): GuestStatus {
  const session = useSession();
  const online = useOnline();
  const { pending } = useOutbox();
  return guestStatus(session, online, pending);
}
