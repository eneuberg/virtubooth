import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { cx } from './cx';

/** An empty list is an invitation: say what will appear here and offer the next step. */
export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cx('grid max-w-md content-start justify-items-start gap-2 py-8', className)}>
      {Icon ? <Icon aria-hidden="true" className="mb-1 size-8 text-ink-muted" strokeWidth={1.75} /> : null}
      <p className="text-lg font-bold">{title}</p>
      {children ? <div className="text-sm text-ink-muted">{children}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
