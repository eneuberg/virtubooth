import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import {
  Button as AriaButton,
  Link as AriaLink,
  type ButtonProps as AriaButtonProps,
  type LinkProps as AriaLinkProps,
} from 'react-aria-components';
import { cx, tv, type VariantProps } from './cx';
import { Spinner } from './Spinner';

export const buttonStyles = tv({
  base: [
    'relative inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 rounded-control',
    'font-semibold whitespace-nowrap no-underline select-none',
    'transition-[background-color,color,border-color,transform] duration-(--duration-quick) ease-out',
    'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
    'disabled:cursor-not-allowed disabled:opacity-45 pending:cursor-wait pressed:scale-[0.98]',
  ],
  variants: {
    variant: {
      /** the one main action of a view (Safelight) */
      primary: 'bg-accent text-on-accent hover:bg-accent-hover',
      secondary: 'border border-line-strong text-ink hover:bg-surface-hover',
      quiet: 'text-ink hover:bg-surface-hover',
      danger: 'bg-danger-fill text-on-danger hover:bg-danger-fill-hover',
      /** destructive but secondary (opens a confirm step) */
      'danger-outline': 'border border-danger text-danger hover:bg-surface-hover',
      /** on the black camera stage, over a live picture */
      camera: 'bg-black/60 text-white ring-1 ring-white/20 ring-inset hover:bg-black/75',
    },
    size: {
      lg: 'h-14 px-6 text-md',
      md: 'h-12 px-5 text-md',
      sm: 'h-11 px-4 text-sm',
      /** dense desktop admin: 36px visual, 44px hit area */
      xs: 'h-9 px-3 text-sm after:absolute after:inset-x-0 after:-inset-y-1',
    },
    block: { true: 'w-full' },
    iconOnly: { true: 'px-0' },
  },
  compoundVariants: [
    { iconOnly: true, size: 'lg', class: 'w-14' },
    { iconOnly: true, size: 'md', class: 'w-12' },
    { iconOnly: true, size: 'sm', class: 'w-11' },
    { iconOnly: true, size: 'xs', class: 'w-9' },
  ],
  defaultVariants: { variant: 'secondary', size: 'md' },
});

type StyleProps = Omit<VariantProps<typeof buttonStyles>, 'iconOnly'>;

export interface ButtonProps extends Omit<AriaButtonProps, 'className' | 'children' | 'style'>, StyleProps {
  children: ReactNode;
  /** leading icon (lucide), decorative */
  icon?: LucideIcon;
  /** trailing icon, e.g. a chevron */
  iconEnd?: LucideIcon;
  /** text the spinner announces while pending; the label keeps its width */
  pendingLabel?: string;
  className?: string;
}

function Label({
  icon: Icon,
  iconEnd: IconEnd,
  children,
}: Pick<ButtonProps, 'icon' | 'iconEnd' | 'children'>) {
  return (
    <>
      {Icon ? <Icon aria-hidden="true" className="size-5 shrink-0" strokeWidth={2} /> : null}
      {children}
      {IconEnd ? <IconEnd aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.25} /> : null}
    </>
  );
}

/**
 * A button: verb label, optional icon, never emoji. `isPending` keeps the width and
 * shows a spinner (React Aria keeps focus and blocks presses meanwhile).
 */
export function Button({
  children,
  icon,
  iconEnd,
  variant,
  size,
  block,
  pendingLabel = 'Lädt…',
  className,
  ...props
}: ButtonProps) {
  return (
    <AriaButton {...props} className={buttonStyles({ variant, size, block, class: className })}>
      {({ isPending }) => (
        <>
          <span className={cx('inline-flex items-center gap-2', isPending && 'invisible')}>
            <Label icon={icon} iconEnd={iconEnd}>
              {children}
            </Label>
          </span>
          {isPending ? (
            <span className="absolute inset-0 grid place-items-center">
              <Spinner label={pendingLabel} />
            </span>
          ) : null}
        </>
      )}
    </AriaButton>
  );
}

export interface LinkButtonProps extends Omit<AriaLinkProps, 'className' | 'children' | 'style'>, StyleProps {
  children: ReactNode;
  icon?: LucideIcon;
  iconEnd?: LucideIcon;
  className?: string;
}

/** Navigation that looks like a button ("Zum Start"). Renders a real <a href>. */
export function LinkButton({
  children,
  icon,
  iconEnd,
  variant,
  size,
  block,
  className,
  ...props
}: LinkButtonProps) {
  return (
    <AriaLink {...props} className={buttonStyles({ variant, size, block, class: className })}>
      <Label icon={icon} iconEnd={iconEnd}>
        {children}
      </Label>
    </AriaLink>
  );
}
