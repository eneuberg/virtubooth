import { useQueryClient } from '@tanstack/react-query';
import { DoorClosed, OctagonPause, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { ToggleButton } from 'react-aria-components';
import { cx, tv } from '@/ui/cx';
import { Spinner } from '@/ui/Spinner';
import { useUploadStop } from '../store/hooks';
import { flipSwitch, useJoinStop, useSwitchBusy, type QuickSwitch } from './data';
import { switchCopy } from './text';

const toggle = tv({
  base: [
    'relative inline-flex min-h-11 min-w-0 cursor-pointer items-center justify-center gap-2 rounded-control px-3 py-1.5',
    'border-[1.5px] text-sm leading-tight font-semibold select-none',
    'transition-[background-color,color,border-color,transform] duration-(--duration-quick) ease-out',
    'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
    'disabled:cursor-not-allowed disabled:opacity-60 aria-busy:cursor-wait aria-busy:opacity-100 pressed:scale-[0.98]',
  ],
  variants: {
    tone: {
      /** stop all uploads: the emergency red, like the switch in the upload sheet */
      danger: [
        'border-danger text-danger hover:bg-surface-hover',
        'selected:border-danger-fill selected:bg-danger-fill selected:text-on-danger selected:hover:bg-danger-fill-hover',
      ],
      /** stop joining: Safelight amber */
      accent: [
        'border-accent-ink text-accent-ink hover:bg-surface-hover',
        'selected:border-accent selected:bg-accent selected:text-on-accent selected:hover:bg-accent-hover',
      ],
    },
  },
});

interface QuickToggleProps {
  which: QuickSwitch;
  isSelected: boolean;
  isKnown: boolean;
  icon: LucideIcon;
  tone: 'danger' | 'accent';
  children: ReactNode;
}

function QuickToggle({ which, isSelected, isKnown, icon: Icon, tone, children }: QuickToggleProps) {
  const qc = useQueryClient();
  const busy = useSwitchBusy((s) => s.busy);
  const pending = busy === which;
  return (
    <ToggleButton
      isSelected={isSelected}
      onChange={(on) => void flipSwitch(qc, which, on)}
      isDisabled={!isKnown || (busy !== null && !pending)}
      aria-busy={pending || undefined}
      data-testid={which === 'uploads' ? 'quick-upload-stop' : 'quick-join-stop'}
      data-state={isKnown ? (isSelected ? 'on' : 'off') : 'loading'}
      className={toggle({ tone })}
    >
      {pending ? (
        <Spinner label="Wird umgeschaltet…" className="size-5 shrink-0" />
      ) : (
        <Icon aria-hidden="true" className="size-5 shrink-0" strokeWidth={2} />
      )}
      <span className="min-w-0 text-left">{children}</span>
    </ToggleButton>
  );
}

/**
 * The two one-tap switches of the dashboard, side by side: stop all uploads and stop
 * joining. No confirmation on purpose. Pressed = on; the status strip says it in words
 * and carries the resume button too.
 */
export function QuickControls({ className }: { className?: string }) {
  const { data: stop } = useUploadStop();
  const { data: join } = useJoinStop();
  return (
    <div data-testid="quick-controls" className={cx('grid grid-cols-2 gap-2', className)}>
      <QuickToggle
        which="uploads"
        tone="danger"
        icon={OctagonPause}
        isSelected={stop?.enabled ?? false}
        isKnown={stop !== undefined}
      >
        {switchCopy('uploads', stop).toggle}
      </QuickToggle>
      <QuickToggle
        which="join"
        tone="accent"
        icon={DoorClosed}
        isSelected={join?.enabled ?? false}
        isKnown={join !== undefined}
      >
        {switchCopy('join', join).toggle}
      </QuickToggle>
    </div>
  );
}
