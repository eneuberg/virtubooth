/**
 * The preview/capture renderer: WebGL1 with a Canvas2D fallback (webglcontextlost →
 * Canvas2D). OWNER: wave 2 "AC". Port of booth/static/renderer.js.
 */
import type { CropRect } from './capture';

export interface Renderer {
  readonly kind: 'webgl' | 'canvas2d';
  setFilter(filterId: string): void;
  /** draws one frame of `source` cropped by `crop` into the canvas */
  draw(source: TexImageSource, crop: CropRect, options: { mirror: boolean }): void;
  destroy(): void;
}

/** May replace the canvas (a canvas keeps its first context type): use the returned one. */
export function createRenderer(
  canvas: HTMLCanvasElement,
  options: { prefer?: 'webgl' | 'canvas2d' } = {},
): { renderer: Renderer; canvas: HTMLCanvasElement } {
  void canvas;
  void options;
  throw new Error('TODO(wave 2, AC): sdk/camera/renderer createRenderer');
}
