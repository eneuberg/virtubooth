import { cx } from './cx';

const STROKE = {
  fill: 'none',
  stroke: 'currentColor',
  strokeLinecap: 'round',
  // no vector-effect: non-scaling-stroke. With pathLength=1 the dash pattern is
  // measured in user space but drawn in screen space, which cut the strokes short on
  // frames wider than ~130 px (the X looked like a V). The stroke scales with the frame.
  pathLength: 1,
} as const;

/**
 * The grease-pencil X a host draws over a hidden frame on a contact sheet.
 * Stretches to its box; colour = currentColor (use text-mark).
 * `animate` draws the two strokes (180 ms each); reduced motion shows them at once.
 */
export function GreaseX({ className, animate = false }: { className?: string; animate?: boolean }) {
  const draw = animate ? 'motion-ok:animate-pencil [stroke-dasharray:1]' : '';
  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      aria-hidden="true"
      className={cx('overflow-visible', className)}
    >
      <path {...STROKE} strokeWidth={2.4} className={draw} d="M8 10 C 35 38, 62 66, 92 91" />
      <path
        {...STROKE}
        strokeWidth={2.4}
        className={cx(draw, animate && '[animation-delay:var(--duration-quick)]')}
        d="M90 8 C 64 36, 38 64, 9 93"
      />
    </svg>
  );
}

/** The grease-pencil circle that marks a selected frame. */
export function GreaseCircle({ className, animate = false }: { className?: string; animate?: boolean }) {
  return (
    <svg
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      aria-hidden="true"
      className={cx('overflow-visible', className)}
    >
      <path
        {...STROKE}
        strokeWidth={2.4}
        className={animate ? '[stroke-dasharray:1] motion-ok:animate-pencil' : ''}
        d="M52 4 C 20 3, 6 22, 7 50 C 8 80, 28 97, 54 96 C 82 95, 95 74, 94 47 C 93 22, 76 6, 46 7"
      />
    </svg>
  );
}
