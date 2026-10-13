import { cx } from './cx';

export type ConnectionStatus = 'live' | 'connecting' | 'reconnecting' | 'polling' | 'offline';

const LABEL: Record<ConnectionStatus, string> = {
  live: 'verbunden',
  connecting: 'verbindet…',
  reconnecting: 'verbindet…',
  polling: 'nur Abfrage',
  offline: 'getrennt',
};

const DOT: Record<ConnectionStatus, string> = {
  live: 'bg-ok',
  connecting: 'bg-accent motion-ok:animate-shimmer',
  reconnecting: 'bg-accent motion-ok:animate-shimmer',
  polling: 'bg-accent',
  offline: 'bg-danger',
};

/** Admin realtime state: a dot plus words (never colour alone). */
export function ConnectionIndicator({ status, className }: { status: ConnectionStatus; className?: string }) {
  return (
    <output
      data-status={status}
      className={cx('inline-flex items-center gap-1.5 text-xs text-ink-muted', className)}
    >
      <span aria-hidden="true" className={cx('size-2 shrink-0 rounded-full', DOT[status])} />
      {LABEL[status]}
    </output>
  );
}
