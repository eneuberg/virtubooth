/**
 * The Instagram-name field of the join sheet and the "Du" sheet: TextField with a
 * fixed "@" (not part of the value; a typed or pasted "@" is dropped), and a pasted
 * profile link (instagram.com/<name>/?igsh=…) keeps just the name. The server
 * normalises and validates the rest (invalid_instagram names the problem).
 */
import type { ClipboardEvent, ReactNode, Ref } from 'react';
import { TextField } from '@/ui/TextField';
import { cleanHandle, HANDLE_MAX, handleFromLink } from '../identity';

export interface HandleFieldProps {
  label: ReactNode;
  description?: ReactNode;
  value: string;
  onChange: (value: string) => void;
  errorMessage?: string | null;
  inputRef?: Ref<HTMLInputElement>;
  isDisabled?: boolean;
  className?: string;
}

export function HandleField({ value, onChange, ...props }: HandleFieldProps) {
  const onPaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const handle = handleFromLink(event.clipboardData.getData('text'));
    if (handle === null) return;
    event.preventDefault();
    onChange(handle.slice(0, HANDLE_MAX));
  };
  return (
    <TextField
      {...props}
      prefix="@"
      name="instagram"
      autoComplete="off"
      inputMode="text"
      placeholder="deinname…"
      maxLength={HANDLE_MAX}
      value={value}
      onChange={(next) => onChange(cleanHandle(next))}
      onPaste={onPaste}
    />
  );
}
