/**
 * The guest pass: one 44px pill with a monogram, the name others see (display name,
 * else @handle, else the short pseudonym) and the @handle (or "Instagram hinzufügen"),
 * top left on every guest screen. A dot
 * on the monogram marks paused / stopped (amber) and banned (red); the words are in
 * the label. Tap opens the "Du" sheet. Test id `guest-pass` (was user-chip).
 * Names and handles get translate="no".
 */
import { useState } from 'react';
import { Button as AriaButton } from 'react-aria-components';
import { t } from '@/lib/messages.de';
import { cx } from '@/ui/cx';
import { initials, passName } from '../identity';
import { useSession } from '../session';
import { useGuestStatus } from '../status';
import { GuestSheet } from './GuestSheet';
import { StatusDot } from './StatusSlot';

export interface GuestPassProps {
  /** camera top bar: the short name only, no second line */
  compact?: boolean;
  className?: string;
}

export function GuestPass({ compact = false, className }: GuestPassProps) {
  const session = useSession();
  const status = useGuestStatus();
  const [open, setOpen] = useState(false);
  const user = session.status === 'ready' || session.status === 'banned' ? session.user : null;

  if (!user) {
    // same footprint while the session loads: nothing jumps
    return (
      <span
        aria-hidden="true"
        className={cx(
          'inline-block h-11 w-40 rounded-full bg-surface-raised motion-ok:animate-shimmer',
          className,
        )}
      />
    );
  }

  const flagged = status.kind === 'paused' || status.kind === 'stopped' || status.kind === 'banned';
  const handle = user.instagram ? `@${user.instagram}` : null;
  const name = passName(user);
  // second line: the handle (unless it is the name already), else the invitation
  const second = handle && handle !== name ? handle : handle ? 'Name wählen' : t.addInstagram;
  return (
    <>
      <AriaButton
        data-testid="guest-pass"
        data-status={status.kind}
        onPress={() => setOpen(true)}
        className={cx(
          'group inline-flex h-12 max-w-full min-w-0 cursor-pointer items-center gap-2.5 rounded-full bg-surface-raised pr-4 pl-1.5 text-left outline-none',
          'transition-[background-color,transform] duration-(--duration-quick) hover:bg-surface-hover pressed:scale-[0.98]',
          'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
          className,
        )}
      >
        <span
          aria-hidden="true"
          className="relative grid size-9 shrink-0 place-items-center rounded-full bg-accent-tint text-xs font-bold text-accent-ink"
        >
          {initials(name)}
          {flagged ? (
            <StatusDot
              tone={status.tone}
              className="absolute -top-1 -right-1 ring-2 ring-surface-raised group-hover:ring-surface-hover"
            />
          ) : null}
        </span>
        <span className="grid min-w-0 leading-tight">
          <span translate="no" className="truncate text-sm font-semibold" title={user.shown_name}>
            {name}
          </span>
          {compact ? null : (
            <span
              translate={second === handle ? 'no' : undefined}
              className={cx('truncate text-xs', second === handle ? 'text-ink-muted' : 'text-accent-ink')}
            >
              {second}
            </span>
          )}
        </span>
        {flagged ? <span className="sr-only">, {status.label}</span> : null}
      </AriaButton>
      <GuestSheet isOpen={open} onOpenChange={setOpen} />
    </>
  );
}
