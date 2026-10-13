import { ProgressBar as AriaProgressBar } from 'react-aria-components';
import { cx } from './cx';

/** Indeterminate busy indicator; announced through its label. */
export function Spinner({ label = 'Lädt…', className }: { label?: string; className?: string }) {
  return (
    <AriaProgressBar isIndeterminate aria-label={label} className={cx('inline-grid size-5', className)}>
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className="size-full animate-spin">
        <circle cx="12" cy="12" r="9.5" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
        <path d="M21.5 12A9.5 9.5 0 0 0 12 2.5" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
    </AriaProgressBar>
  );
}

/** Determinate progress (0…1) with a visible label and value. */
export function Progress({
  label,
  value,
  valueLabel,
  className,
}: {
  label: string;
  /** 0…1 */
  value: number;
  /** defaults to "40 %" */
  valueLabel?: string;
  className?: string;
}) {
  const percent = Math.round(Math.min(1, Math.max(0, value)) * 100);
  return (
    <AriaProgressBar
      value={percent}
      aria-label={label}
      {...(valueLabel ? { valueLabel } : {})}
      className={cx('grid gap-1.5', className)}
    >
      {({ valueText }) => (
        <>
          <span className="flex items-baseline justify-between gap-3 text-sm">
            <span>{label}</span>
            <span className="text-ink-muted tabular">{valueText}</span>
          </span>
          <span className="h-1.5 overflow-hidden rounded-full bg-surface-sunk">
            <span
              className="block h-full origin-left bg-accent transition-transform duration-(--duration-base)"
              style={{ transform: `scaleX(${percent / 100})` }}
            />
          </span>
        </>
      )}
    </AriaProgressBar>
  );
}
