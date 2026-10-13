/**
 * TEMPORARY stand-in for GP's `@/sdk/components/GuestPass` (see ./session.ts: delete
 * when GP merges). The same compact pill as GP's first cut, fed by the bridge session.
 */
import { monogram } from '@/lib/format';
import { cx } from '@/ui/cx';
import { useSession } from './session';

export interface GuestPassProps {
  compact?: boolean;
  className?: string;
}

export function GuestPass({ compact = false, className }: GuestPassProps) {
  const session = useSession();
  const name = session.status === 'ready' || session.status === 'banned' ? session.user.name : '';
  const shown = compact ? name.replace(/\s*#\d+$/, '') : name;
  return (
    <span
      data-testid="guest-pass"
      className={cx(
        'inline-flex h-11 max-w-full min-w-0 items-center gap-2.5 rounded-control bg-surface-raised pr-3 pl-1.5',
        !name && 'invisible',
        className,
      )}
    >
      <span className="grid size-8 shrink-0 place-items-center rounded-small bg-surface-sunk text-xs font-bold text-accent-ink">
        {monogram(name)}
      </span>
      <span translate="no" className="truncate text-sm font-semibold">
        {shown}
      </span>
    </span>
  );
}
