import { useQueryClient } from '@tanstack/react-query';
import { ChevronRight, OctagonPause } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-aria-components';
import { isApiError } from '@/api/client';
import type { AdminUser } from '@/api/types';
import { msg } from '@/lib/messages.de';
import { Button } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Sheet } from '@/ui/Sheet';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { setNewGuestPause, setUploadStop, setUserPaused } from '../store/actions';
import { usePausedUsers, useUploadPause, useUploadStop } from '../store/hooks';
import { qk } from '../store/keys';
import { guestCount } from '../lib/labels';
import { useUploadSheet } from './sheetStore';
import { endPausePlan, endPauseResult, pauseDescription, pauseSource, stopDescription } from './uploadState';

type Busy = null | 'stop' | 'pause' | 'restore' | 'keep' | number;
interface Result {
  text: string;
  tone: 'ok' | 'error';
}

function errorText(err: unknown): string {
  return isApiError(err) ? err.message : msg.generic;
}

/**
 * Every upload lever in one place (BRIEF: per-guest pause, new-guest pause, stop all),
 * reachable from the status pill in each header and from the phone bottom bar. The
 * switch state is the feedback: results show inside the sheet, no toast on top of it.
 */
export function UploadControlsSheet() {
  const qc = useQueryClient();
  const isOpen = useUploadSheet((s) => s.isOpen);
  const setOpen = useUploadSheet((s) => s.setOpen);
  const { data: stop } = useUploadStop();
  const { data: pause } = useUploadPause();
  const paused = usePausedUsers(isOpen);
  const [view, setView] = useState<'main' | 'end'>('main');
  const [busy, setBusy] = useState<Busy>(null);
  const [result, setResult] = useState<Result | null>(null);
  const endHeading = useRef<HTMLHeadingElement>(null);
  const mainHeading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    // another admin may have changed something while the stream was asleep
    void qc.invalidateQueries({ queryKey: qk.uploadStop });
    void qc.invalidateQueries({ queryKey: qk.uploadPause });
  }, [isOpen, qc]);

  const run = async (what: Busy, task: () => Promise<string | null>) => {
    setBusy(what);
    setResult(null);
    try {
      const text = await task();
      if (text) setResult({ text, tone: 'ok' });
    } catch (err) {
      setResult({ text: errorText(err), tone: 'error' });
    } finally {
      setBusy(null);
    }
  };

  const showView = (next: 'main' | 'end') => {
    setView(next);
    requestAnimationFrame(() => (next === 'end' ? endHeading : mainHeading).current?.focus());
  };

  const onStop = (enabled: boolean) =>
    run('stop', async () => {
      await setUploadStop(qc, enabled);
      return enabled ? 'Hochladen für alle gestoppt.' : 'Hochladen läuft wieder.';
    });

  const onPause = (enabled: boolean) => {
    if (!pause) return;
    if (enabled) {
      void run('pause', async () => {
        await setNewGuestPause(qc, true);
        return 'Neue Gäste sind ab jetzt pausiert.';
      });
      return;
    }
    if (endPausePlan(pause).ask) {
      setResult(null);
      showView('end');
      return;
    }
    void run('pause', async () => {
      await setNewGuestPause(qc, false, true);
      return 'Pause für neue Gäste beendet.';
    });
  };

  const endPause = (restore: boolean) =>
    run(restore ? 'restore' : 'keep', async () => {
      const res = await setNewGuestPause(qc, false, restore);
      showView('main');
      return endPauseResult(res);
    });

  const resume = (user: AdminUser) =>
    run(user.id, async () => {
      await setUserPaused(qc, user.id, false);
      return `${user.name} darf wieder hochladen.`;
    });

  const onOpenChange = (open: boolean) => {
    if (!open && view === 'end') {
      showView('main'); // Esc in the decision goes back one step, like "Zurück"
      return;
    }
    setOpen(open);
    if (!open) {
      setView('main');
      setResult(null);
    }
  };

  const plan = pause ? endPausePlan(pause) : null;
  const pausedUsers = paused.data?.users ?? [];
  const pausedTotal = pause?.paused_total ?? pausedUsers.length;

  return (
    <Sheet
      isOpen={isOpen}
      onOpenChange={onOpenChange}
      title="Hochladen"
      size="md"
      data-testid="uploads-sheet"
    >
      {!stop || !pause ? (
        <div className="grid place-items-center py-10">
          <Spinner />
        </div>
      ) : view === 'end' && plan ? (
        <section className="grid gap-4" aria-labelledby="vb-end-pause-title">
          <h3
            id="vb-end-pause-title"
            ref={endHeading}
            tabIndex={-1}
            className="text-md font-bold outline-none"
          >
            Pause für neue Gäste beenden
          </h3>
          <p data-testid="pause-end-text" className="text-md">
            {plan.text}
          </p>
          <div className="grid gap-2">
            <Button
              variant="primary"
              block
              isPending={busy === 'restore'}
              isDisabled={busy !== null && busy !== 'restore'}
              onPress={() => void endPause(true)}
              data-testid="pause-end-restore"
            >
              {plan.restoreLabel}
            </Button>
            <Button
              variant="secondary"
              block
              isPending={busy === 'keep'}
              isDisabled={busy !== null && busy !== 'keep'}
              onPress={() => void endPause(false)}
              data-testid="pause-end-keep"
            >
              {plan.keepLabel}
            </Button>
            <Button
              variant="quiet"
              block
              isDisabled={busy !== null}
              onPress={() => showView('main')}
              data-testid="pause-end-back"
            >
              Zurück
            </Button>
          </div>
          <p className="text-sm text-ink-muted">
            Freischalten gilt nur für die Gäste aus dieser Pause. Von Hand pausierte bleiben pausiert, und
            neue Gäste können in jedem Fall wieder hochladen.
          </p>
          <ResultLine result={result} />
        </section>
      ) : (
        <div className="grid gap-3">
          <h3 ref={mainHeading} tabIndex={-1} className="sr-only">
            Hochladen steuern
          </h3>
          <Switch
            variant="emergency"
            icon={OctagonPause}
            isSelected={stop.enabled}
            isPending={busy === 'stop'}
            isDisabled={busy !== null && busy !== 'stop'}
            onChange={(on) => void onStop(on)}
            description={stopDescription(stop)}
            data-testid="upload-stop-switch"
          >
            Hochladen für alle stoppen
          </Switch>
          <Switch
            variant="row"
            isSelected={pause.enabled}
            isPending={busy === 'pause'}
            isDisabled={busy !== null && busy !== 'pause'}
            onChange={onPause}
            description={pauseDescription(pause)}
            data-testid="upload-pause-switch"
          >
            Neue Gäste pausieren
          </Switch>
          <ResultLine result={result} />
          <HelpDisclosure summary="Was passiert dabei?">
            <p>
              <strong className="text-ink">Hochladen für alle stoppen:</strong> Niemand kann hochladen, auch
              bekannte Gäste nicht. Für kurze Pausen, etwa bei einer Flut unpassender Fotos. Einzelne Pausen
              bleiben dabei, wie sie sind.
            </p>
            <p>
              <strong className="text-ink">Neue Gäste pausieren:</strong> Wer ab jetzt beitritt, kann erst
              hochladen, wenn ihr freigebt. Bekannte Gäste laden weiter hoch. Beim Ausschalten entscheidest
              du, ob die Betroffenen freigeschaltet werden.
            </p>
            <p>
              Einzelne Gäste pausierst du auf ihrer Seite. Pausieren ist keine Sperre: Ihre Fotos bleiben
              sichtbar.
            </p>
          </HelpDisclosure>
          <section aria-labelledby="vb-paused-title" className="grid gap-1 border-t border-line pt-3">
            <h3 id="vb-paused-title" className="flex items-baseline gap-2 text-md font-bold">
              Pausierte Gäste
              <span className="text-sm font-normal text-ink-muted tabular">{pausedTotal}</span>
            </h3>
            {paused.isPending ? (
              <Spinner className="my-2" />
            ) : pausedUsers.length === 0 ? (
              <p className="text-sm text-ink-muted">Niemand ist pausiert.</p>
            ) : (
              <ul className="grid" data-testid="paused-guests">
                {pausedUsers.map((user) => (
                  <li
                    key={user.id}
                    className="flex min-h-13 items-center gap-3 border-b border-line last:border-0"
                  >
                    <div className="grid min-w-0 flex-1">
                      <Link
                        href={`/user?id=${user.id}`}
                        onPress={() => setOpen(false)}
                        translate="no"
                        className="truncate font-semibold text-ink underline-offset-3 outline-none hover:underline focus-visible:outline-2 focus-visible:outline-focus"
                      >
                        {user.name}
                      </Link>
                      <span className="truncate text-xs text-ink-muted">{pauseSource(user, pause)}</span>
                    </div>
                    <Button
                      size="xs"
                      variant="secondary"
                      isPending={busy === user.id}
                      isDisabled={busy !== null && busy !== user.id}
                      onPress={() => void resume(user)}
                      aria-label={`Hochladen für ${user.name} erlauben`}
                      data-testid="resume-guest"
                    >
                      Freigeben
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {pausedTotal > 0 ? (
              <Link
                href="/manage?tab=gaeste&show=paused"
                onPress={() => setOpen(false)}
                data-testid="uploads-paused-list"
                className="flex min-h-11 items-center justify-between gap-2 text-sm font-semibold text-ink no-underline outline-none hover:underline focus-visible:outline-2 focus-visible:outline-focus"
              >
                {pausedTotal > pausedUsers.length
                  ? `Alle ${guestCount(pausedTotal)} in der Gästeliste`
                  : 'In der Gästeliste ansehen'}
                <ChevronRight aria-hidden="true" className="size-4" strokeWidth={2.25} />
              </Link>
            ) : null}
          </section>
        </div>
      )}
    </Sheet>
  );
}

function ResultLine({ result }: { result: Result | null }) {
  return (
    <output
      data-testid="uploads-result"
      className={cx(
        'block text-sm font-semibold empty:hidden',
        result?.tone === 'error' ? 'text-danger' : 'text-ok',
      )}
    >
      {result?.text ?? ''}
    </output>
  );
}
