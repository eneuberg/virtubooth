/**
 * „Token“: generate one, or take an own one (a printed code's link, pasted). Shared by
 * the „Neuer QR-Code“ and „Token ändern“ sheets; the sheet owns the state and reads the
 * pasted text with `readTokenInput` (codeUrl.ts).
 */
import { TriangleAlert } from 'lucide-react';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { TextField } from '@/ui/TextField';
import type { PastedToken } from './codeUrl';

export type TokenMode = 'generate' | 'own';

const MODES = [
  { id: 'generate', label: 'Neu erzeugen' },
  { id: 'own', label: 'Eigenes' },
] as const;

export function TokenChoice({
  mode,
  onModeChange,
  input,
  onInputChange,
  pasted,
  showError,
  serverError,
  targetNote,
}: {
  mode: TokenMode;
  onModeChange: (mode: TokenMode) => void;
  input: string;
  onInputChange: (value: string) => void;
  /** what the input says (null while generating) */
  pasted: PastedToken | null;
  /** show the input's problem (after a first try, or once it looks complete) */
  showError: boolean;
  /** the server's answer for this token (taken, refused) */
  serverError: string | null;
  /** „Ziel auf „Fotobox“ gesetzt, wie im Link.“ */
  targetNote: string | null;
}) {
  const error = serverError ?? (showError ? (pasted?.error ?? null) : null);
  return (
    <div className="grid gap-3">
      <div className="grid gap-1.5">
        <span aria-hidden="true" className="text-sm font-semibold">
          Token
        </span>
        <SegmentedControl
          label="Token"
          options={MODES}
          value={mode}
          onChange={onModeChange}
          size="sm"
          data-testid="token-mode"
          className="w-full sm:w-auto"
        />
      </div>
      {mode === 'own' ? (
        <TextField
          label="Token oder Link"
          description="Für einen schon gedruckten Code: Code mit dem Handy scannen und den Link hier einfügen. Sonst mindestens 16 Zeichen aus A–Z, a–z, 0–9, _ und -."
          value={input}
          onChange={onInputChange}
          errorMessage={error}
          autoComplete="off"
          autoCorrect="off"
          spellCheck="false"
          maxLength={2000}
          data-testid="token-input"
        />
      ) : null}
      {mode === 'own' && pasted?.warning ? (
        <output className="flex gap-2 text-sm text-bernstein" data-testid="token-host-warning">
          <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2.25} />
          {pasted.warning}
        </output>
      ) : null}
      {mode === 'own' && targetNote ? (
        <output className="block text-sm text-ink-muted" data-testid="token-target-note">
          {targetNote}
        </output>
      ) : null}
    </div>
  );
}
