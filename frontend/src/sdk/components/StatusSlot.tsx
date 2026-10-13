/**
 * The one place for exceptional guest states (UX audit §5): "Gesperrt",
 * "Hochladen pausiert", "Hochladen ist kurz angehalten", "Offline", "1 Foto wartet".
 * Never a floating chip: Start puts it under the party name, activities put it where
 * their layout has room (AC). Tap explains in a sheet. Renders nothing when all is
 * well. Test id `status-slot` with `data-kind`.
 */
import { useState } from 'react';
import { Button as AriaButton } from 'react-aria-components';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { Sheet } from '@/ui/Sheet';
import { useGuestStatus, type GuestStatus } from '../status';

const DOT: Record<GuestStatus['tone'], string> = {
  ok: 'bg-ok',
  warn: 'bg-accent',
  danger: 'bg-danger',
  muted: 'bg-ink-muted',
};

/** A small coloured dot (state is never colour alone: always next to words). */
export function StatusDot({ tone, className }: { tone: GuestStatus['tone']; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx('inline-block size-2.5 shrink-0 rounded-full', DOT[tone], className)}
    />
  );
}

/** Explains a status; "Alles klar" closes it. */
export function StatusSheet({
  status,
  isOpen,
  onOpenChange,
}: {
  status: GuestStatus;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title={status.title}
      size="sm"
      data-testid="status-info"
      footer={
        <Button variant="primary" size="lg" block onPress={() => onOpenChange(false)}>
          Alles klar
        </Button>
      }
    >
      <p className="text-md">{status.text}</p>
    </Sheet>
  );
}

export interface StatusSlotProps {
  className?: string;
}

export function StatusSlot({ className }: StatusSlotProps) {
  const status = useGuestStatus();
  const [open, setOpen] = useState(false);
  const Icon = status.icon;
  return (
    <div aria-live="polite" className={cx('empty:hidden', className)}>
      {status.kind === 'ok' ? null : (
        <>
          <AriaButton
            data-testid="status-slot"
            data-kind={status.kind}
            onPress={() => setOpen(true)}
            className={cx(
              'inline-flex min-h-11 max-w-full cursor-pointer items-center gap-2.5 rounded-control border px-3 py-2 text-left text-sm font-semibold outline-none',
              'transition-[background-color] duration-(--duration-quick) hover:bg-surface-hover',
              'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
              status.tone === 'danger' ? 'border-danger text-danger' : 'border-line-strong text-ink',
              status.tone === 'warn' && 'border-accent bg-accent-tint',
            )}
          >
            <Icon aria-hidden="true" className="size-5 shrink-0" strokeWidth={2.25} />
            <span className="min-w-0">{status.label}</span>
            <span className="sr-only">. Mehr dazu</span>
          </AriaButton>
          <StatusSheet status={status} isOpen={open} onOpenChange={setOpen} />
        </>
      )}
    </div>
  );
}
