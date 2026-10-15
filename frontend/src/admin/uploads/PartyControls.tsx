/**
 * The three party switches, in one place and always in sight: „Hochladen für alle
 * stoppen“, „Anmeldung stoppen“ and „Neue Gäste pausieren“. The same component sits in
 * the manage sidebar (desktop), at the top of the manage area on phones and in the Live
 * header; nothing else switches these (no button pair, no pill, no sheet).
 *
 * Real switches (role="switch", aria-checked): one tap flips one lever, no confirmation
 * (it must be instant at a party). Only ending the new-guest pause asks, when guests
 * joined during it: release them, or keep them paused. A stop that is on fills its row
 * (uploads red, joining amber, the pause amber-tinted), so the state reads at a glance.
 */
import { useQueryClient } from '@tanstack/react-query';
import { ChevronRight, DoorClosed, OctagonPause, UserRoundPlus, type LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { Link, Switch as AriaSwitch } from 'react-aria-components';
import { isApiError } from '@/api/client';
import type { PauseState } from '@/api/types';
import { msg } from '@/lib/messages.de';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { cx, tv } from '@/ui/cx';
import { Sheet } from '@/ui/Sheet';
import { Spinner } from '@/ui/Spinner';
import { showToast } from '@/ui/Toast';
import { flipSwitch, useJoinStop, useSwitchBusy } from '../dashboard/data';
import { guestCount } from '../lib/labels';
import { setNewGuestPause } from '../store/actions';
import { useUploadPause, useUploadStop } from '../store/hooks';
import { endPausePlan, endPauseResult, partyControlsCopy, partySummary } from './uploadState';

const row = tv({
  slots: {
    root: [
      'group relative flex min-h-12 min-w-0 cursor-pointer items-center gap-2.5 rounded-control border px-3 py-2',
      'border-line bg-surface-raised text-ink outline-none select-none hover:bg-surface-hover',
      'transition-[background-color,border-color,color] duration-(--duration-quick) ease-out',
      'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
      'disabled:cursor-not-allowed disabled:opacity-60 data-pending:cursor-wait data-pending:opacity-100',
    ],
    icon: 'size-5 shrink-0 text-ink-muted',
    text: 'grid min-w-0 flex-1',
    label: 'text-sm leading-tight font-semibold',
    state: 'text-xs text-ink-muted tabular',
    track: [
      'relative h-6 w-10 shrink-0 rounded-full bg-line-strong transition-colors duration-(--duration-quick)',
      'group-data-pending:animate-shimmer',
    ],
    thumb: [
      'shadow-sm absolute top-[3px] left-[3px] size-[18px] rounded-full bg-white',
      'transition-transform duration-(--duration-quick) ease-out group-selected:translate-x-4',
    ],
  },
  variants: {
    tone: {
      /** uploads stopped: the emergency red */
      danger: {
        root: 'selected:border-danger-fill selected:bg-danger-fill selected:text-on-danger selected:hover:bg-danger-fill-hover',
        icon: 'group-selected:text-on-danger',
        state: 'group-selected:text-on-danger',
        track: 'group-selected:bg-white/90',
        thumb: 'group-selected:bg-danger-fill',
      },
      /** joining stopped: Safelight amber */
      accent: {
        root: 'selected:border-accent selected:bg-accent selected:text-on-accent selected:hover:bg-accent-hover',
        icon: 'group-selected:text-on-accent',
        state: 'group-selected:text-on-accent',
        track: 'group-selected:bg-on-accent',
        thumb: 'group-selected:bg-accent',
      },
      /** new guests paused: amber, but quieter (known guests keep uploading) */
      tint: {
        root: 'selected:border-accent selected:bg-accent-tint',
        icon: 'group-selected:text-accent-ink',
        track: 'group-selected:bg-accent',
        thumb: 'group-selected:bg-on-accent',
      },
    },
    /** the sidebar: rows in one card, no icon, the state line only while on */
    compact: {
      true: {
        root: 'min-h-11 rounded-none border-0 px-2.5 py-2 focus-visible:-outline-offset-2',
        icon: 'hidden',
        state: 'hidden group-selected:block',
      },
    },
  },
});

interface RowProps {
  label: string;
  state: string;
  icon: LucideIcon;
  tone: 'danger' | 'accent' | 'tint';
  isSelected: boolean | undefined;
  isPending: boolean;
  isDisabled: boolean;
  onChange: (on: boolean) => void;
  testId: string;
  compact: boolean;
}

function SwitchRow({
  label,
  state,
  icon: Icon,
  tone,
  isSelected,
  isPending,
  isDisabled,
  onChange,
  testId,
  compact,
}: RowProps) {
  const s = row({ tone, compact });
  const known = isSelected !== undefined;
  return (
    <AriaSwitch
      isSelected={isSelected ?? false}
      // never disabled while a request runs: a disabled input drops the focus (keyboard
      // users lose their place); a press meanwhile is ignored (one request at a time)
      isDisabled={!known}
      onChange={(on) => {
        if (!isDisabled && !isPending) onChange(on);
      }}
      data-pending={isPending || undefined}
      aria-busy={isPending || undefined}
      data-testid={testId}
      data-state={known ? (isSelected ? 'on' : 'off') : 'loading'}
      className={s.root()}
    >
      {isPending ? (
        <Spinner label="Wird umgeschaltet…" className="size-5 shrink-0" />
      ) : (
        <Icon aria-hidden="true" className={s.icon()} strokeWidth={2} />
      )}
      <span className={s.text()}>
        <span className={s.label()}>{label}</span>
        <span className={s.state()}>{state}</span>
      </span>
      <span aria-hidden="true" className={s.track()}>
        <span className={s.thumb()} />
      </span>
    </AriaSwitch>
  );
}

export interface PartyControlsProps {
  /**
   * stack: one switch per row (phones) · row: side by side (Live on desktop) ·
   * sidebar: one compact card (the manage sidebar)
   */
  layout?: 'stack' | 'row' | 'sidebar';
  className?: string;
}

/** The three switches and, while guests are paused, the way to them. */
export function PartyControls({ layout = 'stack', className }: PartyControlsProps) {
  const qc = useQueryClient();
  const { data: stop } = useUploadStop();
  const { data: join } = useJoinStop();
  const { data: pause } = useUploadPause();
  const busy = useSwitchBusy((s) => s.busy);
  const [ending, setEnding] = useState(false);
  const copy = partyControlsCopy(stop, join, pause);
  const compact = layout === 'sidebar';

  const runPause = async (enabled: boolean, restore?: boolean): Promise<void> => {
    if (useSwitchBusy.getState().busy !== null) return;
    useSwitchBusy.setState({ busy: 'pause' });
    try {
      const res = await setNewGuestPause(qc, enabled, restore);
      if (!enabled && (res.restored > 0 || res.kept > 0)) {
        showToast({ tone: 'success', message: endPauseResult(res) });
      }
      setEnding(false);
    } catch (err) {
      showToast({ tone: 'error', message: isApiError(err) ? err.message : msg.generic });
    } finally {
      useSwitchBusy.setState({ busy: null });
    }
  };

  const onPause = (on: boolean) => {
    if (!pause) return;
    if (!on && endPausePlan(pause).ask) setEnding(true);
    else void runPause(on, on ? undefined : true);
  };

  const pausedTotal = pause?.paused_total ?? 0;

  return (
    <div data-testid="party-controls" className={cx('grid gap-1.5', className)}>
      <fieldset
        className={cx(
          'grid min-w-0 gap-1.5',
          layout === 'row' && 'sm:grid-cols-3',
          layout === 'sidebar' &&
            'gap-0 divide-y divide-line overflow-hidden rounded-control border border-line bg-surface-raised',
        )}
      >
        <legend className="sr-only">Hochladen und Anmeldung</legend>
        <SwitchRow
          label="Hochladen für alle stoppen"
          state={copy.uploads}
          icon={OctagonPause}
          tone="danger"
          isSelected={stop?.enabled}
          isPending={busy === 'uploads'}
          isDisabled={busy !== null}
          onChange={(on) => void flipSwitch(qc, 'uploads', on)}
          testId="upload-stop-switch"
          compact={compact}
        />
        <SwitchRow
          label="Anmeldung stoppen"
          state={copy.join}
          icon={DoorClosed}
          tone="accent"
          isSelected={join?.enabled}
          isPending={busy === 'join'}
          isDisabled={busy !== null}
          onChange={(on) => void flipSwitch(qc, 'join', on)}
          testId="join-stop-switch"
          compact={compact}
        />
        <SwitchRow
          label="Neue Gäste pausieren"
          state={copy.pause}
          icon={UserRoundPlus}
          tone="tint"
          isSelected={pause?.enabled}
          isPending={busy === 'pause'}
          isDisabled={busy !== null}
          onChange={onPause}
          testId="upload-pause-switch"
          compact={compact}
        />
      </fieldset>
      {pausedTotal > 0 ? (
        <Link
          href="/manage?tab=gaeste&show=paused"
          data-testid="uploads-paused-list"
          className="flex min-h-9 items-center gap-1 rounded-small px-1 text-sm font-semibold text-ink no-underline outline-none hover:underline focus-visible:outline-2 focus-visible:outline-focus"
        >
          {`${guestCount(pausedTotal)} pausiert`}
          <ChevronRight aria-hidden="true" className="size-4" strokeWidth={2.25} />
        </Link>
      ) : null}
      {/* switching here, in another tab or on another device (event stream) is announced */}
      <p aria-live="polite" className="sr-only" data-testid="party-summary">
        {partySummary(stop, join, pause)}
      </p>
      {pause ? (
        <EndPauseSheet
          isOpen={ending}
          pause={pause}
          busy={busy === 'pause'}
          onClose={() => setEnding(false)}
          onEnd={(restore) => void runPause(false, restore)}
        />
      ) : null}
    </div>
  );
}

/** Ending the new-guest pause while guests wait: release them, or keep them paused. */
function EndPauseSheet({
  isOpen,
  pause,
  busy,
  onClose,
  onEnd,
}: {
  isOpen: boolean;
  pause: PauseState;
  busy: boolean;
  onClose: () => void;
  onEnd: (restore: boolean) => void;
}) {
  const plan = endPausePlan(pause);
  const [choice, setChoice] = useState<boolean | null>(null);
  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
      title="Pause für neue Gäste beenden"
      size="sm"
      data-testid="pause-end"
    >
      <div className="grid gap-4">
        <p data-testid="pause-end-text" className="text-md">
          {plan.text}
        </p>
        <div className="grid gap-2">
          <Button
            variant="primary"
            block
            isPending={busy && choice === true}
            isDisabled={busy}
            onPress={() => {
              setChoice(true);
              onEnd(true);
            }}
            data-testid="pause-end-restore"
          >
            {plan.restoreLabel}
          </Button>
          <Button
            variant="secondary"
            block
            isPending={busy && choice === false}
            isDisabled={busy}
            onPress={() => {
              setChoice(false);
              onEnd(false);
            }}
            data-testid="pause-end-keep"
          >
            {plan.keepLabel}
          </Button>
          <Button variant="quiet" block isDisabled={busy} onPress={onClose} data-testid="pause-end-back">
            Pause weiterlaufen lassen
          </Button>
        </div>
        <p className="text-sm text-ink-muted">
          Freischalten gilt nur für die Gäste aus dieser Pause. Von Hand pausierte bleiben pausiert, und neue
          Gäste können in jedem Fall wieder hochladen.
        </p>
      </div>
    </Sheet>
  );
}

/** Small badges for the stops that are on (the sticky Live header on phones). */
export function PartyStateBadges({ className }: { className?: string }) {
  const { data: stop } = useUploadStop();
  const { data: join } = useJoinStop();
  const { data: pause } = useUploadPause();
  if (!stop?.enabled && !join?.enabled && !pause?.enabled) return null;
  return (
    <span className={cx('flex flex-wrap gap-1', className)} data-testid="party-badges">
      {stop?.enabled ? (
        <Badge tone="mark" icon={OctagonPause}>
          Hochladen gestoppt
        </Badge>
      ) : null}
      {join?.enabled ? (
        <Badge tone="amber" icon={DoorClosed}>
          Anmeldung gestoppt
        </Badge>
      ) : null}
      {pause?.enabled && !stop?.enabled ? <Badge tone="neutral">Neue pausiert</Badge> : null}
    </span>
  );
}
