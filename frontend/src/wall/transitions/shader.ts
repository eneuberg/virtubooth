/**
 * dither + pixelate: the shared WebGL canvas lies over the new photo card and renders
 * old → new; without WebGL both are a crossfade.
 */
import { sharedGl, type GlMode } from '../gl/gl';
import { crossfade } from './motion';
import { captionIn, fadeOut, imgOf, picOf, play, type Transition } from './types';

const MAX_SIDE = 2048;

function shaderTransition(mode: GlMode): Transition {
  return (args) => {
    const { from, to, ms, signal } = args;
    const gl = sharedGl();
    const pic = picOf(to);
    const img = imgOf(to);
    if (!gl || !img) return crossfade(args);
    const rect = img.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const scale = Math.min(dpr, MAX_SIDE / Math.max(rect.width, rect.height, 1));
    if (!gl.prepare(rect.width * scale, rect.height * scale, from ? imgOf(from) : null, img)) {
      return crossfade(args);
    }
    const canvas = gl.canvas;
    gl.draw(mode, 0);
    pic.append(canvas);
    const animations = [
      to.animate(
        [
          { opacity: 0, transform: 'scale(0.97)' },
          { opacity: 1, transform: 'none', offset: 0.18 },
          { opacity: 1, transform: 'none' },
        ],
        { duration: ms, fill: 'backwards' },
      ),
      ...fadeOut(from, ms * 0.25),
      ...captionIn(to, ms * 0.35, ms * 0.6),
    ];
    const start = performance.now();
    let frame = 0;
    const tick = (now: number): void => {
      const p = Math.min(1, (now - start) / ms);
      gl.draw(mode, p);
      if (p < 1 && !signal.aborted) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return play(animations, signal).then(() => {
      cancelAnimationFrame(frame);
      canvas.remove();
    });
  };
}

export const dither = shaderTransition(1);
export const pixelate = shaderTransition(0);
