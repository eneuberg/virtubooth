import { ChevronDown } from 'lucide-react';
import { Button as AriaButton, type ButtonProps as AriaButtonProps } from 'react-aria-components';
import { cx } from './cx';

export type UploadsState = 'on' | 'paused-new' | 'stopped';

const LABEL: Record<UploadsState, string> = {
  on: 'Hochladen an',
  'paused-new': 'Neue pausiert',
  stopped: 'Gestoppt',
};

const TONE: Record<UploadsState, string> = {
  on: 'border-line-strong text-ink',
  'paused-new': 'border-accent-ink text-accent-ink',
  stopped: 'border-danger-fill bg-danger-fill text-on-danger hover:bg-danger-fill-hover',
};

export interface StatusPillProps extends Omit<AriaButtonProps, 'className' | 'children' | 'style'> {
  state: UploadsState;
  /** override the words, e.g. "Hochladen: an" in the sidebar */
  label?: string;
  className?: string;
}

/** The admin upload status (an / neue pausiert / gestoppt); opens the upload controls sheet. */
export function StatusPill({ state, label, className, ...props }: StatusPillProps) {
  return (
    <AriaButton
      {...props}
      data-state={state}
      className={cx(
        'inline-flex h-11 shrink-0 cursor-pointer items-center justify-between gap-2 rounded-control border pr-2.5 pl-3 text-sm font-semibold whitespace-nowrap',
        'outline-none hover:bg-surface-hover focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
        TONE[state],
        className,
      )}
    >
      {label ?? LABEL[state]}
      <ChevronDown aria-hidden="true" className="size-4" strokeWidth={2.25} />
    </AriaButton>
  );
}
