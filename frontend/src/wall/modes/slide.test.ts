import { afterEach, describe, expect, it, vi } from 'vitest';
import { photo as wallPhoto } from '../fixtures.test-util';
import { buildSlide, refreshAges, slideSize, type Box } from './slide';

// the stage of a 1920×1080 TV: inside the 3.5 vmin overscan padding
const STAGE: Box = { left: 38, top: 38, right: 1882, bottom: 1042 };
const VMIN = 10.8;
// the corner with the QR code, event name and counter: about 300×330 px
const W = 300;
const H = 330;
const CORNERS: Record<string, Box> = {
  'bottom-right': { left: 1882 - W, top: 1042 - H, right: 1882, bottom: 1042 },
  'bottom-left': { left: 38, top: 1042 - H, right: 38 + W, bottom: 1042 },
  'top-right': { left: 1882 - W, top: 38, right: 1882, bottom: 38 + H },
  'top-left': { left: 38, top: 38, right: 38 + W, bottom: 38 + H },
};

function cardBox(size: { w: number; h: number }): Box {
  const cx = (STAGE.left + STAGE.right) / 2;
  const cy = (STAGE.top + STAGE.bottom) / 2;
  return { left: cx - size.w / 2, right: cx + size.w / 2, top: cy - size.h / 2, bottom: cy + size.h / 2 };
}

/** the caption hangs out of the card's bottom left: 2.6 vmin left, 3.2 vmin down (wall.css) */
function captionBox(card: Box): Box {
  return {
    left: card.left - 2.6 * VMIN,
    right: card.left + 0.9 * (card.right - card.left),
    top: card.bottom - 14 * VMIN,
    bottom: card.bottom + 3.2 * VMIN + 1.5 * VMIN,
  };
}

const intersects = (a: Box, b: Box): boolean =>
  a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

describe('slideSize', () => {
  it('without a corner: as large as fits, keeping the aspect', () => {
    expect(slideSize(0.75, STAGE, null, VMIN)).toEqual({ w: 633, h: 843 });
    expect(slideSize(16 / 9, STAGE, null, VMIN)).toEqual({ w: 1365, h: 768 });
  });

  it.each(Object.keys(CORNERS))('neither card nor caption reach the %s corner', (name) => {
    const corner = CORNERS[name]!;
    for (const aspect of [0.33, 0.56, 0.75, 1, 4 / 3, 1.5, 16 / 9, 2.4, 3]) {
      const size = slideSize(aspect, STAGE, corner, VMIN);
      expect(size.w / size.h).toBeCloseTo(aspect, 1);
      const card = cardBox(size);
      expect(intersects(card, corner), `card ${aspect}`).toBe(false);
      expect(intersects(captionBox(card), corner), `caption ${aspect}`).toBe(false);
    }
  });

  it('a portrait photo keeps its full size next to a corner', () => {
    expect(slideSize(0.75, STAGE, CORNERS['bottom-right']!, VMIN)).toEqual({ w: 633, h: 843 });
  });
});

describe('caption age', () => {
  afterEach(() => vi.useRealTimers());

  it('counts on while the photo is shown', () => {
    vi.useFakeTimers();
    const now = new Date('2026-07-04T20:00:00Z').getTime();
    vi.setSystemTime(now);
    const stage = document.createElement('div');
    const photo = { ...wallPhoto(1), taken_at: new Date(now - 3 * 60_000).toISOString() };
    stage.append(buildSlide(stage, photo, new Image(), { skewMs: 0 }));
    const ago = () => stage.querySelector('.wall-caption-ago')?.textContent;
    expect(ago()).toBe('vor 3 Min.');
    refreshAges(stage, 0, now + 2 * 60_000);
    expect(ago()).toBe('vor 5 Min.');
    // a TV clock 10 minutes ahead of the server
    refreshAges(stage, 10 * 60_000, now + 12 * 60_000);
    expect(ago()).toBe('vor 5 Min.');
  });
});
