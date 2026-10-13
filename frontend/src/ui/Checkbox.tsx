import { Check, Minus } from 'lucide-react';
import type { ReactNode } from 'react';
import { Checkbox as AriaCheckbox, type CheckboxProps as AriaCheckboxProps } from 'react-aria-components';
import { cx } from './cx';

export interface CheckboxProps extends Omit<AriaCheckboxProps, 'className' | 'children' | 'style'> {
  /** visible label; for `tile` pass aria-label instead */
  children?: ReactNode;
  /** `tile`: a box over a photo corner (44px hit area, no visible label) */
  variant?: 'plain' | 'tile';
  className?: string;
}

/** Label and box share one 44px hit target. Supports the mixed state (select all). */
export function Checkbox({ children, variant = 'plain', className, ...props }: CheckboxProps) {
  const tile = variant === 'tile';
  return (
    <AriaCheckbox
      {...props}
      className={cx(
        'group flex cursor-pointer items-center gap-3 outline-none select-none disabled:cursor-not-allowed disabled:opacity-50',
        tile ? 'size-11 justify-center' : 'min-h-11 text-sm',
        className,
      )}
    >
      {({ isSelected, isIndeterminate }) => (
        <>
          <span
            aria-hidden="true"
            className={cx(
              'grid size-6 shrink-0 place-items-center rounded-small border-2 border-field transition-colors duration-(--duration-quick)',
              tile && 'shadow-sm border-negativ-muted bg-white/90',
              'group-indeterminate:border-ink group-indeterminate:bg-ink group-indeterminate:text-surface group-selected:border-ink group-selected:bg-ink group-selected:text-surface',
              tile && 'group-selected:border-negativ group-selected:bg-negativ group-selected:text-white',
              'group-focus-visible:outline-2 group-focus-visible:outline-offset-2 group-focus-visible:outline-focus',
            )}
          >
            {isIndeterminate ? (
              <Minus className="size-4" strokeWidth={3} />
            ) : isSelected ? (
              <Check className="size-4" strokeWidth={3} />
            ) : null}
          </span>
          {children ? <span className="min-w-0">{children}</span> : null}
        </>
      )}
    </AriaCheckbox>
  );
}
