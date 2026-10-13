import { Check, ChevronDown } from 'lucide-react';
import type { Key } from 'react-aria-components';
import {
  Button as AriaButton,
  Label,
  ListBox,
  ListBoxItem,
  Popover,
  Select as AriaSelect,
  SelectValue,
} from 'react-aria-components';
import { cx } from './cx';
import { useSurface } from './Surface';

export interface SelectOption<K extends Key> {
  id: K;
  label: string;
}

export interface SelectProps<K extends Key> {
  label: string;
  /** show the label inside the trigger as a muted prefix ("Aktivität Alle") instead of above it */
  inlineLabel?: boolean;
  options: ReadonlyArray<SelectOption<K>>;
  value: K | null;
  onChange: (value: K) => void;
  placeholder?: string;
  size?: 'md' | 'sm';
  isDisabled?: boolean;
  className?: string;
  'data-testid'?: string;
}

/** A single-choice list in a popover. Explicit colours, so Windows dark mode leaves it alone. */
export function Select<K extends Key>({
  label,
  inlineLabel = false,
  options,
  value,
  onChange,
  placeholder = 'Bitte wählen…',
  size = 'md',
  isDisabled,
  className,
  ...rest
}: SelectProps<K>) {
  const surface = useSurface();
  return (
    <AriaSelect
      selectedKey={value}
      onSelectionChange={(key) => {
        const option = options.find((o) => o.id === key);
        if (option) onChange(option.id);
      }}
      placeholder={placeholder}
      {...(isDisabled === undefined ? {} : { isDisabled })}
      {...(inlineLabel ? { 'aria-label': label } : {})}
      data-testid={rest['data-testid']}
      className={cx('group grid content-start gap-1.5', className)}
    >
      {inlineLabel ? null : <Label className="text-sm font-semibold">{label}</Label>}
      <AriaButton
        className={cx(
          'flex min-w-0 cursor-pointer items-center gap-2 rounded-control border border-field bg-field-bg pr-2.5 pl-3 text-left text-ink',
          'outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
          'hover:bg-surface-hover disabled:cursor-not-allowed disabled:opacity-50',
          size === 'md' ? 'h-12 text-md' : 'h-10 text-sm',
        )}
      >
        {inlineLabel ? (
          <span aria-hidden="true" className="shrink-0 text-ink-muted">
            {label}
          </span>
        ) : null}
        <SelectValue className="min-w-0 flex-1 truncate placeholder-shown:text-ink-muted" />
        <ChevronDown
          aria-hidden="true"
          className="size-4 shrink-0 transition-transform duration-(--duration-quick) group-open:rotate-180"
          strokeWidth={2.25}
        />
      </AriaButton>
      <Popover
        offset={6}
        data-surface={surface}
        className="max-h-80 min-w-(--trigger-width) overflow-auto rounded-control border border-line bg-surface-raised p-1 text-ink shadow-float outline-none entering:animate-fade-in exiting:animate-fade-out"
      >
        <ListBox className="outline-none">
          {options.map((option) => (
            <ListBoxItem
              key={String(option.id)}
              id={option.id}
              textValue={option.label}
              className="flex min-h-11 cursor-pointer items-center gap-2 rounded-small px-3 text-sm outline-none hover:bg-surface-hover focus-visible:bg-surface-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus selected:font-semibold"
            >
              {({ isSelected }) => (
                <>
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  {isSelected ? (
                    <Check aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.5} />
                  ) : null}
                </>
              )}
            </ListBoxItem>
          ))}
        </ListBox>
      </Popover>
    </AriaSelect>
  );
}
