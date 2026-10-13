import type { LucideIcon } from 'lucide-react';
import { Radio, RadioGroup } from 'react-aria-components';
import { cx, tv } from './cx';

const styles = tv({
  slots: {
    group: 'inline-flex max-w-full gap-0.5 rounded-control p-[3px] whitespace-nowrap',
    item: [
      'flex flex-auto cursor-pointer items-center justify-center gap-1.5 rounded-[7px] px-3.5 font-semibold',
      'transition-colors duration-(--duration-quick) outline-none',
      'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus',
      'disabled:cursor-not-allowed disabled:opacity-45',
    ],
  },
  variants: {
    tone: {
      surface: {
        group: 'bg-surface-sunk',
        item: 'text-ink-muted hover:text-ink selected:bg-surface-raised selected:text-ink selected:shadow-[0_0_0_1px_var(--color-line)]',
      },
      camera: {
        group: 'bg-white/12',
        item: 'text-papier-muted hover:text-papier selected:bg-papier selected:text-kamera',
      },
    },
    size: {
      md: { group: 'h-12', item: 'text-sm' },
      sm: { group: 'h-10', item: 'text-sm' },
    },
  },
  defaultVariants: { tone: 'surface', size: 'md' },
});

export interface SegmentOption<K extends string> {
  id: K;
  label: string;
  icon?: LucideIcon;
}

export interface SegmentedControlProps<K extends string> {
  /** the group's accessible name ("Gefäß", "Sichtbarkeit") */
  label: string;
  options: ReadonlyArray<SegmentOption<K>>;
  value: K;
  onChange: (value: K) => void;
  tone?: 'surface' | 'camera';
  size?: 'md' | 'sm';
  /**
   * Hide the option labels visually (they stay accessible). "narrow" hides them only
   * below 420px, where Flasche/Becher, the 80px shutter and the camera switch do not
   * fit in one row.
   */
  iconOnly?: boolean | 'narrow';
  isDisabled?: boolean;
  className?: string;
  'data-testid'?: string;
}

/** 2–4 exclusive options as one radiogroup. Never wraps; with more options use Select. */
export function SegmentedControl<K extends string>({
  label,
  options,
  value,
  onChange,
  tone,
  size,
  iconOnly = false,
  isDisabled,
  className,
  ...rest
}: SegmentedControlProps<K>) {
  const s = styles({ tone, size });
  const hide = iconOnly === true ? 'sr-only' : iconOnly === 'narrow' ? 'max-[419px]:sr-only' : '';
  return (
    <RadioGroup
      aria-label={label}
      orientation="horizontal"
      value={value}
      onChange={(v) => {
        const option = options.find((o) => o.id === v);
        if (option) onChange(option.id);
      }}
      {...(isDisabled === undefined ? {} : { isDisabled })}
      data-testid={rest['data-testid']}
      className={cx(s.group(), className)}
    >
      {options.map(({ id, label: optionLabel, icon: Icon }) => (
        <Radio key={id} value={id} data-value={id} className={s.item()}>
          {Icon ? <Icon aria-hidden="true" className="size-5 shrink-0" strokeWidth={2} /> : null}
          <span className={Icon ? hide : undefined}>{optionLabel}</span>
        </Radio>
      ))}
    </RadioGroup>
  );
}
