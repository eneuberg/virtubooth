import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { cx } from './cx';

export interface NoticeProps {
  icon?: LucideIcon;
  /** names the problem: "Keine Verbindung zum Server", never "Ups" */
  title: ReactNode;
  /** one or two sentences: what happened and what to do */
  children?: ReactNode;
  /** a muted line under the text */
  hint?: ReactNode;
  /** primary first, then secondary; use size="lg" block buttons */
  actions?: ReactNode;
  /** alert for failures (default), status for neutral states */
  role?: 'alert' | 'status';
  headingLevel?: 1 | 2;
  /** in the page flow instead of covering the viewport */
  inline?: boolean;
  'data-testid'?: string;
  className?: string;
}

/**
 * A full-screen state: gate, 404, camera denied, in-app browser, banned, load failed,
 * offline, fatal. Same classes as public/boot-check.js, so every one of them looks alike.
 * CSS class `vb-screen` on purpose: blockers hide "notice", "banner", "modal", "popup".
 */
export function Notice({
  icon: Icon,
  title,
  children,
  hint,
  actions,
  role = 'alert',
  headingLevel = 1,
  inline = false,
  className,
  ...rest
}: NoticeProps) {
  const Heading = headingLevel === 1 ? 'h1' : 'h2';
  return (
    <div
      role={role}
      data-testid={rest['data-testid']}
      className={cx('vb-screen', inline && 'vb-screen--static', className)}
    >
      <div className="vb-screen-inner">
        {Icon ? <Icon aria-hidden="true" className="vb-screen-icon" strokeWidth={1.75} /> : null}
        <Heading className="vb-screen-title">{title}</Heading>
        {children ? <div className="vb-screen-text grid gap-2">{children}</div> : null}
        {hint ? <p className="vb-screen-hint">{hint}</p> : null}
        {actions ? <div className="vb-screen-actions">{actions}</div> : null}
      </div>
    </div>
  );
}
