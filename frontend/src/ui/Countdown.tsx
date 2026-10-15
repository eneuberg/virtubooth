import { useEffect, useState } from 'react';
import { Button } from './Button';
import { cx } from './cx';

export interface CountdownProps {
  /** the digit shown: 3, 2, 1 */
  value: number;
  /** 1 → 0 across the whole countdown; drives the Safelight ring */
  progress: number;
  /** tapping cancels; shows an "Abbrechen" button */
  onCancel?: () => void;
  cancelLabel?: string;
  /** read once when the countdown starts */
  announcement?: string;
  className?: string;
}

/**
 * Doto 160 numeral inside a draining Safelight ring, centred on the camera stage.
 * Screen readers hear one announcement at the start, not every digit.
 */
export function Countdown({
  value,
  progress,
  onCancel,
  cancelLabel = 'Abbrechen',
  announcement,
  className,
}: CountdownProps) {
  // fill the live region a moment after mount: text present at insertion is not reliably read
  const [first] = useState(() => announcement ?? `Countdown läuft, ${value} Sekunden`);
  const [said, setSaid] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setSaid(first), 60);
    return () => clearTimeout(timer);
  }, [first]);
  const remaining = Math.min(1, Math.max(0, progress));
  return (
    <div className={cx('vb-countdown grid place-items-center gap-4', className)}>
      <div className="relative grid size-55 place-items-center" aria-hidden="true">
        <svg viewBox="0 0 220 220" className="absolute inset-0 size-full -rotate-90">
          <circle
            cx="110"
            cy="110"
            r="104"
            fill="rgb(0 0 0 / 0.55)"
            stroke="rgb(255 255 255 / 0.2)"
            strokeWidth="6"
          />
          <circle
            cx="110"
            cy="110"
            r="104"
            fill="none"
            stroke="var(--color-safelight)"
            strokeWidth="6"
            strokeLinecap="round"
            pathLength={1}
            strokeDasharray="1"
            strokeDashoffset={1 - remaining}
            className="transition-[stroke-dashoffset] duration-(--duration-base) ease-linear"
          />
        </svg>
        <span key={value} className="relative dots text-dots-xl text-papier dots-round motion-ok:animate-pop">
          {value}
        </span>
      </div>
      <span className="sr-only" aria-live="assertive">
        {said}
      </span>
      {onCancel ? (
        <Button variant="camera" size="sm" onPress={onCancel}>
          {cancelLabel}
        </Button>
      ) : null}
    </div>
  );
}
