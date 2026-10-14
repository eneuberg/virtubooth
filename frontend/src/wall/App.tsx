/**
 * The Live-Wall app: session check → login / no password / connecting → the live wall
 * (playlist of modes over the animated background, corner overlay, TV controls).
 */
import { useEffect, useMemo, useReducer, useRef, useState } from 'react';
import { fetchCategories, fetchFeed, sessionStatus } from './api/client';
import { browserStreamDeps, openWallStream, type StreamStatus } from './api/stream';
import { DEFAULT_CONFIG, type WallCategory, type WallLook, type WallMode } from './api/types';
import { mountBackground, type BackgroundHandle } from './background';
import { highlightIds, visibleCategories } from './modes/categories';
import { Categories, Gallery, Spotlight } from './modes/Modes';
import { Corner } from './overlay/Corner';
import { modeAllowed, modeContent, modeDuration, nextMode } from './playlist';
import { ConnectingScreen, EmptyScreen, LoginScreen, NoPasswordScreen, OfflineHint } from './screens/Screens';
import { initialWallState, wallReducer, type WallState } from './state/photos';
import { useFullscreen, useIdle } from './tv/hooks';
import {
  fullscreenAvailable,
  keepScreenOn,
  softReloadDue,
  toggleFullscreen,
  wakeLockSupported,
} from './tv/screen';

type Phase = 'checking' | 'login' | 'nopassword' | 'connecting' | 'live';

const IDLE_MS = 3000;
const OFFLINE_GRACE_MS = 2500;
const CATEGORIES_REFRESH_MS = 5 * 60_000;
/** how long a mode that ends keeps fading out (wall.css: wall-mode-out) */
const MODE_FADE_MS = 900;

function applyLook(look: WallLook): void {
  const root = document.documentElement.style;
  root.setProperty('--wall-primary', look.primary);
  root.setProperty('--wall-secondary', look.secondary);
  root.setProperty('--wall-bg', look.background);
}

function FullscreenButton({ side }: { side: 'left' | 'right' }) {
  const full = useFullscreen();
  if (!fullscreenAvailable()) return null;
  return (
    <button
      type="button"
      className="wall-fs"
      data-side={side}
      data-testid="wall-fullscreen"
      onClick={() => void toggleFullscreen()}
    >
      {full ? 'Vollbild beenden' : 'Vollbild'}
    </button>
  );
}

function LiveWall({ state, categories }: { state: WallState; categories: readonly WallCategory[] }) {
  const { config } = state;
  const cats = useMemo(
    () => visibleCategories(categories, config.categories.disabled, state.removed),
    [categories, config.categories.disabled, state.removed],
  );
  const content = modeContent(state.photos.length, cats.length);
  // the current playlist slot: which mode, since when
  const [slot, setSlot] = useState<{ mode: WallMode | null; since: number }>(() => ({
    mode: null,
    since: performance.now(),
  }));
  let active: WallMode | null =
    slot.mode !== null && modeAllowed(config.playlist, slot.mode, content)
      ? slot.mode
      : nextMode(config.playlist, slot.mode, content);
  // photos, but no enabled mode can show them (e.g. only the gallery with 3 photos): spotlight
  if (active === null && state.photos.length > 0) active = 'spotlight';

  const latest = useRef({ playlist: config.playlist, content });
  useEffect(() => {
    latest.current = { playlist: config.playlist, content };
  });
  const durationMs = active === null ? 0 : modeDuration(config.playlist, active) * 1000;
  useEffect(() => {
    if (active === null) return undefined;
    const left = Math.max(1000, slot.since + durationMs - performance.now());
    const timer = setTimeout(() => {
      // the planned soft reload happens between two modes, never in the middle of one
      if (softReloadDue()) {
        location.reload();
        return;
      }
      const next = nextMode(latest.current.playlist, active, latest.current.content) ?? active;
      setSlot({ mode: next, since: performance.now() });
    }, left);
    return () => clearTimeout(timer);
  }, [active, slot, durationMs]);

  const highlights = useMemo(() => highlightIds(cats), [cats]);
  const spotlightInput = useMemo(
    () => ({
      photos: state.photos,
      fresh: state.fresh,
      highlights,
      config,
      clockSkewMs: state.clockSkewMs,
    }),
    [state.photos, state.fresh, highlights, config, state.clockSkewMs],
  );

  // the previous mode stays while it fades out (crossfade); same key → no remount
  const [modes, setModes] = useState<{ current: WallMode | null; leaving: WallMode | null }>({
    current: active,
    leaving: null,
  });
  if (modes.current !== active) {
    setModes({ current: active, leaving: modes.current });
  }
  const { leaving } = modes;
  useEffect(() => {
    if (leaving === null) return undefined;
    const timer = setTimeout(() => setModes((m) => ({ ...m, leaving: null })), MODE_FADE_MS);
    return () => clearTimeout(timer);
  }, [leaving]);

  const render = (mode: WallMode, isLeaving: boolean) => (
    <div
      className="wall-mode"
      key={mode}
      data-mode={mode}
      data-leaving={isLeaving ? '' : undefined}
      aria-hidden={isLeaving ? true : undefined}
    >
      {mode === 'spotlight' ? <Spotlight input={spotlightInput} /> : null}
      {mode === 'gallery' ? (
        <Gallery photos={state.photos} rows={config.gallery.rows} speed={config.gallery.speed} />
      ) : null}
      {mode === 'categories' ? (
        <Categories categories={cats} perCategoryS={config.categories.per_category_s} />
      ) : null}
    </div>
  );
  return (
    <>
      {leaving !== null && leaving !== active ? render(leaving, true) : null}
      {active === null ? <EmptyScreen key="empty" /> : render(active, false)}
    </>
  );
}

export function WallApp() {
  const [phase, setPhase] = useState<Phase>('checking');
  const [state, dispatch] = useReducer(wallReducer, initialWallState);
  const [offline, setOffline] = useState(false);
  const [categories, setCategories] = useState<WallCategory[]>([]);
  const idle = useIdle(IDLE_MS);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const backgroundRef = useRef<BackgroundHandle | null>(null);
  const refreshCategoriesRef = useRef<(() => void) | null>(null);
  const look = state.config.look;

  // the session decides the first screen; no answer → keep asking (2 s … 30 s)
  useEffect(() => {
    if (phase !== 'checking') return undefined;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const check = async (delay: number): Promise<void> => {
      const code = await sessionStatus().catch(() => 0);
      if (cancelled) return;
      if (code === 200) setPhase('connecting');
      else if (code === 401) setPhase('login');
      else if (code === 409) setPhase('nopassword');
      else timer = setTimeout(() => void check(Math.min(delay * 2, 30_000)), delay);
    };
    void check(2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [phase]);

  // one stream while connecting or live; a short hiccup is no reason to say "offline"
  const streaming = phase === 'connecting' || phase === 'live';
  useEffect(() => {
    if (!streaming) return undefined;
    let offlineTimer: ReturnType<typeof setTimeout> | undefined;
    const stream = openWallStream(
      {
        feed: (feed) => {
          dispatch({ type: 'feed', feed });
          setPhase('live');
        },
        event: (event) => {
          dispatch({ type: 'event', event });
          if (event.type === 'categories.changed') refreshCategoriesRef.current?.();
        },
        status: (status: StreamStatus) => {
          clearTimeout(offlineTimer);
          if (status === 'offline') offlineTimer = setTimeout(() => setOffline(true), OFFLINE_GRACE_MS);
          else setOffline(false);
        },
        auth: (problem) => setPhase(problem === 'login' ? 'login' : 'nopassword'),
      },
      browserStreamDeps(fetchFeed, sessionStatus),
    );
    return () => {
      clearTimeout(offlineTimer);
      stream.close();
    };
  }, [streaming]);

  // categories: when the wall starts, on `categories.changed`, and every few minutes
  const live = phase === 'live';
  useEffect(() => {
    if (!live) return undefined;
    let cancelled = false;
    const load = (): void => {
      fetchCategories().then(
        (list) => {
          if (!cancelled) setCategories(list);
        },
        () => undefined,
      );
    };
    refreshCategoriesRef.current = load;
    load();
    const timer = setInterval(load, CATEGORIES_REFRESH_MS);
    return () => {
      cancelled = true;
      refreshCategoriesRef.current = null;
      clearInterval(timer);
    };
  }, [live]);

  // background + colours
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const handle = mountBackground(canvas, DEFAULT_CONFIG.look);
    backgroundRef.current = handle;
    return () => {
      handle.destroy();
      backgroundRef.current = null;
    };
  }, []);
  useEffect(() => {
    applyLook(look);
    backgroundRef.current?.update(look);
  }, [look]);

  useEffect(() => keepScreenOn(), []);

  const corner = state.config.overlay.corner;
  return (
    <div
      className="wall"
      data-idle={idle ? '' : undefined}
      data-phase={phase}
      data-corner={phase === 'live' ? corner : undefined}
    >
      <canvas ref={canvasRef} className="wall-bg-canvas" aria-hidden="true" />
      {phase === 'login' ? (
        <LoginScreen onDone={() => setPhase('connecting')} onNoPassword={() => setPhase('nopassword')} />
      ) : null}
      {phase === 'nopassword' ? <NoPasswordScreen /> : null}
      {phase === 'checking' || phase === 'connecting' ? (
        <ConnectingScreen wakeLockHint={!wakeLockSupported()} />
      ) : null}
      {phase === 'live' ? (
        <>
          <div className="wall-safe">
            <LiveWall state={state} categories={categories} />
          </div>
          <Corner
            overlay={state.config.overlay}
            eventName={state.eventName}
            total={state.total}
            qr={state.qr}
          />
          {offline ? <OfflineHint /> : null}
        </>
      ) : null}
      <FullscreenButton side={phase === 'live' && corner === 'top-right' ? 'left' : 'right'} />
    </div>
  );
}
