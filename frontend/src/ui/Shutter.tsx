import { Lock } from 'lucide-react';
import { Button as AriaButton, type ButtonProps as AriaButtonProps } from 'react-aria-components';
import { cx } from './cx';
import { GooglyEyes } from './goofy/GooglyEyes';

export type ShutterState = 'idle' | 'not-ready' | 'ready' | 'counting' | 'capturing' | 'blocked';

export interface ShutterProps extends Omit<
  AriaButtonProps,
  'className' | 'children' | 'style' | 'isDisabled'
> {
  /**
   * idle/ready: armed · not-ready: camera starting (disabled) · counting: the ring drains
   * with `countdownProgress` · capturing: the disc flashes · blocked: uploads paused or
   * stopped: a lock; still pressable so the page can explain why
   */
  state?: ShutterState;
  /** 1 → 0 while counting */
  countdownProgress?: number;
  label?: string;
  blockedLabel?: string;
  /** desktop keyboard hint under the button, e.g. "Leertaste" (hidden on touch screens) */
  keyHint?: string;
  className?: string;
}

/** The 80px shutter: Safelight ring, paper disc. Space/Enter work through the button. */
export function Shutter({
  state = 'ready',
  countdownProgress = 1,
  label = 'Foto aufnehmen',
  blockedLabel = 'Hochladen geht gerade nicht. Warum?',
  keyHint,
  className,
  ...props
}: ShutterProps) {
  const blocked = state === 'blocked';
  const counting = state === 'counting';
  const ring = state === 'not-ready' || blocked ? 'text-white/30' : 'text-accent';
  const remaining = counting ? Math.min(1, Math.max(0, countdownProgress)) : 1;
  return (
    <span className={cx('inline-grid justify-items-center gap-1.5', className)}>
      <AriaButton
        {...props}
        isDisabled={state === 'not-ready'}
        aria-label={blocked ? blockedLabel : label}
        data-state={state}
        className="vb-shutter group relative grid size-20 cursor-pointer place-items-center rounded-full outline-none focus-visible:outline-3 focus-visible:outline-offset-3 focus-visible:outline-focus disabled:cursor-not-allowed"
      >
        <svg
          viewBox="0 0 80 80"
          aria-hidden="true"
          className={cx('absolute inset-0 size-full -rotate-90', ring)}
        >
          {counting ? (
            <circle cx="40" cy="40" r="38" fill="none" stroke="rgb(255 255 255 / 0.25)" strokeWidth="4" />
          ) : null}
          <circle
            cx="40"
            cy="40"
            r="38"
            fill="none"
            stroke="currentColor"
            strokeWidth="4"
            pathLength={1}
            strokeDasharray="1"
            strokeDashoffset={1 - remaining}
            strokeLinecap={counting ? 'round' : 'butt'}
            className="transition-[stroke-dashoffset] duration-(--duration-base) ease-linear"
          />
          {/* the party style's second set of ring lights (styles/party.css); invisible otherwise */}
          <circle
            className="vb-shutter-lights"
            cx="40"
            cy="40"
            r="38"
            fill="none"
            stroke="none"
            pathLength={1}
          />
        </svg>
        <span
          className={cx(
            'grid size-[62px] place-items-center rounded-full bg-papier text-rot-900 transition-transform duration-(--duration-press)',
            'group-pressed:scale-90',
            (state === 'not-ready' || blocked) && 'bg-papier/30',
            counting && 'scale-90 bg-papier/60',
            state === 'capturing' && 'animate-pop bg-white',
          )}
        >
          {blocked ? (
            <Lock aria-hidden="true" className="size-6 text-white" strokeWidth={2.25} />
          ) : (
            // party and goofy styles: the camera looks at you, asleep while it starts, cross-eyed
            // during the countdown, and it blinks when it takes the photo
            <GooglyEyes
              mood={
                state === 'counting'
                  ? 'nervous'
                  : state === 'capturing' || state === 'not-ready'
                    ? 'shut'
                    : 'look'
              }
            />
          )}
        </span>
      </AriaButton>
      {keyHint ? (
        <kbd className="hidden rounded-small border border-white/30 px-1.5 font-sans text-xs text-papier-muted fine:inline">
          {keyHint}
        </kbd>
      ) : null}
    </span>
  );
}
