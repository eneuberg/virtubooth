import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-aria-components';
import { cx } from './cx';

export interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  href: string;
  /** tabular count at the end of the row */
  count?: number;
}

export interface SidebarNavProps {
  /** accessible name of the <nav> */
  label: string;
  items: ReadonlyArray<NavItem>;
  currentId: string | null;
  /** top of the sidebar: party name, connection */
  header?: ReactNode;
  /** bottom of the sidebar: status pill, "Live öffnen", "Abmelden" */
  footer?: ReactNode;
  className?: string;
}

/**
 * Desktop navigation for the manage area. Real links (Cmd/Ctrl-click works); the app's
 * RouterProvider turns plain clicks into client navigation.
 */
export function SidebarNav({ label, items, currentId, header, footer, className }: SidebarNavProps) {
  return (
    <aside
      className={cx(
        'flex h-full w-62 shrink-0 flex-col gap-5 border-r border-line bg-surface-raised px-3 pt-5 pb-4',
        className,
      )}
    >
      {header ? <div className="px-2">{header}</div> : null}
      <nav aria-label={label}>
        <ul className="grid gap-0.5">
          {items.map(({ id, label: itemLabel, icon: Icon, href, count }) => {
            const current = id === currentId;
            return (
              <li key={id}>
                <Link
                  href={href}
                  aria-current={current ? 'page' : undefined}
                  className={cx(
                    'relative flex h-10 items-center gap-2.5 rounded-small px-2.5 text-sm text-ink no-underline outline-none',
                    'hover:bg-surface-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus',
                    current &&
                      'bg-surface-sunk font-semibold before:absolute before:inset-y-2 before:-left-3 before:w-[3px] before:rounded-r-full before:bg-ink',
                  )}
                >
                  <Icon aria-hidden="true" className="size-5 shrink-0" strokeWidth={2} />
                  <span className="min-w-0 flex-1 truncate">{itemLabel}</span>
                  {count === undefined ? null : (
                    <span className="text-xs font-normal text-ink-muted tabular">{count}</span>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      {footer ? <div className="mt-auto grid gap-1">{footer}</div> : null}
    </aside>
  );
}
