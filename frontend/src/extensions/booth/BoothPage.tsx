/**
 * Fotobox: a selfie through a filter, with an optional 3-2-1. OWNER: wave 2 "AC".
 * Port of booth/static/booth.js.
 *
 * The preview is the WebGL shader output (Canvas2D without WebGL), mirrored for the
 * front camera like a mirror; the capture renders the frozen frame again at 1080×1440
 * through the same shader and overlay, so the photo is exactly what was on screen.
 * Filters: the carousel, swipes on the preview, the arrow keys; a double tap flips the
 * camera. The result is a print that develops, with "Speichern" and "Neues Foto"; its
 * upload state lives on the film edge. A failed upload waits in the outbox.
 */
import { Camera, Check, Download, Share2, SwitchCamera, Timer } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ToggleButton } from 'react-aria-components';
import { formatPercent, NBSP } from '@/lib/format';
import { msg, t } from '@/lib/messages.de';
import { CameraStatus, FilmRetry } from '@/sdk/camera/CameraHints';
import { CameraErrorScreen, FatalScreen } from '@/sdk/camera/CameraScreens';
import { CameraStage, PREVIEW_CANVAS_CLASS } from '@/sdk/camera/CameraStage';
import { PHOTO_H, PHOTO_W, STREAM_SIZE } from '@/sdk/camera/capture';
import { buildFilterList, NORMAL, type Filter } from '@/sdk/camera/filters';
import { useCameraKeys, useLeaveGuard } from '@/sdk/camera/keys';
import { drawOverlay, overlayInfo, type OverlayInfo } from '@/sdk/camera/overlays';
import { useCameraSession } from '@/sdk/camera/useCameraSession';
import { shotErrorText, useNow, useOutboxToasts, useShot } from '@/sdk/camera/useShot';
import { ActivityMenu } from '@/sdk/components/ActivityMenu';
import { ActivityShell } from '@/sdk/components/ActivityShell';
import { GuestPass } from '@/sdk/components/GuestPass';
import { StatusSheet } from '@/sdk/components/StatusSlot';
import type { ExtensionPageProps } from '@/sdk/extension';
import { flash, vibrate } from '@/sdk/feedback';
import { flushOutbox, subscribeOutboxEvents, useOutbox } from '@/sdk/outbox';
import { canUpload, useSession } from '@/sdk/session';
import { isIOS } from '@/sdk/platform';
import { canShareFiles, saveImage, shareImage } from '@/sdk/share';
import { useGuestStatus } from '@/sdk/status';
import { Button, buttonStyles } from '@/ui/Button';
import { Countdown } from '@/ui/Countdown';
import { cx } from '@/ui/cx';
import { FilmEdge, type FilmEdgeState } from '@/ui/FilmEdge';
import { IconButton } from '@/ui/IconButton';
import { Shutter, type ShutterState } from '@/ui/Shutter';
import { clearToasts, showToast } from '@/ui/Toast';
import { FilterStrip } from './FilterStrip';
import { useCatalogue } from './useCatalogue';
import { useSwatches } from './useSwatches';

const TITLE = 'Fotobox';
const COUNTDOWN_KEY = 'vb_booth_countdown';
const COUNTDOWN_SECONDS = 3;
const SWIPE_MIN_PX = 40;
const DOUBLE_TAP_MS = 320;

function readCountdown(): boolean {
  try {
    return localStorage.getItem(COUNTDOWN_KEY) === '1';
  } catch {
    return false;
  }
}

function prefer(): 'canvas2d' | null {
  return new URLSearchParams(location.search).get('renderer') === 'canvas2d' ? 'canvas2d' : null;
}

/** Rendered inside GP's session gate: the guest has joined (banned/error never get here). */
export default function BoothPage({ id }: ExtensionPageProps) {
  const catalogue = useCatalogue(true);
  if (catalogue.status === 'error') {
    return <FatalScreen error={catalogue.error} fallback="Die Fotobox konnte nicht starten." />;
  }
  return <Fotobox id={id} catalogue={catalogue.status === 'ready' ? catalogue : null} />;
}

function Fotobox({
  id,
  catalogue,
}: {
  id: string;
  catalogue: { filters: ReadonlyArray<{ id: string; name: string; icon: string }>; partyName: string } | null;
}) {
  const session = useSession();
  const gate = canUpload(session);
  const joined = session.status === 'ready';
  const blocked = joined && !gate.ok;
  const [renderer] = useState(prefer);
  const {
    videoRef,
    mountRef,
    session: camera,
    camera: cam,
  } = useCameraSession({
    enabled: joined,
    facing: 'user',
    ...STREAM_SIZE.booth,
    prefer: renderer,
    canvasClassName: PREVIEW_CANVAS_CLASS,
    canvasTestId: 'preview-canvas',
  });
  const live = cam.status === 'live' && cam.ready;
  const outbox = useOutbox();
  const { shot, take, retry, dismiss } = useShot(id);
  useOutboxToasts(shot?.id ?? null);
  const now = useNow(!!shot && shot.waitUntil > 0);
  const [busy, setBusy] = useState(false);
  const [countdownOn, setCountdownOn] = useState(readCountdown);
  const [count, setCount] = useState<{ value: number; progress: number } | null>(null);
  const cancelCount = useRef<(() => void) | null>(null);
  const [saved, setSaved] = useState(false);
  const [sendingOutbox, setSendingOutbox] = useState(false);
  const [lastNumber, setLastNumber] = useState<number | null>(null);

  // ------------------------------------------------------------ filters
  const kind = cam.renderer ?? (renderer === 'canvas2d' ? 'canvas2d' : 'webgl');
  const filters: Filter[] = useMemo(
    () => (catalogue ? buildFilterList(catalogue.filters, kind).filters : []),
    [catalogue, kind],
  );
  const [selectedId, setSelectedId] = useState<string>('');
  const filter = filters.find((f) => f.id === selectedId) ?? filters[0] ?? null;
  const info: OverlayInfo | null = useMemo(
    () => (catalogue ? overlayInfo(catalogue.partyName) : null),
    [catalogue],
  );
  const [overlayCanvas] = useState(() => {
    const canvas = document.createElement('canvas');
    canvas.width = PHOTO_W;
    canvas.height = PHOTO_H;
    return canvas;
  });
  const applied = useRef<string | null>(null);

  // show the selected filter on the session (and again after a camera restart)
  useEffect(() => {
    if (!camera || !filter || !info || cam.status !== 'live') return;
    const key = `${filter.id}|${cam.renderer ?? ''}`;
    if (applied.current === key) return;
    try {
      camera.setFilter(filter, drawOverlay(overlayCanvas, filter.id, info));
      applied.current = key;
    } catch {
      showToast({ message: 'Dieser Filter klappt auf deinem Handy leider nicht.', tone: 'error' });
      const previous = filters.find((f) => `${f.id}|${cam.renderer ?? ''}` === applied.current) ?? NORMAL;
      try {
        camera.setFilter(previous, drawOverlay(overlayCanvas, previous.id, info));
      } catch {
        // stays on whatever ran before
      }
      setSelectedId(previous.id);
    }
  }, [camera, filter, info, cam.status, cam.renderer, filters, overlayCanvas]);

  useEffect(() => {
    if (catalogue && info) document.title = `${TITLE} – ${info.partyName}`;
  }, [catalogue, info]);

  const swatches = useSwatches(camera, filters, info, live);

  const step = (delta: -1 | 1) => {
    if (!filters.length || shot) return;
    const index = Math.max(
      0,
      filters.findIndex((f) => f.id === filter?.id),
    );
    const next = filters[(index + delta + filters.length) % filters.length];
    if (next) setSelectedId(next.id);
  };

  // ------------------------------------------------------------ uploads allowed again
  // (the guest app says so): send what waited
  const wasBlocked = useRef(false);
  useEffect(() => {
    if (!joined) return;
    if (wasBlocked.current && !blocked) void flushOutbox({ force: true });
    wasBlocked.current = blocked;
  }, [blocked, joined]);

  useEffect(
    () =>
      subscribeOutboxEvents((e) => {
        if (e.type === 'sent' && e.item.ext === 'booth') {
          setLastNumber(e.result.booth_number ?? e.result.photo.seq);
        }
      }),
    [],
  );

  useLeaveGuard(outbox.atRisk > 0);

  // ------------------------------------------------------------ shooting
  // the locked shutter explains: the status sheet ("Hochladen pausiert" …)
  const status = useGuestStatus();
  const [whyOpen, setWhyOpen] = useState(false);
  const explainBlocked = () => {
    vibrate([20, 40, 20]);
    setWhyOpen(true);
  };

  const runCountdown = () =>
    new Promise<boolean>((resolve) => {
      const total = COUNTDOWN_SECONDS * 1000;
      const start = performance.now();
      let last = COUNTDOWN_SECONDS;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const finish = (ok: boolean) => {
        clearTimeout(timer);
        cancelCount.current = null;
        setCount(null);
        resolve(ok);
      };
      cancelCount.current = () => finish(false);
      setCount({ value: COUNTDOWN_SECONDS, progress: 1 });
      vibrate(12);
      const tick = () => {
        const left = total - (performance.now() - start);
        if (left <= 0) {
          finish(true);
          return;
        }
        const value = Math.ceil(left / 1000);
        if (value !== last) {
          last = value;
          vibrate(12);
        }
        setCount({ value, progress: left / total });
        timer = setTimeout(tick, 100);
      };
      timer = setTimeout(tick, 100);
    });

  useEffect(() => () => cancelCount.current?.(), []);

  const shoot = async () => {
    if (busy || shot || !camera || !live || !filter) return;
    if (!gate.ok) {
      explainBlocked();
      return;
    }
    setBusy(true);
    clearToasts();
    try {
      if (countdownOn && !(await runCountdown())) return;
      // freeze: the frame on screen now is the photo
      flash();
      vibrate(40);
      const blob = await camera.capture();
      setSaved(false);
      setBusy(false);
      const result = await take(blob, { filter: filter.id, facing: cam.facing });
      if (result) setLastNumber(result.booth_number ?? result.photo.seq);
    } catch {
      showToast({ message: 'Das Foto hat nicht geklappt. Versuch es nochmal.', tone: 'error' });
      await camera.resume().catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  const again = async () => {
    dismiss();
    clearToasts();
    setSaved(false);
    await camera?.resume().catch(() => undefined);
    document.querySelector<HTMLElement>('[data-testid="shutter"]')?.focus({ preventScroll: true });
  };

  const save = async () => {
    if (!shot) return;
    const n = shot.result?.booth_number ?? shot.result?.photo.seq;
    const stamp = new Date().toTimeString().slice(0, 8).replaceAll(':', '');
    try {
      const how = await saveImage(shot.blob, `fotobox-${n ?? stamp}.jpg`);
      if (how !== 'cancelled') setSaved(true);
    } catch {
      showToast({
        message: 'Speichern hat nicht geklappt. Halte das Foto gedrückt und sichere es so.',
        tone: 'error',
      });
    }
  };

  // iOS shares on "Speichern" already ("Bild sichern"); elsewhere "Teilen" is extra
  const [offerShare] = useState(() => !isIOS() && canShareFiles());
  const share = async () => {
    if (!shot) return;
    const n = shot.result?.booth_number ?? shot.result?.photo.seq;
    try {
      await shareImage(shot.blob, `fotobox-${n ?? 'foto'}.jpg`);
    } catch {
      showToast({
        message: 'Teilen hat nicht geklappt. Speichere das Foto und teile es dann.',
        tone: 'error',
      });
    }
  };

  const sendOutbox = async () => {
    setSendingOutbox(true);
    try {
      await flushOutbox({ force: true });
    } finally {
      setSendingOutbox(false);
    }
  };

  const toggleCountdown = (on: boolean) => {
    setCountdownOn(on);
    try {
      localStorage.setItem(COUNTDOWN_KEY, on ? '1' : '0');
    } catch {
      // private mode
    }
  };

  const switchCamera = () => {
    if (!camera || !cam.canSwitch || busy || shot || !live) return;
    camera.switchFacing().catch((err: unknown) => {
      showToast({
        message: err instanceof Error && err.message ? err.message : 'Kamera wechseln hat nicht geklappt.',
        tone: 'error',
      });
    });
  };

  const shutterRef = useRef<HTMLDivElement | null>(null);
  useCameraKeys({
    shutter: () => void shoot(),
    ...(shot ? { escape: () => void again() } : count ? { escape: () => cancelCount.current?.() } : {}),
    ...(shot || count ? {} : { arrow: step }),
    arrowTargets: () => [shutterRef.current?.querySelector('[data-testid="shutter"]') ?? null],
  });

  const shotShown = !!shot;
  useEffect(() => {
    if (shotShown)
      document.querySelector<HTMLElement>('[data-testid="save"]')?.focus({ preventScroll: true });
  }, [shotShown]);

  // ------------------------------------------------------------ gestures on the preview
  const gestureRef = useRef<HTMLDivElement | null>(null);
  const gesture = useRef({ step, switchCamera });
  useEffect(() => {
    gesture.current = { step, switchCamera };
  });
  useEffect(() => {
    const el = gestureRef.current;
    if (!el) return undefined;
    let start: { x: number; y: number; id: number } | null = null;
    let lastTap = 0;
    const down = (e: PointerEvent) => {
      if (e.isPrimary) start = { x: e.clientX, y: e.clientY, id: e.pointerId };
    };
    const up = (e: PointerEvent) => {
      if (!start || e.pointerId !== start.id) return;
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      start = null;
      if (Math.abs(dx) > SWIPE_MIN_PX && Math.abs(dx) > Math.abs(dy) * 1.3) {
        lastTap = 0;
        gesture.current.step(dx < 0 ? 1 : -1);
        vibrate(8);
      } else if (Math.abs(dx) < 12 && Math.abs(dy) < 12) {
        const time = performance.now();
        if (time - lastTap < DOUBLE_TAP_MS) {
          lastTap = 0;
          gesture.current.switchCamera();
        } else {
          lastTap = time;
        }
      }
    };
    const cancel = () => {
      start = null;
    };
    el.addEventListener('pointerdown', down);
    el.addEventListener('pointerup', up);
    el.addEventListener('pointercancel', cancel);
    return () => {
      el.removeEventListener('pointerdown', down);
      el.removeEventListener('pointerup', up);
      el.removeEventListener('pointercancel', cancel);
    };
  }, []);

  // ------------------------------------------------------------ view
  const shutterState: ShutterState =
    !live || !joined || !filter
      ? 'not-ready'
      : count
        ? 'counting'
        : busy
          ? 'capturing'
          : blocked
            ? 'blocked'
            : 'ready';
  const waitSeconds = shot ? Math.max(0, Math.ceil((shot.waitUntil - now) / 1000)) : 0;
  const number = shot?.result ? (shot.result.booth_number ?? shot.result.photo.seq) : null;

  let film;
  if (!shot) {
    film = (
      <FilmEdge
        label="Nächstes Foto"
        {...(lastNumber === null ? {} : { frame: lastNumber + 1 })}
        end={filter?.name ?? ''}
        state={outbox.pending > 0 ? 'waiting' : 'idle'}
        {...(lastNumber === null ? {} : { advanceKey: lastNumber })}
      />
    );
  } else {
    const filmState: FilmEdgeState =
      shot.status === 'uploading'
        ? 'uploading'
        : shot.status === 'done'
          ? 'done'
          : shot.status === 'failed'
            ? 'error'
            : 'waiting';
    const end =
      shot.status === 'uploading' ? (
        <span className="tabular">
          {t.uploading} {formatPercent(shot.progress)}
        </span>
      ) : shot.status === 'done' ? (
        <span className="inline-flex items-center gap-1 font-semibold text-ok">
          <Check aria-hidden="true" className="size-4" strokeWidth={2.5} />
          {t.uploaded}
        </span>
      ) : shot.status === 'waiting' ? (
        <FilmRetry onPress={() => void retry()} waitSeconds={waitSeconds} />
      ) : shot.status === 'held' ? (
        <span className="font-semibold text-accent">{t.waiting}</span>
      ) : (
        <span className="font-semibold text-danger">Nicht hochgeladen</span>
      );
    film = (
      <div data-testid="upload-status" data-state={shot.status}>
        <FilmEdge
          label="Foto"
          {...(number === null ? {} : { frame: number, advanceKey: number })}
          end={end}
          state={filmState}
          progress={shot.progress}
          progressLabel={t.uploading}
        />
      </div>
    );
  }

  let hint;
  if (shot) {
    const message = shotErrorText(shot.error, waitSeconds);
    hint = (
      <div aria-live="polite" data-testid="result-text" className="grid gap-1">
        {shot.status === 'done' ? (
          <span className="sr-only">{t.uploaded}</span>
        ) : shot.status === 'uploading' ? null : shot.status === 'failed' ? (
          <p className="text-sm text-papier-muted">
            <strong className="font-semibold text-papier">Nicht hochgeladen.</strong> {message} Speichern geht
            trotzdem.
          </p>
        ) : (
          <p className="text-sm text-papier-muted">
            <strong className="font-semibold text-papier">Dein Foto wartet.</strong> {message}{' '}
            {shot.status === 'held'
              ? 'Es wird gesendet, sobald du wieder hochladen kannst.'
              : 'Es wird gesendet, sobald es geht.'}
          </p>
        )}
      </div>
    );
  } else if (status.kind !== 'ok') {
    hint = <CameraStatus onSend={() => void sendOutbox()} sending={sendingOutbox} />;
  }

  const controls = shot ? (
    <>
      <Button
        variant="primary"
        size="lg"
        icon={saved ? Check : Download}
        data-testid="save"
        data-saved={saved ? '1' : undefined}
        className="flex-1"
        onPress={() => void save()}
      >
        {saved ? msg.saved : t.save}
      </Button>
      {offerShare ? (
        <IconButton
          label="Teilen"
          icon={Share2}
          variant="camera"
          size="lg"
          data-testid="share"
          className="size-14"
          onPress={() => void share()}
        />
      ) : null}
      <Button
        variant="secondary"
        size="lg"
        icon={Camera}
        data-testid="again"
        className="flex-1"
        onPress={() => void again()}
      >
        {t.newPhoto}
      </Button>
    </>
  ) : (
    <>
      <ToggleButton
        data-testid="countdown-toggle"
        aria-label={`Countdown ${COUNTDOWN_SECONDS} Sekunden`}
        isSelected={countdownOn}
        onChange={toggleCountdown}
        isDisabled={busy}
        className={cx(
          buttonStyles({ variant: 'camera', size: 'sm' }),
          'min-w-22 tabular selected:text-accent selected:ring-2 selected:ring-accent',
        )}
      >
        <Timer aria-hidden="true" className="size-5 shrink-0" strokeWidth={2} />
        <span aria-hidden="true">{countdownOn ? `${COUNTDOWN_SECONDS}${NBSP}s` : t.countdownOff}</span>
      </ToggleButton>
      <div ref={shutterRef}>
        <Shutter
          data-testid="shutter"
          state={shutterState}
          {...(count ? { countdownProgress: count.progress } : {})}
          keyHint="Leertaste"
          onPress={() => {
            if (count) cancelCount.current?.();
            else if (blocked) explainBlocked();
            else void shoot();
          }}
        />
      </div>
      {cam.canSwitch ? (
        <IconButton
          label={t.switchCamera}
          icon={SwitchCamera}
          variant="camera"
          size="lg"
          data-testid="switch-camera"
          isDisabled={!live || busy}
          onPress={switchCamera}
        />
      ) : (
        <span aria-hidden="true" className="size-12" />
      )}
    </>
  );

  return (
    <ActivityShell
      heading={TITLE}
      title={<ActivityMenu currentId={id} title={TITLE} />}
      topRight={<GuestPass compact />}
      stageTestId="preview"
      rootProps={{
        'data-testid': 'booth',
        'data-screen': shot ? 'result' : 'camera',
        'data-ready': live ? '1' : undefined,
        'data-renderer': cam.renderer ?? undefined,
        'data-filter': filter?.id,
        'data-facing': cam.facing,
        'data-mirror': cam.mirrored ? '1' : '0',
        'data-counting': count ? '1' : undefined,
      }}
      stage={
        <div ref={gestureRef} className="absolute inset-0 touch-none">
          <CameraStage
            videoRef={videoRef}
            mountRef={mountRef}
            ready={live || !!shot}
            {...(joined ? {} : { waiting: <span className="px-6 text-center">Gleich geht’s los…</span> })}
          >
            {shot ? (
              <img
                src={shot.url}
                width={1080}
                height={1440}
                alt="Dein Foto"
                data-testid="result-photo"
                className="absolute inset-0 size-full object-cover motion-ok:animate-develop"
              />
            ) : null}
            {count ? (
              <div
                data-testid="countdown"
                data-value={count.value}
                className="absolute inset-0 z-(--z-raised) grid place-items-center"
              >
                <Countdown
                  value={count.value}
                  progress={count.progress}
                  onCancel={() => cancelCount.current?.()}
                  announcement={`Countdown läuft, ${COUNTDOWN_SECONDS} Sekunden`}
                />
              </div>
            ) : null}
          </CameraStage>
        </div>
      }
      filmEdge={film}
      strip={
        shot ? undefined : (
          <FilterStrip
            filters={filters}
            selectedId={filter?.id ?? ''}
            onSelect={setSelectedId}
            swatches={swatches}
            isDisabled={!!count || busy}
          />
        )
      }
      hint={hint}
      controls={controls}
      controlsLayout={shot ? 'actions' : 'camera'}
      holdLayout={!!shot}
    >
      {cam.status === 'error' && cam.error ? <CameraErrorScreen error={cam.error} /> : null}
      <StatusSheet status={status} isOpen={whyOpen} onOpenChange={setWhyOpen} />
    </ActivityShell>
  );
}
