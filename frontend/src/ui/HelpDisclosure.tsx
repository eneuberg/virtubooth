import { ChevronDown, CircleHelp } from 'lucide-react';
import type { ReactNode } from 'react';
import { Button as AriaButton, Disclosure, DisclosurePanel, Heading } from 'react-aria-components';
import { cx } from './cx';

export interface HelpDisclosureProps {
  /** the question or section name: "Was passiert dabei?", "Technische Details" */
  summary: ReactNode;
  children: ReactNode;
  /** inline: a "?" link-like toggle next to a control · section: a collapsible page section */
  variant?: 'inline' | 'section';
  defaultExpanded?: boolean;
  /**
   * The heading that wraps the trigger. `false`: no heading, for a toggle inside
   * running text that is not a section of the page ("Mehr dazu" in the join sheet).
   */
  headingLevel?: 2 | 3 | 4 | false;
  className?: string;
}

/** Where long explanations live, collapsed, instead of inside the controls. */
export function HelpDisclosure({
  summary,
  children,
  variant = 'inline',
  defaultExpanded = false,
  headingLevel = 3,
  className,
}: HelpDisclosureProps) {
  const section = variant === 'section';
  const Icon = section ? ChevronDown : CircleHelp;
  const trigger = (
    <AriaButton
      slot="trigger"
      className={cx(
        'flex min-h-11 cursor-pointer items-center gap-2 rounded-small text-left outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
        section ? 'w-full text-md font-semibold' : 'text-sm text-ink-muted hover:text-ink',
      )}
    >
      <Icon
        aria-hidden="true"
        className={cx(
          'size-5 shrink-0 transition-transform duration-(--duration-quick)',
          section && '-rotate-90 group-expanded:rotate-0',
        )}
        strokeWidth={2}
      />
      {summary}
    </AriaButton>
  );
  return (
    <Disclosure
      defaultExpanded={defaultExpanded}
      className={cx('group', section && 'border-t border-line pt-2', className)}
    >
      {headingLevel === false ? (
        trigger
      ) : (
        <Heading level={headingLevel} className="m-0">
          {trigger}
        </Heading>
      )}
      <DisclosurePanel className={cx('text-sm', section ? 'pb-2' : 'pb-1 pl-7 text-ink-muted')}>
        <div className="grid gap-2 pt-1">{children}</div>
      </DisclosurePanel>
    </Disclosure>
  );
}
