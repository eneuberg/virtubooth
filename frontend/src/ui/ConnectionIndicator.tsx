import { cx } from './cx';
import { dataAttributes, type DataAttributes } from './dataAttributes';

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

export interface ConnectionIndicatorProps extends DataAttributes {
  status: ConnectionStatus;
  className?: string;
}

/** Admin realtime state: a dot plus words (never colour alone). `data-*` props land on the root. */
export function ConnectionIndicator({ status, className, ...rest }: ConnectionIndicatorProps) {
  return (
    <output
      data-status={status}
      className={cx('inline-flex items-center gap-1.5 text-xs text-ink-muted', className)}
      {...dataAttributes(rest)}
    >
      <span aria-hidden="true" className={cx('size-2 shrink-0 rounded-full', DOT[status])} />
      {LABEL[status]}
    </output>
  );
}
