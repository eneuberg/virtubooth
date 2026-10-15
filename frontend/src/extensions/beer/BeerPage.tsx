/**
 * Beer Cam: one photo per drink, in the same framing every time (the timelapse
 * source). OWNER: wave 2 "AC". Port of beer/static/beer.js.
 *
 * The 3:4 stage is exactly the saved photo: the renderer draws the cover-cropped
 * camera picture (mirrored only for the front camera) and the capture renders the same
 * frame at 1080×1440. The bottle or cup outline lies over it in photo coordinates; it
 * is a guide and never part of the photo.
 *
 * Never lose a shot: when the guest may not upload (paused, stopped) the shutter is
 * locked and the hint says why, before anyone shoots. A failed upload waits in the
 * outbox (on disk) and is sent later; "Noch ein Bier" never throws a beer away.
 */
import { SwitchCamera } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { formatCount, formatNumber, formatPercent } from '@/lib/format';
import { t } from '@/lib/messages.de';
import { CameraStatus, FilmRetry } from '@/sdk/camera/CameraHints';
import { UploadState } from '@/sdk/camera/UploadState';
import { CameraErrorScreen } from '@/sdk/camera/CameraScreens';
import { CameraStage, PREVIEW_CANVAS_CLASS } from '@/sdk/camera/CameraStage';
import { STREAM_SIZE } from '@/sdk/camera/capture';
import { useCameraKeys, useLeaveGuard } from '@/sdk/camera/keys';
import { isVessel, VESSEL_SHAPES, VESSELS, shadePath, type Vessel } from '@/sdk/camera/overlays';
import { useCameraSession } from '@/sdk/camera/useCameraSession';
import { useNow, useOutboxToasts, useShot, type Shot } from '@/sdk/camera/useShot';
import { ActivityMenu } from '@/sdk/components/ActivityMenu';
import { ActivityShell } from '@/sdk/components/ActivityShell';
import { GuestPass } from '@/sdk/components/GuestPass';
import { StatusSheet } from '@/sdk/components/StatusSlot';
import type { ExtensionPageProps } from '@/sdk/extension';
import { flash, vibrate } from '@/sdk/feedback';
import { flushOutbox, useOutbox } from '@/sdk/outbox';
import { canUpload, useSession } from '@/sdk/session';
import { useGuestStatus } from '@/sdk/status';
import { Button } from '@/ui/Button';
import { FilmEdge, type FilmEdgeState } from '@/ui/FilmEdge';
import { IconButton } from '@/ui/IconButton';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { Shutter, type ShutterState } from '@/ui/Shutter';
import { clearToasts, showToast } from '@/ui/Toast';
import { useBeerStats } from './useBeerStats';
import { VESSEL_ICONS } from './vesselIcons';

const TITLE = 'Beer Cam';
const VESSEL_KEY = 'vb_beer_vessel';

const CHEERS = [
  'Prost!',
  'Zum Wohl!',
  'Auf die Million!',
  'Der Zeitraffer dankt dir.',
  'Läuft bei dir!',
  'Ein Frame für die Ewigkeit.',
  'Hopfen und Malz, Gott erhalt’s!',
];

function readVessel(): Vessel {
  try {
    const saved = localStorage.getItem(VESSEL_KEY);
    return isVessel(saved) ? saved : 'bottle';
  } catch {
    return 'bottle';
  }
}

function saveVessel(vessel: Vessel): void {
  try {
    localStorage.setItem(VESSEL_KEY, vessel);
  } catch {
    // private mode: remembered for this visit only
  }
}

function prefer(): 'canvas2d' | null {
  return new URLSearchParams(location.search).get('renderer') === 'canvas2d' ? 'canvas2d' : null;
}

/** The outline over the stage: shade around the drink, halo, details, line. */
function Outline({ vessel }: { vessel: Vessel }) {
  const shape = VESSEL_SHAPES[vessel];
  return (
    <svg
      data-testid="overlay"
      data-vessel={vessel}
      viewBox="0 0 1080 1440"
      preserveAspectRatio="none"
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 size-full"
    >
      <g data-testid={`overlay-${vessel}`}>
        <path d={shadePath(vessel)} fillRule="evenodd" className="fill-black/40" />
        <path
          d={shape.outline}
          vectorEffect="non-scaling-stroke"
          className="fill-none stroke-black/55 stroke-7"
        />
        <path
          d={`${shape.details} ${shape.shine}`}
          vectorEffect="non-scaling-stroke"
          className="fill-none stroke-white/55 stroke-2"
        />
        <path
          d={shape.outline}
          data-testid="outline-line"
          vectorEffect="non-scaling-stroke"
          className="fill-none stroke-white stroke-3"
        />
      </g>
    </svg>
  );
}

/** A sent beer's number: its photo's seq, as "Deine Bilder" shows it (not the board count). */
function beerNumber(shot: Shot): number | null {
  const r = shot.result;
  if (!r) return null;
  return r.beer_number ?? r.photo.seq;
}

/** Rendered inside GP's session gate: the guest has joined (banned/error never get here). */
export default function BeerPage({ id }: ExtensionPageProps) {
  const session = useSession();
  const gate = canUpload(session);
  const joined = session.status === 'ready';
  const [vessel, setVessel] = useState<Vessel>(readVessel);
  const [busy, setBusy] = useState(false);
  const [cheer, setCheer] = useState('');
  const [renderer] = useState(prefer);
  const {
    videoRef,
    mountRef,
    session: camera,
    camera: cam,
  } = useCameraSession({
    enabled: joined,
    facing: 'environment',
    ...STREAM_SIZE.beer,
    prefer: renderer,
    canvasClassName: PREVIEW_CANVAS_CLASS,
    canvasTestId: 'preview-canvas',
  });
  const stats = useBeerStats();
  const outbox = useOutbox();
  const { shot, take, retry, dismiss } = useShot(id);
  const [sendingOutbox, setSendingOutbox] = useState(false);
  useOutboxToasts(shot?.id ?? null);
  const now = useNow(!!shot && shot.waitUntil > 0);

  const live = cam.status === 'live' && cam.ready;
  const blocked = joined && !gate.ok;

  // uploads allowed again (the guest app says so): send what waited
  const wasBlocked = useRef(false);
  useEffect(() => {
    if (!joined) return;
    if (wasBlocked.current && !blocked) void flushOutbox({ force: true });
    wasBlocked.current = blocked;
  }, [blocked, joined]);

  // a photo that exists only in memory (no IndexedDB) or is still on its way unstored
  useLeaveGuard(outbox.atRisk > 0);

  const chooseVessel = (next: Vessel) => {
    setVessel(next);
    saveVessel(next);
  };

  // the locked shutter explains: the status sheet ("Hochladen pausiert" …)
  const status = useGuestStatus();
  const [whyOpen, setWhyOpen] = useState(false);
  const explainBlocked = () => {
    vibrate([20, 40, 20]);
    setWhyOpen(true);
  };

  const shoot = async () => {
    if (busy || shot || !camera || !live) return;
    if (!gate.ok) {
      explainBlocked();
      return;
    }
    setBusy(true);
    clearToasts();
    flash();
    vibrate(40);
    let blob: Blob;
    try {
      blob = await camera.capture();
    } catch {
      setBusy(false);
      showToast({ message: 'Das Foto hat nicht geklappt. Versuch es nochmal.', tone: 'error' });
      await camera.resume().catch(() => undefined);
      return;
    }
    setCheer(CHEERS[Math.floor(Math.random() * CHEERS.length)] ?? 'Prost!');
    setBusy(false);
    const result = await take(blob, { vessel, facing: cam.facing });
    if (result) {
      stats.note(result);
      vibrate([30, 60, 30]);
    }
  };

  const again = async () => {
    dismiss();
    clearToasts();
    void stats.refresh();
    await camera?.resume().catch(() => undefined);
    // the focused "Noch ein Bier" is gone: Space/Enter go to the shutter now
    document.querySelector<HTMLElement>('[data-testid="shutter"]')?.focus({ preventScroll: true });
  };

  const sendOutbox = async () => {
    setSendingOutbox(true);
    try {
      await flushOutbox({ force: true });
    } finally {
      setSendingOutbox(false);
    }
  };

  useCameraKeys({
    shutter: () => void shoot(),
    ...(shot ? { escape: () => void again() } : {}),
  });

  // focus the main action of the print when it appears (keyboard users)
  const shotShown = !!shot;
  useEffect(() => {
    if (shotShown)
      document.querySelector<HTMLElement>('[data-testid="again"]')?.focus({ preventScroll: true });
  }, [shotShown]);

  const shutterState: ShutterState =
    !live || !joined ? 'not-ready' : busy ? 'capturing' : blocked ? 'blocked' : 'ready';
  const number = shot ? beerNumber(shot) : null;
  const next = stats.next ?? undefined;
  // towards the million counts the board (hidden and deleted beers don't)
  const board = shot?.result?.total ?? stats.total;
  const togo = board === null ? null : Math.max(0, stats.goal - board);
  const waitSeconds = shot ? Math.max(0, Math.ceil((shot.waitUntil - now) / 1000)) : 0;

  // ------------------------------------------------------------ film edge
  let film;
  if (!shot) {
    film = (
      <FilmEdge
        data-testid="counter"
        data-total={stats.total ?? ''}
        data-next={next ?? ''}
        label="Nächstes Bier"
        {...(next === undefined ? {} : { frame: next })}
        end={<>Ziel {formatCount(stats.goal)}</>}
        state={outbox.pending > 0 ? 'waiting' : 'idle'}
        advanceKey={next ?? 0}
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
        <span className="tabular">{formatPercent(shot.progress)}</span>
      ) : shot.status === 'done' ? (
        <span className="font-semibold text-ok">Gezählt</span>
      ) : shot.status === 'waiting' ? (
        <FilmRetry onPress={() => void retry()} waitSeconds={waitSeconds} />
      ) : shot.status === 'held' ? (
        <span className="font-semibold text-accent">{t.waiting}</span>
      ) : (
        <span className="font-semibold text-danger">Nicht hochgeladen</span>
      );
    film = (
      // data-state: the shot's upload status (uploading, done, waiting, held, failed)
      <FilmEdge
        data-testid="upload-status"
        data-state={shot.status}
        label="Bier"
        {...(number === null ? {} : { frame: number })}
        end={end}
        state={filmState}
        progress={shot.progress}
        progressLabel={t.uploading}
        {...(number === null ? {} : { advanceKey: number })}
      />
    );
  }

  // ------------------------------------------------------------ hint
  let hint;
  if (shot) {
    hint = (
      <UploadState
        shot={shot}
        waitSeconds={waitSeconds}
        verb="gezählt"
        done={
          number === null ? null : (
            <>
              <span data-testid="success-title" className="font-semibold text-papier">
                Bier Nr.&nbsp;{formatNumber(number)} gezählt
              </span>
              {'. '}
              {togo === null
                ? ''
                : togo > 0
                  ? `Noch ${formatNumber(togo)} bis zur Million. `
                  : 'Die Million ist voll! '}
              {number % 100 === 0 ? 'Jubiläumsbier!' : cheer}
            </>
          )
        }
      />
    );
  } else if (status.kind !== 'ok') {
    hint = <CameraStatus onSend={() => void sendOutbox()} sending={sendingOutbox} />;
  } else {
    hint = <p data-testid="hint">{VESSEL_SHAPES[vessel].hint}</p>;
  }

  // ------------------------------------------------------------ controls
  const controls = shot ? (
    <Button
      variant="primary"
      size="lg"
      block
      className="flex-1"
      data-testid="again"
      onPress={() => void again()}
    >
      {t.anotherBeer}
    </Button>
  ) : (
    <>
      <SegmentedControl
        label="Gefäß"
        tone="camera"
        iconOnly="narrow"
        value={vessel}
        onChange={chooseVessel}
        data-testid="vessel"
        options={VESSELS.map((v) => ({ id: v, label: VESSEL_SHAPES[v].label, icon: VESSEL_ICONS[v] }))}
      />
      <Shutter
        data-testid="shutter"
        state={shutterState}
        keyHint="Leertaste"
        onPress={() => (blocked ? explainBlocked() : void shoot())}
      />
      {cam.canSwitch ? (
        <IconButton
          label={t.switchCamera}
          icon={SwitchCamera}
          variant="camera"
          size="lg"
          data-testid="switch-camera"
          isDisabled={!live || busy}
          onPress={() => {
            camera?.switchFacing().catch((err: unknown) => {
              showToast({
                message:
                  err instanceof Error && err.message ? err.message : 'Kamera wechseln hat nicht geklappt.',
                tone: 'error',
              });
            });
          }}
        />
      ) : (
        <span aria-hidden="true" className="size-12" />
      )}
    </>
  );

  const stageState = shot ? 'result' : live ? 'camera' : 'loading';

  return (
    <ActivityShell
      heading={TITLE}
      title={<ActivityMenu currentId={id} title={TITLE} />}
      topRight={<GuestPass compact />}
      stageTestId="frame"
      rootProps={{
        'data-testid': 'beer-app',
        'data-state': stageState,
        'data-vessel': vessel,
        'data-ready': live ? '1' : undefined,
        'data-renderer': cam.renderer ?? undefined,
        'data-facing': cam.facing,
        'data-mirror': cam.mirrored ? '1' : '0',
      }}
      stage={
        <CameraStage
          videoRef={videoRef}
          mountRef={mountRef}
          ready={live || !!shot}
          {...(joined
            ? {}
            : {
                waiting: <span className="px-6 text-center">Gleich geht’s los…</span>,
              })}
        >
          {shot ? (
            <img
              src={shot.url}
              width={1080}
              height={1440}
              alt="Dein Bier"
              data-testid="result-photo"
              className="absolute inset-0 size-full object-cover motion-ok:animate-develop"
            />
          ) : (
            <Outline vessel={vessel} />
          )}
        </CameraStage>
      }
      filmEdge={film}
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
