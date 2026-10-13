import { cx } from './cx';

const SHAPE = {
  /** a 3:4 frame plus its two caption lines */
  photo: 'aspect-[3/4] w-full',
  line: 'h-4 w-full rounded-small',
  /** a Doto counter */
  counter: 'h-7 w-24 rounded-small',
  block: 'h-24 w-full rounded-control',
} as const;

/** Placeholder with the final size, so nothing jumps when data arrives. */
export function Skeleton({ shape = 'line', className }: { shape?: keyof typeof SHAPE; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx('block bg-surface-sunk motion-ok:animate-shimmer', SHAPE[shape], className)}
    />
  );
}

/** A grid of photo placeholders; the caller sets the columns with className. */
export function SkeletonGrid({ count = 8, className }: { count?: number; className?: string }) {
  return (
    <div aria-hidden="true" className={cx('grid grid-cols-2 gap-x-2 gap-y-4', className)}>
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className="grid gap-1.5">
          <Skeleton shape="photo" />
          <Skeleton shape="line" className="h-3 w-2/3" />
          <Skeleton shape="line" className="h-3 w-1/2" />
        </span>
      ))}
    </div>
  );
}
