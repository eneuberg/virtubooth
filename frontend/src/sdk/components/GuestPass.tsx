/**
 * The guest pass: one 44px pill with the short pseudonym and @handle (or "Instagram
 * hinzufügen"), top left on every guest screen. It doubles as the status slot for
 * exceptional states (paused, stopped, offline, n waiting, banned); tap opens the
 * "Du" sheet. OWNER: wave 2 "GP". Keep data-testid="guest-pass" (was user-chip).
 * Names and handles get translate="no".
 */
import { monogram } from '@/lib/format';
import { useSession } from '../session';

export interface GuestPassProps {
  /** camera top bar: name only, no second line */
  compact?: boolean;
  className?: string;
}

export function GuestPass({ compact = false, className }: GuestPassProps) {
  const session = useSession();
  // TODO(wave 2, GP): button, status states, Du sheet
  const name = session.status === 'ready' || session.status === 'banned' ? session.user.name : '…';
  return (
    <span
      data-testid="guest-pass"
      className={`inline-flex h-11 min-w-0 items-center gap-2.5 rounded-control bg-surface-raised pr-3 pl-1.5 ${className ?? ''}`}
    >
      <span className="grid size-8 shrink-0 place-items-center rounded-small bg-surface-sunk text-xs font-bold text-accent-ink">
        {monogram(name)}
      </span>
      <span translate="no" className="truncate text-sm font-semibold">
        {compact ? name.replace(/\s*#\d+$/, '') : name}
      </span>
    </span>
  );
}
