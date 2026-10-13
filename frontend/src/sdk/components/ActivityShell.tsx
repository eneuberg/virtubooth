/**
 * The page frame for camera activities (Beer Cam, Fotobox): black stage, top bar,
 * edge-to-edge 3:4 stage, film edge, one hint line, control row, and the single toast
 * slot just above the controls. Layouts (UX audit §5 wireframes, docs/overhaul/design):
 *   portrait: bar / stage / film edge / hint + controls (centred in the rest)
 *   short (≤ 700px tall): bar and film edge overlay the stage
 *   landscape phone: stage left, everything else in a column on the right
 *   desktop: one centred column, stage height-limited
 * OWNER: wave 2 "GP" (this is a working first cut; AC builds pages on these slots).
 */
import { ChevronLeft } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-aria-components';
import { cx } from '@/ui/cx';
import { iconButtonStyles } from '@/ui/IconButton';
import { ToastSlot } from '@/ui/Toast';
import { GuestPass } from './GuestPass';

export interface ActivityShellProps {
  /** the title area, normally <ActivityMenu currentId title /> */
  title: ReactNode;
  /** top right; defaults to the compact guest pass */
  topRight?: ReactNode;
  /** the 3:4 camera preview or the result print (fills the stage box) */
  stage: ReactNode;
  /** <FilmEdge> under the stage */
  filmEdge?: ReactNode;
  /** one short line between stage and controls */
  hint?: ReactNode;
  /** the control row: [left] [shutter] [right] */
  controls: ReactNode;
  backHref?: string;
  backLabel?: string;
  className?: string;
}

/* portrait: 56px bar + ~46px film edge + ~150px hint/controls stay visible */
const STAGE_W = 'w-[min(100%,calc((100dvh-15.75rem)*0.75))] short:w-[min(100%,calc((100dvh-9.5rem)*0.75))]';

export function ActivityShell({
  title,
  topRight,
  stage,
  filmEdge,
  hint,
  controls,
  backHref = '/',
  backLabel = 'Zurück zum Start',
  className,
}: ActivityShellProps) {
  return (
    <div
      data-surface="dark"
      className={cx(
        'vb-activity relative grid h-dvh grid-cols-[minmax(0,1fr)] grid-rows-[auto_auto_auto_1fr] overflow-hidden bg-kamera text-papier',
        'short:grid-rows-[auto_1fr]',
        'landscape-phone:grid-cols-[auto_minmax(0,1fr)] landscape-phone:grid-rows-[auto_auto_1fr]',
        className,
      )}
    >
      <header
        className={cx(
          'z-(--z-sticky) box-content flex h-14 items-center gap-1 px-2 pt-[env(safe-area-inset-top)]',
          'short:absolute short:inset-x-0 short:top-0 short:bg-linear-to-b short:from-black/60 short:to-transparent',
          'landscape-phone:col-start-2',
        )}
      >
        <Link href={backHref} aria-label={backLabel} className={iconButtonStyles({ variant: 'plain' })}>
          <ChevronLeft aria-hidden="true" className="size-7" strokeWidth={2} />
        </Link>
        <div className="min-w-0 flex-1">{title}</div>
        <div className="min-w-0 shrink">{topRight ?? <GuestPass compact />}</div>
      </header>

      <div
        className={cx(
          'relative mx-auto aspect-[3/4] overflow-hidden bg-black',
          STAGE_W,
          'landscape-phone:col-start-1 landscape-phone:row-span-full landscape-phone:h-dvh landscape-phone:w-auto',
        )}
      >
        {stage}
        {filmEdge ? (
          <div className="absolute inset-x-0 bottom-0 z-(--z-raised) hidden opacity-90 short:block">
            {filmEdge}
          </div>
        ) : null}
      </div>

      {filmEdge ? (
        <div
          className={cx(
            'mx-auto w-full short:hidden',
            STAGE_W,
            'landscape-phone:col-start-2 landscape-phone:w-full',
          )}
        >
          {filmEdge}
        </div>
      ) : null}

      <div
        className={cx(
          'mx-auto grid w-full max-w-[30rem] content-center gap-4 px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))]',
          'landscape-phone:col-start-2 landscape-phone:content-end',
        )}
      >
        {hint ? <p className="text-center text-md landscape-phone:text-left">{hint}</p> : null}
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 [&>:first-child]:justify-self-start [&>:last-child]:justify-self-end">
          {controls}
        </div>
      </div>

      <ToastSlot className="bottom-[calc(7.5rem+env(safe-area-inset-bottom))] landscape-phone:right-4 landscape-phone:left-auto landscape-phone:mx-0" />
    </div>
  );
}
