import { describe, expect, it } from 'vitest';
import { coverRect, mapBox, MAX_TILE_FRAMES, TILE_ASPECT, tileFrames } from './tileFrames';

const near = (x: number, y: number, w: number, h: number) => ({
  x: expect.closeTo(x, 6),
  y: expect.closeTo(y, 6),
  w: expect.closeTo(w, 6),
  h: expect.closeTo(h, 6),
});

const o = (label_de: string, box: { x: number; y: number; w: number; h: number } | null) => ({
  label_de,
  source: 'local',
  sources: ['local'],
  score: 0.9,
  box,
});

describe('coverRect (object-fit: cover)', () => {
  it('a 3:4 photo fills the 3:4 tile exactly', () => {
    expect(coverRect(3 / 4, TILE_ASPECT)).toEqual({ x: 0, y: 0, w: 1, h: 1 });
  });

  it('a landscape photo loses its sides', () => {
    // 16:9 in 3:4: 64/27 tile widths, centred
    expect(coverRect(16 / 9, 3 / 4)).toEqual(near((1 - 64 / 27) / 2, 0, 64 / 27, 1));
  });

  it('a tall photo loses a little top and bottom', () => {
    // 9:16 in 3:4: 4/3 tile heights
    expect(coverRect(9 / 16, 3 / 4)).toEqual(near(0, -1 / 6, 1, 4 / 3));
  });

  it('a broken size falls back to the full tile', () => {
    expect(coverRect(Number.NaN, 3 / 4)).toEqual({ x: 0, y: 0, w: 1, h: 1 });
    expect(coverRect(0, 3 / 4)).toEqual({ x: 0, y: 0, w: 1, h: 1 });
  });
});

describe('mapBox', () => {
  const landscape = coverRect(4 / 3, 3 / 4); // x = -7/18, w = 16/9

  it('moves and scales a box with the picture', () => {
    expect(mapBox({ x: 0.4, y: 0.25, w: 0.2, h: 0.5 }, landscape)).toEqual(
      near(-7 / 18 + 0.4 * (16 / 9), 0.25, 0.2 * (16 / 9), 0.5),
    );
  });

  it('clips a box at the cut edge and drops one that is cut away', () => {
    expect(mapBox({ x: 0.1, y: 0, w: 0.3, h: 1 }, landscape)).toEqual(
      near(0, 0, -7 / 18 + 0.4 * (16 / 9), 1),
    );
    expect(mapBox({ x: 0, y: 0, w: 0.2, h: 1 }, landscape)).toBeNull(); // all in the cut-off strip
    expect(mapBox({ x: 0.5, y: 0.5, w: 0.01, h: 0.5 }, { x: 0, y: 0, w: 1, h: 1 })).toBeNull(); // too thin
  });
});

describe('tileFrames', () => {
  it('objects, faces and hands, biggest first; labels only where they fit', () => {
    const frames = tileFrames(
      {
        objects: [
          o('Becher', { x: 0.1, y: 0.1, w: 0.2, h: 0.2 }),
          o('Person', { x: 0, y: 0, w: 0.9, h: 1 }),
          o('Kuchen', null),
        ],
        boxes: [
          { kind: 'hand', x: 0.5, y: 0.5, w: 0.1, h: 0.1 },
          { kind: 'face', x: 0.3, y: 0.1, w: 0.4, h: 0.3 },
        ],
      },
      3 / 4,
    );
    expect(frames.map((f) => [f.kind, f.label])).toEqual([
      ['object', 'Person'],
      ['face', null], // faces and hands: the outline only
      ['object', null], // the cup is too small for its name
      ['hand', null],
    ]);
  });

  it('keeps at most MAX_TILE_FRAMES, the biggest', () => {
    const many = Array.from({ length: 30 }, (_, i) => o(`O${i}`, { x: 0, y: 0, w: 0.1 + i / 100, h: 0.2 }));
    const frames = tileFrames({ objects: many, boxes: [] }, 3 / 4);
    expect(frames).toHaveLength(MAX_TILE_FRAMES);
    expect(frames[0]!.w).toBeCloseTo(0.39, 6);
  });
});
