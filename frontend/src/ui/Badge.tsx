import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { tv, type VariantProps } from './cx';

const styles = tv({
  base: 'inline-flex h-6 shrink-0 items-center gap-1 rounded-small px-2 text-xs font-semibold whitespace-nowrap',
  variants: {
    tone: {
      neutral: 'bg-surface-sunk text-ink',
      /** grease pencil: Ausgeblendet, Gesperrt, Automatisch gesperrt */
      mark: 'text-mark ring-1 ring-current ring-inset',
      /** Safelight: Hochladen pausiert */
      amber: 'bg-accent text-on-accent',
      ok: 'text-ok ring-1 ring-current ring-inset',
      /** fresh things: Neu */
      new: 'bg-ink text-surface',
    },
  },
  defaultVariants: { tone: 'neutral' },
});

export interface BadgeProps extends VariantProps<typeof styles> {
  /** sentence case: "Automatisch gesperrt" */
  children: ReactNode;
  /** state is never colour alone: pass an icon where the text is short */
  icon?: LucideIcon;
  className?: string;
}

/** Marks an exceptional state. The default state needs no badge. */
export function Badge({ children, icon: Icon, tone, className }: BadgeProps) {
  return (
    <span className={styles({ tone, class: className })}>
      {Icon ? <Icon aria-hidden="true" className="size-3.5" strokeWidth={2.5} /> : null}
      {children}
    </span>
  );
}
