import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Switch as AriaSwitch, type SwitchProps as AriaSwitchProps } from 'react-aria-components';
import { cx, tv } from './cx';

const styles = tv({
  slots: {
    root: [
      'group relative flex cursor-pointer items-center gap-3 outline-none select-none',
      'disabled:cursor-not-allowed disabled:opacity-50 data-pending:cursor-wait',
      'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
    ],
    text: 'grid min-w-0 flex-1 gap-0.5',
    label: 'font-semibold',
    description: 'text-xs text-ink-muted',
    track: [
      'relative h-8 w-13 shrink-0 rounded-full bg-line-strong transition-colors duration-(--duration-quick)',
      'group-data-pending:animate-shimmer group-selected:bg-accent',
    ],
    thumb: [
      'shadow-sm absolute top-[3px] left-[3px] size-[26px] rounded-full bg-white',
      'transition-transform duration-(--duration-quick) ease-out',
      'group-selected:translate-x-5 group-selected:bg-on-accent',
    ],
  },
  variants: {
    variant: {
      /** label left, track right, inline */
      plain: { root: 'min-h-11', label: 'text-sm' },
      /** a full-width row on the sunk surface (settings) */
      row: { root: 'min-h-16 rounded-control bg-surface-sunk px-4 py-3', label: 'text-md' },
      /** the emergency control: outlined in red, filled red when on */
      emergency: {
        root: [
          'min-h-18 rounded-control border-[1.5px] border-danger px-4 py-3.5',
          'selected:border-danger-fill selected:bg-danger-fill selected:text-on-danger',
        ],
        label: 'text-md',
        description: 'group-selected:text-on-danger',
        track: 'group-selected:bg-white',
        thumb: 'group-selected:bg-danger-fill',
      },
    },
  },
  defaultVariants: { variant: 'plain' },
});

export interface SwitchProps extends Omit<AriaSwitchProps, 'className' | 'children' | 'style'> {
  /** what the switch turns on: "Neue Gäste pausieren" */
  children: ReactNode;
  /** one line: the current state or its effect ("Gestoppt seit 22:41") */
  description?: ReactNode;
  icon?: LucideIcon;
  variant?: 'plain' | 'row' | 'emergency';
  /** the request is running: input blocked, track pulses */
  isPending?: boolean;
  className?: string;
}

/** On/off with role="switch". The state is also said in words via `description`. */
export function Switch({
  children,
  description,
  icon: Icon,
  variant,
  isPending = false,
  isDisabled,
  className,
  ...props
}: SwitchProps) {
  const s = styles({ variant });
  return (
    <AriaSwitch
      {...props}
      isDisabled={isDisabled === true || isPending}
      data-pending={isPending || undefined}
      aria-busy={isPending || undefined}
      className={cx(s.root(), className)}
    >
      {Icon ? <Icon aria-hidden="true" className="size-7 shrink-0" strokeWidth={1.75} /> : null}
      <span className={s.text()}>
        <span className={s.label()}>{children}</span>
        {description ? <span className={s.description()}>{description}</span> : null}
      </span>
      <span aria-hidden="true" className={s.track()}>
        <span className={s.thumb()} />
      </span>
    </AriaSwitch>
  );
}
