import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import {
  Tab as AriaTab,
  TabList as AriaTabList,
  TabPanel as AriaTabPanel,
  Tabs as AriaTabs,
  type Key,
  type TabsProps as AriaTabsProps,
} from 'react-aria-components';
import { cx } from './cx';

export interface TabsProps extends Omit<AriaTabsProps, 'className' | 'style'> {
  className?: string;
}

/** Tabs container. Keep the selected tab in the URL (`?tab=`) via selectedKey/onSelectionChange. */
export function Tabs({ className, ...props }: TabsProps) {
  return <AriaTabs {...props} className={cx('grid min-w-0 gap-4', className)} />;
}

export interface TabItem<K extends Key = string> {
  id: K;
  label: string;
  icon?: LucideIcon;
  /** shown after the label, tabular */
  count?: number;
}

/** A horizontally scrolling tab strip with a shadow where more tabs hide. Labels never clip mid-word. */
export function TabList<K extends Key>({
  label,
  items,
  className,
}: {
  label: string;
  items: ReadonlyArray<TabItem<K>>;
  className?: string;
}) {
  return (
    <AriaTabList
      aria-label={label}
      className={cx(
        'flex [scrollbar-width:none] gap-1 overflow-x-auto border-b border-line scroll-shadows-x',
        className,
      )}
    >
      {items.map(({ id, label: tabLabel, icon: Icon, count }) => (
        <AriaTab
          key={String(id)}
          id={id}
          className={cx(
            'relative flex h-12 shrink-0 cursor-pointer items-center gap-2 px-3 text-sm font-semibold whitespace-nowrap text-ink-muted outline-none',
            'hover:text-ink selected:text-ink',
            'after:absolute after:inset-x-2 after:bottom-0 after:h-[3px] after:rounded-t-full after:bg-transparent selected:after:bg-ink',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus',
          )}
        >
          {Icon ? <Icon aria-hidden="true" className="size-5" strokeWidth={2} /> : null}
          {tabLabel}
          {count === undefined ? null : <span className="font-normal text-ink-muted tabular">{count}</span>}
        </AriaTab>
      ))}
    </AriaTabList>
  );
}

export function TabPanel({ id, children, className }: { id: Key; children: ReactNode; className?: string }) {
  return (
    <AriaTabPanel id={id} className={cx('min-w-0 outline-none', className)}>
      {children}
    </AriaTabPanel>
  );
}
