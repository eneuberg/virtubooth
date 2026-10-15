/**
 * A small 16:9 look at the wall with the draft's colours and background: the wall's
 * own background renderer (`mountBackground`, loaded lazily from the wall's code) on a
 * canvas; until it is there (or without canvas 2D) a CSS gradient moved with WAAPI.
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { cx } from '@/ui/cx';
import type { BackgroundHandle } from '@/wall/background';
import type { WallConfig } from './types';

/** the look with its colours resolved (a null colour follows the theme) */
type Look = WallConfig['look'] & { primary: string; secondary: string; background: string };

/** The CSS background of each preset in the given colours (a = primary, b = secondary). */
const PRESET_BACKGROUND: Record<Look['preset'], (a: string, b: string) => CSSProperties> = {
  blobs: (a, b) => ({
    backgroundImage: `radial-gradient(circle at 28% 32%, ${a} 0, transparent 34%), radial-gradient(circle at 72% 68%, ${b} 0, transparent 36%)`,
  }),
  aurora: (a, b) => ({
    backgroundImage: `linear-gradient(160deg, transparent 22%, ${a}cc 44%, transparent 62%), linear-gradient(205deg, transparent 38%, ${b}aa 58%, transparent 78%)`,
  }),
  disco: (a, b) => ({
    backgroundImage: `repeating-linear-gradient(0deg, ${a}88 0 2px, transparent 2px 22px), repeating-linear-gradient(90deg, ${b}88 0 2px, transparent 2px 22px)`,
  }),
  confetti: (a, b) => ({
    backgroundImage: `radial-gradient(${a} 2px, transparent 3px), radial-gradient(${b} 2px, transparent 3px)`,
    backgroundSize: '22px 22px, 30px 30px',
  }),
  plain: () => ({ backgroundImage: 'none' }),
};

const CORNER_CLASS: Record<WallConfig['overlay']['corner'], string> = {
  'bottom-right': 'right-[3%] bottom-[4%]',
  'bottom-left': 'bottom-[4%] left-[3%]',
  'top-right': 'top-[4%] right-[3%]',
  'top-left': 'top-[4%] left-[3%]',
};

function canvas2d(): boolean {
  try {
    return typeof document !== 'undefined' && !!document.createElement('canvas').getContext('2d');
  } catch {
    return false;
  }
}

/** The wall's background on `canvas` once its module loaded; null meanwhile (or never). */
function useWallBackground(canvas: React.RefObject<HTMLCanvasElement | null>, look: Look): boolean {
  const handle = useRef<BackgroundHandle | null>(null);
  const latest = useRef(look);
  const [live, setLive] = useState(false);

  useEffect(() => {
    const el = canvas.current;
    if (!el || !canvas2d()) return undefined;
    let cancelled = false;
    import('@/wall/background')
      .then(({ mountBackground }) => {
        if (cancelled) return;
        handle.current = mountBackground(el, latest.current, { maxWidth: 480 });
        setLive(true);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      handle.current?.destroy();
      handle.current = null;
    };
  }, [canvas]);

  useEffect(() => {
    latest.current = look;
    handle.current?.update(look);
  }, [look]);

  return live;
}

export function WallPreview({ look, overlay }: { look: Look; overlay: WallConfig['overlay'] }) {
  const layer = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const live = useWallBackground(canvas, look);
  const still = look.calm || look.preset === 'plain';
  const fps = look.fps;

  useEffect(() => {
    const el = layer.current;
    const moving =
      el !== null &&
      !live &&
      !still &&
      typeof el.animate === 'function' &&
      !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const animation = moving
      ? el.animate(
          [
            { transform: 'translate(0, 0) rotate(0deg)' },
            { transform: 'translate(6%, -4%) rotate(8deg)' },
            { transform: 'translate(-4%, 5%) rotate(-6deg)' },
            { transform: 'translate(0, 0) rotate(0deg)' },
          ],
          { duration: fps === 60 ? 9000 : 12_000, iterations: Infinity, easing: 'ease-in-out' },
        )
      : null;
    return () => animation?.cancel();
  }, [still, fps, live]);

  const showBadge = overlay.event_name || overlay.counter || overlay.qr;
  return (
    <div
      aria-hidden="true"
      data-testid="wall-preview"
      className="relative aspect-video w-full max-w-md overflow-hidden rounded-control ring-1 ring-line"
      style={{ backgroundColor: look.background }}
    >
      <canvas ref={canvas} className="absolute inset-0 size-full" data-testid="wall-preview-canvas" />
      <div
        ref={layer}
        className={cx('absolute -inset-1/4', live && 'hidden')}
        style={PRESET_BACKGROUND[look.preset](look.primary, look.secondary)}
      />
      <div className="absolute top-[18%] left-1/2 h-[64%] w-[30%] -translate-x-1/2 rotate-[-2deg] bg-white p-[1.5%] pb-[5%] shadow-float">
        <div className="size-full bg-surface-sunk" />
      </div>
      {showBadge ? (
        <div
          className={cx(
            'absolute grid justify-items-end gap-1 rounded-small bg-black/55 px-2 py-1 text-[0.625rem] font-semibold text-white',
            CORNER_CLASS[overlay.corner],
          )}
        >
          {overlay.qr ? (
            <div className="size-8 bg-white ring-2 ring-white" data-testid="wall-preview-qr" />
          ) : null}
          {overlay.event_name || overlay.counter ? (
            <span>
              {[overlay.event_name ? 'Eventname' : null, overlay.counter ? '128 Fotos' : null]
                .filter(Boolean)
                .join(' · ')}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
