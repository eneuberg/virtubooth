import type { LucideIcon } from 'lucide-react';
import {
  Button as AriaButton,
  OverlayArrow,
  Tooltip,
  TooltipTrigger,
  type ButtonProps as AriaButtonProps,
} from 'react-aria-components';
import { tv, type VariantProps } from './cx';
import { useSurface } from './Surface';

export const iconButtonStyles = tv({
  base: [
    'relative inline-grid shrink-0 cursor-pointer place-items-center rounded-control select-none',
    'transition-[background-color,color,transform] duration-(--duration-quick)',
    'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
    'disabled:cursor-not-allowed disabled:opacity-45 pressed:scale-95',
  ],
  variants: {
    variant: {
      /** toolbar, close, nav */
      plain: 'text-ink hover:bg-surface-hover',
      /** on the camera stage: switch camera, countdown */
      camera: 'bg-white/12 text-white hover:bg-white/20',
      /** round, over a photo (hide toggle) */
      overlay: 'rounded-full bg-black/55 text-white hover:bg-black/70 selected:bg-black/70',
    },
    size: {
      md: 'size-11 [&_svg]:size-6',
      lg: 'size-12 [&_svg]:size-6',
    },
  },
  defaultVariants: { variant: 'plain', size: 'md' },
});

export interface IconButtonProps
  extends
    Omit<AriaButtonProps, 'className' | 'children' | 'style' | 'aria-label'>,
    VariantProps<typeof iconButtonStyles> {
  /** what the button does; read by screen readers, shown as tooltip on hover */
  label: string;
  icon: LucideIcon;
  /** show the label as a tooltip on hover/focus (desktop) */
  tooltip?: boolean;
  className?: string;
}

/** An icon-only button. 44×44 (48 on the camera), always with an accessible label. */
export function IconButton({
  label,
  icon: Icon,
  variant,
  size,
  tooltip = false,
  className,
  ...props
}: IconButtonProps) {
  const surface = useSurface();
  const button = (
    <AriaButton
      {...props}
      aria-label={label}
      className={iconButtonStyles({ variant, size, class: className })}
    >
      <Icon aria-hidden="true" strokeWidth={2} />
    </AriaButton>
  );
  if (!tooltip) return button;
  return (
    <TooltipTrigger delay={600} closeDelay={100}>
      {button}
      <Tooltip
        offset={8}
        data-surface={surface}
        className="rounded-small bg-ink px-2 py-1 text-xs font-semibold text-surface shadow-float entering:animate-fade-in exiting:animate-fade-out"
      >
        <OverlayArrow className="fill-ink [&[data-placement=bottom]_svg]:rotate-180">
          <svg width={8} height={8} viewBox="0 0 8 8" aria-hidden="true">
            <path d="M0 0 L4 4 L8 0" />
          </svg>
        </OverlayArrow>
        {label}
      </Tooltip>
    </TooltipTrigger>
  );
}
