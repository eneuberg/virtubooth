import { useId, type Key, type ReactNode } from 'react';
import { formatFrame } from '@/lib/format';
import { cx } from './cx';

export type FilmEdgeState = 'idle' | 'uploading' | 'done' | 'waiting' | 'error';

export interface FilmEdgeProps {
  /** small text before the frame number: "Nächstes Bier", "Foto" */
  label?: ReactNode;
  /** the frame number, printed in Doto (numbers are zero-padded to 4 digits) */
  frame?: number | string;
  /** right-hand side: goal, filter name, upload state */
  end?: ReactNode;
  /**
   * idle: plain film · uploading: holes fill with Safelight along `progress` ·
   * done: all holes lit · waiting: dimmed light (queued, not sent) · error: grease red
   */
  state?: FilmEdgeState;
  /** 0…1 while uploading */
  progress?: number;
  /** what the progress bar announces, e.g. "Wird hochgeladen…" */
  progressLabel?: string;
  /** where the sprocket holes run */
  holes?: 'top' | 'bottom' | 'both';
  /** md: camera and print (Doto 22) · lg: counters on the start screen (Doto 28) */
  size?: 'md' | 'lg';
  /** change it (e.g. to the new frame number) to play the one-frame advance */
  advanceKey?: Key;
  className?: string;
}

const PITCH = 14;

/** One sprocket hole. Pattern content takes its colour where the <pattern> is defined,
 * so every tone gets its own pattern. */
function Hole({ className }: { className: string }) {
  return <rect x="4" y="1.5" width="6" height="7" rx="1.5" className={className} />;
}

function Holes({
  id,
  fill,
  state,
  advanceKey,
}: {
  id: string;
  fill: number;
  state: FilmEdgeState;
  advanceKey?: Key;
}) {
  const lit =
    state === 'error' ? 'fill-fettstift-hell' : state === 'waiting' ? 'fill-safelight/45' : 'fill-accent';
  return (
    <div className="h-2.5 overflow-hidden" aria-hidden="true">
      <svg
        key={advanceKey}
        className={cx(
          '-ml-3.5 h-2.5 w-[calc(100%+14px)]',
          advanceKey !== undefined && 'motion-ok:animate-advance',
        )}
      >
        <defs>
          <pattern id={`${id}a`} width={PITCH} height="10" patternUnits="userSpaceOnUse">
            <Hole className="fill-film-hole" />
          </pattern>
          <pattern id={`${id}b`} width={PITCH} height="10" patternUnits="userSpaceOnUse">
            <Hole className={lit} />
          </pattern>
        </defs>
        <rect width="100%" height="10" fill={`url(#${id}a)`} />
        <rect
          width={`${fill * 100}%`}
          height="10"
          fill={`url(#${id}b)`}
          className="transition-[width] duration-(--duration-base) ease-out"
        />
      </svg>
    </div>
  );
}

/**
 * The signature element: a strip of film edge with sprocket holes and the frame number.
 * Under the camera preview it shows the next frame and doubles as the upload progress
 * track; under a print it carries the upload state; on the start screen the counter.
 * Always black film base, so it reads the same on both surfaces.
 */
export function FilmEdge({
  label,
  frame,
  end,
  state = 'idle',
  progress = 0,
  progressLabel = 'Wird hochgeladen…',
  holes = 'top',
  size = 'md',
  advanceKey,
  className,
}: FilmEdgeProps) {
  const id = useId().replace(/:/g, '');
  const clamped = Math.min(1, Math.max(0, progress));
  const fill = state === 'uploading' ? clamped : state === 'idle' ? 0 : 1;
  const frameText = typeof frame === 'number' ? formatFrame(frame) : frame;
  const progressProps =
    state === 'uploading'
      ? {
          role: 'progressbar' as const,
          'aria-label': progressLabel,
          'aria-valuemin': 0,
          'aria-valuemax': 100,
          'aria-valuenow': Math.round(clamped * 100),
        }
      : {};
  return (
    <div data-state={state} className={cx('vb-film bg-film text-papier', className)} {...progressProps}>
      {holes !== 'bottom' ? (
        <div className="pt-1">
          <Holes
            id={`${id}t`}
            fill={fill}
            state={state}
            {...(advanceKey === undefined ? {} : { advanceKey })}
          />
        </div>
      ) : null}
      {label !== undefined || frame !== undefined || end !== undefined ? (
        <div
          className={cx(
            'flex items-center justify-between gap-3 px-4',
            size === 'md' ? 'min-h-9 py-1' : 'min-h-11 py-1.5',
          )}
        >
          <span className="flex min-w-0 items-baseline gap-2">
            {label !== undefined ? <span className="truncate text-xs text-film-label">{label}</span> : null}
            {frameText !== undefined ? (
              <span
                className={cx(
                  'dots text-accent',
                  size === 'md' ? 'text-dots-sm' : 'text-dots-md',
                  state === 'error' && 'text-fettstift-hell',
                )}
              >
                {frameText}
              </span>
            ) : null}
          </span>
          {end !== undefined ? <span className="shrink-0 text-xs text-film-label">{end}</span> : null}
        </div>
      ) : null}
      {holes !== 'top' ? (
        <div className="pb-1">
          <Holes id={`${id}b`} fill={fill} state={state} />
        </div>
      ) : null}
    </div>
  );
}
