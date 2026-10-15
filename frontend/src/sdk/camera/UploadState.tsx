/**
 * The result's headline on a camera page: where the photo is on its way to the party.
 * „Wird hochgeladen…“ → „Hochgeladen“, or why it is not there yet (offline, too many at
 * once, paused …) and that it is kept. The live state of the shot (useShot), never a
 * timer. One polite live region (<output>, role status); every state has an icon AND words.
 * The film edge under the print keeps the frame number, the percentage (its progress bar
 * announces it, the live region does not) and „Erneut senden“.
 */
import { CircleAlert, CloudCheck, CloudOff, Hourglass, LoaderCircle, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { t } from '@/lib/messages.de';
import { cx } from '@/ui/cx';
import { shotErrorText, type Shot } from './useShot';

export interface UploadStateProps {
  shot: Pick<Shot, 'status' | 'error' | 'stored'>;
  /** seconds until a rate-limited retry */
  waitSeconds: number;
  /** what happens once it is sent: „Es wird gesendet …“ (Fotobox), „Es wird gezählt …“ (Beer Cam) */
  verb?: 'gesendet' | 'gezählt';
  /** the line under „Hochgeladen“ */
  done?: ReactNode;
  /** appended to a refusal („Herunterladen geht trotzdem.“) */
  failedHint?: string;
}

/** Codes where the network (not the server) is the problem. */
const NETWORK_CODES: ReadonlySet<string> = new Set(['network', 'timeout']);

export function UploadState({ shot, waitSeconds, verb = 'gesendet', done, failedHint }: UploadStateProps) {
  const reason = shotErrorText(shot.error, waitSeconds);
  const kept = shot.stored
    ? ''
    : // only in memory (no IndexedDB, a private tab …): leaving the page loses it
      ' Lass die Seite offen, bis es hochgeladen ist.';
  let Icon: LucideIcon;
  let tone: string;
  let title: string;
  let detail: ReactNode = null;
  switch (shot.status) {
    case 'uploading':
      Icon = LoaderCircle;
      tone = 'text-papier motion-ok:animate-spin';
      title = t.uploading;
      break;
    case 'done':
      Icon = CloudCheck;
      tone = 'text-ok';
      title = t.uploaded;
      detail = done ?? null;
      break;
    case 'waiting':
      Icon = shot.error === null || NETWORK_CODES.has(shot.error.code) ? CloudOff : Hourglass;
      tone = 'text-accent';
      title = 'Noch nicht hochgeladen';
      detail = `${reason ? `${reason} ` : ''}Es wird ${verb}, sobald es geht.${kept}`;
      break;
    case 'held':
      Icon = Hourglass;
      tone = 'text-accent';
      title = 'Noch nicht hochgeladen';
      detail = `${reason ? `${reason} ` : ''}Es wird ${verb}, sobald du wieder hochladen kannst.${kept}`;
      break;
    default:
      Icon = CircleAlert;
      tone = 'text-danger';
      title = 'Nicht hochgeladen';
      detail = `${reason}${failedHint ? ` ${failedHint}` : ''}`.trim() || null;
  }
  return (
    // data-state: the shot's upload status (uploading, done, waiting, held, failed)
    // <output>: role="status", a polite live region
    <output
      data-testid="result-text"
      data-state={shot.status}
      className="grid justify-items-center gap-1 landscape-phone:justify-items-start"
    >
      {/* spans: <output> takes phrasing content only */}
      <span
        className="inline-flex items-center gap-2 text-lg leading-tight font-bold"
        data-testid="upload-title"
      >
        <Icon aria-hidden="true" className={cx('size-6 shrink-0', tone)} strokeWidth={2.25} />
        <span>{title}</span>
      </span>
      {detail ? <span className="block text-sm text-papier-muted">{detail}</span> : null}
    </output>
  );
}
