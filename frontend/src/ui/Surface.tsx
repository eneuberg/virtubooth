import { createContext, use, type ReactNode } from 'react';
import { cx } from './cx';

export type SurfaceTone = 'dark' | 'light';

const SurfaceContext = createContext<SurfaceTone | undefined>(undefined);

/**
 * The surface an area sits on: "dark" (Rotlicht: guest pages) or "light" (Leuchttisch:
 * the admin). Pages normally set it once on <html data-surface>;
 * use this for nested areas (the UI gallery shows both side by side).
 * Overlays (Sheet, Select, Tooltip) read it so their portals match the area.
 */
export function Surface({
  tone,
  className,
  children,
}: {
  tone: SurfaceTone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <SurfaceContext value={tone}>
      <div data-surface={tone} className={cx('bg-surface text-ink', className)}>
        {children}
      </div>
    </SurfaceContext>
  );
}

/** The tone set by the nearest <Surface>, or undefined (then <html data-surface> applies). */
export function useSurface(): SurfaceTone | undefined {
  return use(SurfaceContext);
}
