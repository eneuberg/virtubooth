/**
 * Capture geometry. OWNER: wave 2 "AC". The saved photo is exactly 1080×1440 and the
 * preview shows exactly what is saved (WYSIWYG, architecture.md §4, risk 4–5).
 *
 * Pure functions only (unit-tested): the renderer, the camera session and the tests
 * all use the same numbers. Ported from renderer.js `coverCrop` and camera.js
 * `captureFrame` / facing inference.
 */

export const PHOTO_W = 1080;
export const PHOTO_H = 1440;
/** width / height of the photo (3:4 portrait) */
export const PHOTO_ASPECT = PHOTO_W / PHOTO_H;

export type Facing = 'user' | 'environment';

/** A crop of the video frame, in fractions of its width/height (0…1). */
export interface CropRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * The centred 3:4 crop of a vw×vh video frame, in texture coordinates (renderer.js
 * coverCrop). A landscape 4:3 sensor keeps its full height; a portrait stream keeps
 * its full width. Unknown sizes give the whole frame.
 */
export function coverCrop(vw: number, vh: number, aspect: number = PHOTO_ASPECT): CropRect {
  if (!(vw > 0) || !(vh > 0)) return { x: 0, y: 0, w: 1, h: 1 };
  const a = vw / vh;
  if (a > aspect) {
    const w = aspect / a;
    return { x: (1 - w) / 2, y: 0, w, h: 1 };
  }
  const h = a / aspect;
  return { x: 0, y: (1 - h) / 2, w: 1, h };
}

/** The same crop in video pixels, for `drawImage(video, sx, sy, sw, sh, …)` (camera.js captureFrame). */
export function cropPixels(
  vw: number,
  vh: number,
  tw: number = PHOTO_W,
  th: number = PHOTO_H,
): { sx: number; sy: number; sw: number; sh: number } {
  const scale = Math.max(tw / vw, th / vh);
  const sw = tw / scale;
  const sh = th / scale;
  return { sx: (vw - sw) / 2, sy: (vh - sh) / 2, sw, sh };
}

/**
 * Whether the preview and the saved photo are mirrored: the front camera only (like
 * every video call and the phone's own selfie preview), never the back camera.
 * Overlays (party frame, VHS text, the beer outline) are never mirrored.
 */
export function isMirrored(facing: Facing): boolean {
  return facing === 'user';
}

/**
 * Which way the running camera points (camera.js start()):
 * - what the track reports, when it says `user` or `environment`;
 * - otherwise a device with exactly one camera is a laptop or PC webcam, which faces
 *   the guest (mirrored like a video call);
 * - otherwise what was asked for.
 */
export function inferFacing(reported: unknown, cameras: number | null, requested: Facing): Facing {
  if (reported === 'user' || reported === 'environment') return reported;
  if (cameras === 1) return 'user';
  return requested;
}

/** A device can switch cameras unless it is known to have exactly one (unknown counts as yes). */
export function canSwitchCamera(cameras: number | null): boolean {
  return cameras !== 1;
}

/** The other camera. */
export function otherFacing(facing: Facing): Facing {
  return facing === 'user' ? 'environment' : 'user';
}

/**
 * The getUserMedia constraints, exactly as before (the e2e tests assert the shapes):
 * a wish for the facing and an ideal 4:3 size; on OverconstrainedError the retry asks
 * only for the facing.
 */
export function cameraConstraints(
  facing: Facing,
  width: number,
  height: number,
): MediaStreamConstraints & { video: MediaTrackConstraints } {
  return {
    audio: false,
    video: { facingMode: { ideal: facing }, width: { ideal: width }, height: { ideal: height } },
  };
}

export function fallbackConstraints(facing: Facing): MediaStreamConstraints {
  return { audio: false, video: { facingMode: facing } };
}

/** Requested stream sizes: both 4:3, so the 3:4 crop keeps the full sensor height. */
export const STREAM_SIZE = {
  /** Beer Cam: the back camera */
  beer: { width: 1920, height: 1440 },
  /** Fotobox: the selfie camera */
  booth: { width: 1440, height: 1080 },
} as const;
