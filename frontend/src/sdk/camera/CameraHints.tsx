/**
 * Small pieces the camera pages share: the blocked-shutter explanation, the in-app
 * browser hint, the outbox line and the retry link on the film edge. OWNER: wave 2 "AC".
 */
import { CloudUpload, Lock, RotateCw, X } from 'lucide-react';
import { useState } from 'react';
import { Button as AriaButton } from 'react-aria-components';
import { waitingPhotos } from '@/lib/messages.de';
import { cx } from '@/ui/cx';
import { IconButton } from '@/ui/IconButton';
import { isInAppBrowser } from '../platform';

const INAPP_KEY = 'vb_inapp_dismissed';

/**
 * Why the shutter is locked (paused, stopped): said before the guest shoots. Pressing
 * the locked shutter bumps `nudge`: the line pops and is read out again (no second copy
 * of the same words in a toast).
 */
export function BlockedHint({ message, nudge = 0 }: { message: string; nudge?: number }) {
  return (
    <div aria-live="polite" data-testid="blocked-hint" data-nudge={nudge}>
      <p
        key={nudge}
        className={cx(
          'mx-auto max-w-[26rem] text-center text-sm text-pretty',
          nudge > 0 && 'motion-ok:animate-pop',
        )}
      >
        <Lock
          aria-hidden="true"
          className="-mt-0.5 mr-1.5 inline size-4 align-middle text-accent"
          strokeWidth={2.25}
        />
        {message}
      </p>
    </div>
  );
}

function readDismissed(): boolean {
  try {
    return localStorage.getItem(INAPP_KEY) === '1';
  } catch {
    return false;
  }
}

/** Instagram & co. open links in their own browser, often without a camera: say so once. */
export function InAppHint() {
  const [show, setShow] = useState(() => isInAppBrowser() && !readDismissed());
  if (!show) return null;
  return (
    <div
      data-testid="inapp-hint"
      className="mx-4 flex items-center gap-2 rounded-control bg-white/10 py-1 pr-1 pl-3 text-left text-sm"
    >
      <p className="flex-1">
        Kamera geht nicht? Öffne den Link in Safari oder Chrome (⋯ › „Im Browser öffnen“).
      </p>
      <IconButton
        label="Hinweis schließen"
        icon={X}
        onPress={() => {
          setShow(false);
          try {
            localStorage.setItem(INAPP_KEY, '1');
          } catch {
            // private mode: hidden for this visit
          }
        }}
      />
    </div>
  );
}

/** "2 Fotos warten · Erneut senden": photos in the outbox, one tap sends them. */
export function OutboxLine({
  pending,
  onSend,
  sending,
}: {
  pending: number;
  onSend: () => void;
  sending: boolean;
}) {
  if (pending === 0) return null;
  return (
    <AriaButton
      data-testid="outbox"
      onPress={onSend}
      isDisabled={sending}
      aria-label={`${waitingPhotos(pending)}. Erneut senden`}
      className={cx(
        'mx-auto inline-flex min-h-11 cursor-pointer items-center gap-2 rounded-control px-3 text-sm outline-none',
        'text-papier hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-wait',
      )}
    >
      <CloudUpload aria-hidden="true" className="size-5 text-accent" strokeWidth={2} />
      <span className="tabular">{waitingPhotos(pending)}</span>
      <span className="font-semibold text-accent underline underline-offset-3">
        {sending ? 'Sendet…' : 'Erneut senden'}
      </span>
    </AriaButton>
  );
}

/** The retry link at the end of the film edge under a print that waits. */
export function FilmRetry({
  onPress,
  waitSeconds,
  pending,
}: {
  onPress: () => void;
  waitSeconds: number;
  pending?: boolean;
}) {
  const label = waitSeconds > 0 ? `Erneut senden in ${waitSeconds} s` : 'Erneut senden';
  return (
    <AriaButton
      data-testid="retry"
      onPress={onPress}
      isDisabled={waitSeconds > 0 || pending === true}
      className={cx(
        'relative -my-1 inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-small px-2 text-sm font-semibold text-accent outline-none',
        'after:absolute after:inset-x-0 after:-inset-y-1 hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-focus',
        'disabled:cursor-not-allowed disabled:text-papier-muted',
      )}
    >
      <RotateCw aria-hidden="true" className="size-4" strokeWidth={2.25} />
      <span className="tabular">{label}</span>
    </AriaButton>
  );
}
