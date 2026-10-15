import { describe, expect, it } from 'vitest';
import { NORMAL, type FilterImpl } from './filters';
import type { Look, Renderer } from './renderer';
import { changesPicture, renderShot } from './session';

const THERMAL: FilterImpl = { id: 'thermal', glsl: 'vec3 effect(vec2 uv) { return vec3(1.0); }' };

/** A canvas stand-in: toBlob hands out a Blob naming what was drawn. */
function fakeCanvas(label: string): HTMLCanvasElement {
  const canvas = {
    width: 1080,
    height: 1440,
    toBlob: (cb: (blob: Blob | null) => void, type: string) => cb(new Blob([label], { type })),
  };
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- the two members renderShot uses
  return canvas as unknown as HTMLCanvasElement;
}

function fakeRenderer() {
  const calls: string[] = [];
  const shown = fakeCanvas('shown');
  let plain: HTMLCanvasElement | null = null;
  // oxlint-disable-next-line typescript/no-unsafe-type-assertion -- the members renderShot uses
  const renderer = {
    kind: 'webgl',
    hasFrame: true,
    capture: () => {
      calls.push('capture');
      return shown;
    },
    snapshot: (w: number, h: number, look?: Look) => {
      calls.push(`snapshot ${w}x${h} ${look?.filter.id ?? '-'} ${look?.overlay ? 'overlay' : 'none'}`);
      plain = fakeCanvas('plain');
      return plain;
    },
  } as unknown as Renderer;
  return { renderer, calls, plain: () => plain };
}

describe('a Fotobox shot', () => {
  it('is the photo as shown plus the same frame without filter and overlay', async () => {
    const { renderer, calls, plain } = fakeRenderer();
    const overlay = fakeCanvas('overlay');
    const shot = await renderShot(renderer, { filter: THERMAL, overlay }, 0.9);
    expect(await shot.photo.text()).toBe('shown');
    expect(await shot.raw?.text()).toBe('plain');
    expect(shot.photo.type).toBe('image/jpeg');
    expect(shot.raw?.type).toBe('image/jpeg');
    // both drawn before the first await (Canvas2D reads the live video), at the photo size
    expect(calls).toEqual(['capture', 'snapshot 1080x1440 normal none']);
    // the original's canvas is freed at once (iOS canvas memory)
    expect([plain()?.width, plain()?.height]).toEqual([0, 0]);
  });

  it('has no separate original when the look changes nothing („Normal“ without overlay)', async () => {
    const { renderer, calls } = fakeRenderer();
    const shot = await renderShot(renderer, { filter: NORMAL, overlay: null });
    expect(shot.raw).toBeNull();
    expect(calls).toEqual(['capture']);
  });

  it('knows which looks change the picture', () => {
    expect(changesPicture({ filter: NORMAL, overlay: null })).toBe(false);
    expect(changesPicture({ filter: NORMAL, overlay: fakeCanvas('frame') })).toBe(true);
    expect(changesPicture({ filter: THERMAL, overlay: null })).toBe(true);
  });
});
