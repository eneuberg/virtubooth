import type { LucideIcon } from 'lucide-react';
import { useId, type ReactNode } from 'react';

/** One block of the Einstellungen section: a rule on top, an icon heading, its controls. */
export function SettingsCard({
  title,
  icon: Icon,
  children,
  testid,
}: {
  title: string;
  icon: LucideIcon;
  children: ReactNode;
  testid: string;
}) {
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      data-testid={testid}
      className="grid min-w-0 content-start gap-3 border-t-2 border-ink pt-3"
    >
      <h2 id={id} className="flex items-center gap-2 text-lg font-bold">
        <Icon aria-hidden="true" className="size-5" strokeWidth={2} />
        {title}
      </h2>
      {children}
    </section>
  );
}
