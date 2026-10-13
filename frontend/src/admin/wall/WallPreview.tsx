/**
 * A small 16:9 look at the wall with the draft's colours and background. For now a
 * CSS gradient moved with WAAPI (CSP-safe); integration swaps in the wall's own
 * background renderer (`mountBackground`).
 */
import { useEffect, useRef, type CSSProperties } from 'react';
import { cx } from '@/ui/cx';
import type { WallConfig } from './types';

type Look = WallConfig['look'];

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

export function WallPreview({ look, overlay }: { look: Look; overlay: WallConfig['overlay'] }) {
  const layer = useRef<HTMLDivElement>(null);
  const still = look.calm || look.preset === 'plain';
  const fps = look.fps;

  useEffect(() => {
    const el = layer.current;
    const moving =
      el !== null &&
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
  }, [still, fps]);

  const showBadge = overlay.event_name || overlay.counter;
  return (
    <div
      aria-hidden="true"
      data-testid="wall-preview"
      className="relative aspect-video w-full max-w-md overflow-hidden rounded-control ring-1 ring-line"
      style={{ backgroundColor: look.background }}
    >
      <div
        ref={layer}
        className="absolute -inset-1/4"
        style={PRESET_BACKGROUND[look.preset](look.primary, look.secondary)}
      />
      <div className="absolute top-[18%] left-1/2 h-[64%] w-[30%] -translate-x-1/2 rotate-[-2deg] bg-white p-[1.5%] pb-[5%] shadow-float">
        <div className="size-full bg-surface-sunk" />
      </div>
      {showBadge ? (
        <div
          className={cx(
            'absolute rounded-small bg-black/55 px-2 py-0.5 text-[0.625rem] font-semibold text-white',
            CORNER_CLASS[overlay.corner],
          )}
        >
          {[overlay.event_name ? 'Eventname' : null, overlay.counter ? '128 Fotos' : null]
            .filter(Boolean)
            .join(' · ')}
        </div>
      ) : null}
    </div>
  );
}
