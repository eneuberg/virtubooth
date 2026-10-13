import type { LucideIcon } from 'lucide-react';
import { Button as AriaButton, Link } from 'react-aria-components';
import { cx } from './cx';
import { toastAvoid } from './toastPlacement';

export type BottomBarItem = {
  id: string;
  label: string;
  icon: LucideIcon;
} & ({ href: string; onPress?: never } | { onPress: () => void; href?: never });

export interface BottomBarProps {
  label: string;
  items: ReadonlyArray<BottomBarItem>;
  currentId: string | null;
  className?: string;
}

function itemClass(current: boolean): string {
  return cx(
    'relative flex flex-col items-center justify-center gap-0.5 text-xs font-semibold no-underline outline-none',
    'focus-visible:outline-2 focus-visible:-outline-offset-4 focus-visible:outline-focus',
    current ? 'text-accent-ink' : 'text-ink-muted hover:text-ink',
    current &&
      'before:absolute before:inset-x-[30%] before:top-0 before:h-[3px] before:rounded-b-full before:bg-accent landscape-phone:before:inset-x-auto landscape-phone:before:inset-y-3 landscape-phone:before:left-0 landscape-phone:before:h-auto landscape-phone:before:w-[3px] landscape-phone:before:rounded-r-full landscape-phone:before:rounded-b-none',
  );
}

/**
 * Phone admin navigation: a bar at the bottom (64px + safe area); on landscape phones a
 * rail on the left, so the grid keeps its height. Pad the page with `bottomBarInset`.
 */
export function BottomBar({ label, items, currentId, className }: BottomBarProps) {
  return (
    <nav
      aria-label={label}
      {...toastAvoid}
      className={cx(
        'fixed inset-x-0 bottom-0 z-(--z-bar) border-t border-line bg-surface-sunk pb-[env(safe-area-inset-bottom)]',
        'landscape-phone:inset-x-auto landscape-phone:top-0 landscape-phone:left-0 landscape-phone:border-t-0 landscape-phone:border-r landscape-phone:pb-0 landscape-phone:pl-[env(safe-area-inset-left)]',
        className,
      )}
    >
      <ul
        className="grid h-16 landscape-phone:h-auto landscape-phone:w-19 landscape-phone:auto-rows-[4.5rem]"
        style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}
      >
        {items.map((item) => {
          const current = item.id === currentId;
          const Icon = item.icon;
          const content = (
            <>
              <Icon aria-hidden="true" className="size-6" strokeWidth={2} />
              {item.label}
            </>
          );
          return (
            <li key={item.id} className="grid landscape-phone:col-span-full">
              {item.href === undefined ? (
                <AriaButton onPress={item.onPress} className={cx(itemClass(current), 'cursor-pointer')}>
                  {content}
                </AriaButton>
              ) : (
                <Link
                  href={item.href}
                  aria-current={current ? 'page' : undefined}
                  className={itemClass(current)}
                >
                  {content}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Padding for the page content so the bar (or the landscape rail) never covers it. */
export const bottomBarInset =
  'pb-[calc(4rem+env(safe-area-inset-bottom))] landscape-phone:pb-0 landscape-phone:pl-[calc(4.75rem+env(safe-area-inset-left))]';
