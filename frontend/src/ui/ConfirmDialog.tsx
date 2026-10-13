import { useState, type ReactNode } from 'react';
import { Button } from './Button';
import { Sheet } from './Sheet';

export interface ConfirmDialogProps {
  isOpen: boolean;
  onOpenChange: (isOpen: boolean) => void;
  /** a question: "3 Fotos endgültig löschen?" */
  title: ReactNode;
  children?: ReactNode;
  /** repeats the verb: "Endgültig löschen" */
  confirmLabel: string;
  cancelLabel?: string;
  tone?: 'danger' | 'neutral';
  /** may return a promise: the button shows a spinner and the dialog closes when it resolves */
  onConfirm: () => void | Promise<void>;
  /** shown above the buttons, e.g. the API error after a failed attempt */
  error?: string | null;
  'data-testid'?: string;
}

/**
 * The second step before anything destructive. Focus starts on "Abbrechen", so an
 * accidental Enter never deletes. Esc and the scrim cancel.
 */
export function ConfirmDialog({
  isOpen,
  onOpenChange,
  title,
  children,
  confirmLabel,
  cancelLabel = 'Abbrechen',
  tone = 'danger',
  onConfirm,
  error,
  ...rest
}: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);
  const confirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
      onOpenChange(false);
    } catch {
      // the caller shows what went wrong through `error`; the dialog stays open
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={(open) => !busy && onOpenChange(open)}
      title={title}
      role="alertdialog"
      size="sm"
      data-testid={rest['data-testid']}
      footer={
        <div className="grid gap-3">
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <Button
              size="md"
              variant="secondary"
              autoFocus
              isDisabled={busy}
              onPress={() => onOpenChange(false)}
            >
              {cancelLabel}
            </Button>
            <Button
              size="md"
              variant={tone === 'danger' ? 'danger' : 'primary'}
              isPending={busy}
              onPress={() => void confirm()}
            >
              {confirmLabel}
            </Button>
          </div>
        </div>
      }
    >
      {children ? <div className="grid gap-2 text-md">{children}</div> : null}
    </Sheet>
  );
}
