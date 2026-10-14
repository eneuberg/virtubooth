import type { ReactNode } from 'react';
import { cx } from '@/ui/cx';

/**
 * A box with the photo's own aspect ratio, as large as fits in the element around it
 * (which needs a size: absolute inset, or a fixed aspect). The photo fills it exactly,
 * so anything inside placed in % of the box (the grease X, the analysis frames) lands on
 * the photo, whatever its shape.
 */
export function FittedPhoto({
  width,
  height,
  children,
  className,
}: {
  width: number;
  height: number;
  children: ReactNode;
  className?: string;
}) {
  const ratio = width > 0 && height > 0 ? width / height : 3 / 4;
  return (
    <div className={cx('[container-type:size] absolute inset-0 grid place-items-center', className)}>
      <div
        className="relative max-h-full max-w-full"
        style={{ width: `min(100cqw, ${(100 * ratio).toFixed(4)}cqh)`, aspectRatio: `${ratio}` }}
        data-testid="fitted-photo"
      >
        {children}
      </div>
    </div>
  );
}
