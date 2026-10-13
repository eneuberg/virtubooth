import { useQueryClient } from '@tanstack/react-query';
import { DoorClosed, OctagonPause, type LucideIcon } from 'lucide-react';
import { Button } from 'react-aria-components';
import type { StopState } from '@/api/types';
import { cx, tv } from '@/ui/cx';
import { Spinner } from '@/ui/Spinner';
import { useUploadStop } from '../store/hooks';
import { flipSwitch, useJoinStop, useSwitchBusy, type QuickSwitch } from './data';
import { switchCopy } from './text';

const row = tv({
  slots: {
    root: 'flex items-center gap-2.5 py-1.5 pr-2 pl-4',
    icon: 'size-5 shrink-0',
    action: [
      'relative inline-flex h-11 shrink-0 cursor-pointer items-center justify-center rounded-control px-4',
      'text-sm font-semibold whitespace-nowrap outline-none select-none',
      'transition-[background-color,transform] duration-(--duration-quick) ease-out pressed:scale-[0.98]',
      'focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-wait',
    ],
  },
  variants: {
    tone: {
      /** uploads stopped: the emergency red of the upload sheet */
      danger: {
        root: 'bg-danger-fill text-on-danger',
        action: 'bg-on-danger text-danger-fill hover:bg-on-danger/90 focus-visible:outline-on-danger',
      },
      /** joining stopped: Safelight amber */
      accent: {
        root: 'bg-accent text-on-accent',
        action: 'bg-on-accent text-accent hover:bg-on-accent/90 focus-visible:outline-on-accent',
      },
    },
  },
});

function StripRow({
  which,
  state,
  icon: Icon,
  tone,
}: {
  which: QuickSwitch;
  state: StopState;
  icon: LucideIcon;
  tone: 'danger' | 'accent';
}) {
  const qc = useQueryClient();
  const busy = useSwitchBusy((s) => s.busy);
  const copy = switchCopy(which, state);
  const s = row({ tone });
  return (
    <div className={s.root()} data-testid={`status-strip-${which}`}>
      <Icon aria-hidden="true" className={s.icon()} strokeWidth={2} />
      <p className="grid min-w-0 flex-1">
        <strong className="text-sm leading-tight font-bold lg:text-md">{copy.title}</strong>
        <span className="text-xs tabular">
          {copy.detail} <span className="max-sm:hidden">{copy.effect}</span>
        </span>
      </p>
      <Button
        className={s.action()}
        aria-label={copy.resumeLabel}
        isDisabled={busy !== null}
        onPress={() => void flipSwitch(qc, which, false)}
        data-testid={`status-strip-${which}-resume`}
      >
        {busy === which ? <Spinner label="Wird umgeschaltet…" /> : copy.resume}
      </Button>
    </div>
  );
}

/**
 * The unmistakable state of the two stops: a full-width strip in the header, one row
 * per stop that is on, each with its resume button. Nothing while both are off. The
 * wrapper is a polite live region, so switching (here, in another tab or on another
 * device, through the event stream) is announced.
 */
export function StatusStrip({ className }: { className?: string }) {
  const { data: stop } = useUploadStop();
  const { data: join } = useJoinStop();
  const any = Boolean(stop?.enabled || join?.enabled);
  return (
    <div
      aria-live="polite"
      data-testid="status-strip"
      data-state={any ? 'on' : 'off'}
      className={cx('grid', className)}
    >
      {stop?.enabled ? <StripRow which="uploads" state={stop} icon={OctagonPause} tone="danger" /> : null}
      {join?.enabled ? <StripRow which="join" state={join} icon={DoorClosed} tone="accent" /> : null}
    </div>
  );
}
