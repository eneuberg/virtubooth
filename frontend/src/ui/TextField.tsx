import type { LucideIcon } from 'lucide-react';
import type { ReactNode, Ref } from 'react';
import {
  FieldError,
  Input,
  Label,
  Text,
  TextField as AriaTextField,
  type TextFieldProps as AriaTextFieldProps,
} from 'react-aria-components';
import { cx } from './cx';

export interface TextFieldProps extends Omit<
  AriaTextFieldProps,
  'className' | 'children' | 'style' | 'isInvalid'
> {
  label: ReactNode;
  /** helper text under the field */
  description?: ReactNode;
  /** inline error; set it and focus the field (inputRef) after a failed submit */
  errorMessage?: string | null;
  /** fixed text before the input, e.g. "@" for Instagram names (not part of the value) */
  prefix?: string;
  /** decorative leading icon, e.g. Search */
  icon?: LucideIcon;
  /** a control at the start of the field box, e.g. a colour swatch (labels itself) */
  start?: ReactNode;
  /** keep the label for screen readers only (search fields) */
  hideLabel?: boolean;
  /** ends with "…" and shows an example pattern */
  placeholder?: string;
  size?: 'md' | 'sm';
  inputRef?: Ref<HTMLInputElement>;
  className?: string;
}

/**
 * Label, field, helper and inline error. Inputs stay ≥16px on touch screens so iOS does
 * not zoom. Spellcheck/autocapitalize default off for prefixed (handle) fields.
 */
export function TextField({
  label,
  description,
  errorMessage,
  prefix,
  icon: Icon,
  start,
  hideLabel = false,
  placeholder,
  size = 'md',
  inputRef,
  className,
  ...props
}: TextFieldProps) {
  const handle = Boolean(prefix);
  return (
    <AriaTextField
      {...props}
      isInvalid={Boolean(errorMessage)}
      className={cx('group grid content-start gap-1.5', className)}
    >
      <Label className={cx('text-sm font-semibold', hideLabel && 'sr-only')}>{label}</Label>
      <div
        className={cx(
          'flex items-center gap-1.5 rounded-control border border-field bg-field-bg px-3',
          'focus-within:border-focus focus-within:shadow-[0_0_0_1px_var(--color-focus)]',
          'group-invalid:border-danger group-invalid:focus-within:shadow-[0_0_0_1px_var(--color-danger)]',
          'group-disabled:opacity-50',
          size === 'md' ? 'h-12' : 'h-10',
        )}
      >
        {start}
        {Icon ? (
          <Icon aria-hidden="true" className="size-4 shrink-0 text-ink-muted" strokeWidth={2.25} />
        ) : null}
        {prefix ? (
          <span aria-hidden="true" className="text-md text-ink-muted">
            {prefix}
          </span>
        ) : null}
        <Input
          ref={inputRef}
          {...(placeholder ? { placeholder } : {})}
          spellCheck={handle ? false : undefined}
          autoCapitalize={handle ? 'none' : undefined}
          autoCorrect={handle ? 'off' : undefined}
          className={cx(
            'h-full min-w-0 flex-1 bg-transparent text-md text-ink outline-none placeholder:text-ink-muted',
            size === 'sm' && 'fine:text-sm',
          )}
        />
      </div>
      {description ? (
        <Text slot="description" className="text-xs text-ink-muted">
          {description}
        </Text>
      ) : null}
      <FieldError className="text-sm font-semibold text-danger">{errorMessage}</FieldError>
    </AriaTextField>
  );
}
