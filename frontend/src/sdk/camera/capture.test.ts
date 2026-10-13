import { describe, expect, it } from 'vitest';
import {
  cameraConstraints,
  canSwitchCamera,
  coverCrop,
  cropPixels,
  fallbackConstraints,
  inferFacing,
  isMirrored,
  otherFacing,
  PHOTO_H,
  PHOTO_W,
  STREAM_SIZE,
} from './capture';

describe('the photo', () => {
  it('is exactly 1080×1440 (the server refuses anything else)', () => {
    expect([PHOTO_W, PHOTO_H]).toEqual([1080, 1440]);
  });
});

describe('coverCrop: the centred 3:4 region of the video (renderer.js)', () => {
  it.each([
    // [video w, video h, x, y, w, h]
    ['4:3 back camera (Beer Cam)', 1920, 1440, 0.21875, 0, 0.5625, 1],
    ['4:3 selfie camera (Fotobox)', 1440, 1080, 0.21875, 0, 0.5625, 1],
    ['16:9 laptop webcam', 1280, 720, 0.2890625, 0, 0.421875, 1],
    ['portrait 9:16 stream', 720, 1280, 0, 0.125, 1, 0.75],
    ['exactly 3:4', 1080, 1440, 0, 0, 1, 1],
    ['unknown size', 0, 0, 0, 0, 1, 1],
  ])('%s', (_name, vw, vh, x, y, w, h) => {
    const crop = coverCrop(vw, vh);
    expect(crop.x).toBeCloseTo(x, 6);
    expect(crop.y).toBeCloseTo(y, 6);
    expect(crop.w).toBeCloseTo(w, 6);
    expect(crop.h).toBeCloseTo(h, 6);
    // always 3:4 in pixels (unknown sizes: the whole frame)
    const aspect = vw && vh ? (crop.w * vw) / (crop.h * vh) : 0.75;
    expect(aspect).toBeCloseTo(0.75, 6);
  });
});

describe('cropPixels: captureFrame math in video pixels (camera.js)', () => {
  it('keeps x 370…910 of the 1280×720 test card (the desktop e2e card)', () => {
    expect(cropPixels(1280, 720)).toEqual({ sx: 370, sy: 0, sw: 540, sh: 720 });
  });

  it('keeps the full sensor height of a 4:3 stream', () => {
    expect(cropPixels(1920, 1440)).toEqual({ sx: 420, sy: 0, sw: 1080, sh: 1440 });
  });

  it('agrees with coverCrop', () => {
    for (const [vw, vh] of [
      [1280, 720],
      [1440, 1080],
      [720, 1280],
      [640, 480],
    ] as const) {
      const px = cropPixels(vw, vh);
      const c = coverCrop(vw, vh);
      expect(px.sx).toBeCloseTo(c.x * vw, 6);
      expect(px.sy).toBeCloseTo(c.y * vh, 6);
      expect(px.sw).toBeCloseTo(c.w * vw, 6);
      expect(px.sh).toBeCloseTo(c.h * vh, 6);
    }
  });
});

describe('mirroring rules', () => {
  it('mirrors the front camera only (preview and photo alike)', () => {
    expect(isMirrored('user')).toBe(true);
    expect(isMirrored('environment')).toBe(false);
  });

  it.each([
    // [reported facingMode, cameras, requested, result]
    ['user', 2, 'environment', 'user'],
    ['environment', 2, 'user', 'environment'],
    [undefined, 1, 'environment', 'user'], // a laptop webcam faces the guest
    ['', 1, 'environment', 'user'],
    [undefined, 2, 'environment', 'environment'],
    [undefined, null, 'environment', 'environment'],
    ['left', null, 'user', 'user'],
  ] as const)('track says %s with %s cameras, asked %s → %s', (reported, cameras, requested, result) => {
    expect(inferFacing(reported, cameras, requested)).toBe(result);
  });

  it('can switch unless there is exactly one camera', () => {
    expect(canSwitchCamera(1)).toBe(false);
    expect(canSwitchCamera(2)).toBe(true);
    expect(canSwitchCamera(null)).toBe(true);
    expect(otherFacing('user')).toBe('environment');
    expect(otherFacing('environment')).toBe('user');
  });
});

describe('getUserMedia constraints (asserted by the e2e tests)', () => {
  it('asks for a facing wish and an ideal 4:3 size', () => {
    expect(cameraConstraints('environment', STREAM_SIZE.beer.width, STREAM_SIZE.beer.height)).toEqual({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1440 } },
    });
    expect(cameraConstraints('user', STREAM_SIZE.booth.width, STREAM_SIZE.booth.height).video).toEqual({
      facingMode: { ideal: 'user' },
      width: { ideal: 1440 },
      height: { ideal: 1080 },
    });
  });

  it('retries with the bare facing', () => {
    expect(fallbackConstraints('user')).toEqual({ audio: false, video: { facingMode: 'user' } });
  });
});
