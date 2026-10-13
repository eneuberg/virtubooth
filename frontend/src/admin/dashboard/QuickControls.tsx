import { useQueryClient } from '@tanstack/react-query';
import { DoorClosed, OctagonPause, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button } from 'react-aria-components';
import { cx, tv } from '@/ui/cx';
import { Spinner } from '@/ui/Spinner';
import { useUploadStop } from '../store/hooks';
import { flipSwitch, handFocus, QUICK_TEST_ID, useJoinStop, useSwitchBusy, type QuickSwitch } from './data';
import { switchCopy } from './text';

const stopButton = tv({
  base: [
    'relative inline-flex min-h-11 min-w-0 cursor-pointer items-center justify-center gap-2 rounded-control px-3 py-1.5',
    'border-[1.5px] text-sm leading-tight font-semibold select-none hover:bg-surface-hover',
    'transition-[background-color,color,border-color,transform] duration-(--duration-quick) ease-out',
    'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
    'disabled:cursor-not-allowed disabled:opacity-60 aria-busy:cursor-wait aria-busy:opacity-100 pressed:scale-[0.98]',
  ],
  variants: {
    tone: {
      /** stop all uploads: the emergency red, like the switch in the upload sheet */
      danger: 'border-danger text-danger',
      /** stop joining: Safelight amber */
      accent: 'border-accent-ink text-accent-ink',
    },
  },
});

interface StopButtonProps {
  which: QuickSwitch;
  isKnown: boolean;
  icon: LucideIcon;
  tone: 'danger' | 'accent';
  children: ReactNode;
}

function StopButton({ which, isKnown, icon: Icon, tone, children }: StopButtonProps) {
  const qc = useQueryClient();
  const busy = useSwitchBusy((s) => s.busy);
  const pending = busy === which;
  const stop = async () => {
    if (await flipSwitch(qc, which, true)) handFocus(`status-strip-${which}-resume`);
  };
  return (
    <Button
      onPress={() => void stop()}
      isDisabled={!isKnown || (busy !== null && !pending)}
      aria-busy={pending || undefined}
      data-testid={QUICK_TEST_ID[which]}
      data-state={isKnown ? 'off' : 'loading'}
      className={stopButton({ tone })}
    >
      {pending ? (
        <Spinner label="Wird umgeschaltet…" className="size-5 shrink-0" />
      ) : (
        <Icon aria-hidden="true" className="size-5 shrink-0 max-[419px]:hidden" strokeWidth={2} />
      )}
      <span className="min-w-0 text-center">{children}</span>
    </Button>
  );
}

/**
 * The dashboard's one-tap stops, side by side: stop all uploads and stop joining. No
 * confirmation on purpose. A button is there only while its stop is off: once it is on,
 * the status strip (with its resume button) is the one control for it, so a tap never
 * means "stop" and "resume" at the same time. One button left spans the row; with both
 * stops on there is no row at all.
 */
export function QuickControls({ className }: { className?: string }) {
  const { data: stop } = useUploadStop();
  const { data: join } = useJoinStop();
  const showUploads = !stop?.enabled;
  const showJoin = !join?.enabled;
  if (!showUploads && !showJoin) return null;
  return (
    <div data-testid="quick-controls" className={cx('grid auto-cols-fr grid-flow-col gap-2', className)}>
      {showUploads ? (
        <StopButton which="uploads" tone="danger" icon={OctagonPause} isKnown={stop !== undefined}>
          {switchCopy('uploads', stop).toggle}
        </StopButton>
      ) : null}
      {showJoin ? (
        <StopButton which="join" tone="accent" icon={DoorClosed} isKnown={join !== undefined}>
          {switchCopy('join', join).toggle}
        </StopButton>
      ) : null}
    </div>
  );
}
