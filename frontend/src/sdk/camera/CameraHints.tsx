/**
 * Small pieces the camera pages share: the status row under the stage (GP's StatusSlot
 * plus "Erneut senden" when photos wait) and the retry link on the film edge.
 * OWNER: wave 2 "AC".
 */
import { CloudUpload, RotateCw } from 'lucide-react';
import { Button as AriaButton } from 'react-aria-components';
import { waitingPhotos } from '@/lib/messages.de';
import { cx } from '@/ui/cx';
import { StatusSlot } from '../components/StatusSlot';
import { useOutbox } from '../outbox';
import { useGuestStatus } from '../status';

/**
 * The status row on the camera: GP's StatusSlot ("Hochladen pausiert", "Offline",
 * "1 Foto wartet"; tap explains) and, while photos wait, "Erneut senden".
 */
export function CameraStatus({ onSend, sending }: { onSend: () => void; sending: boolean }) {
  const { pending } = useOutbox();
  const status = useGuestStatus();
  return (
    <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 empty:hidden landscape-phone:justify-start">
      <StatusSlot />
      {pending > 0 && status.kind !== 'banned' ? (
        <AriaButton
          data-testid="outbox"
          onPress={onSend}
          isDisabled={sending}
          aria-label={`${waitingPhotos(pending)}. Erneut senden`}
          className={cx(
            'inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-control px-3 text-sm font-semibold text-accent outline-none',
            'underline underline-offset-3 hover:bg-white/10 focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-wait',
          )}
        >
          <CloudUpload aria-hidden="true" className="size-5" strokeWidth={2} />
          {sending ? 'Sendet…' : 'Erneut senden'}
        </AriaButton>
      ) : null}
    </div>
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
