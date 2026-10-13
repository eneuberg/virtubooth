/**
 * Capture geometry. OWNER: wave 2 "AC". The saved photo is exactly 1080×1440 and the
 * preview shows exactly what is saved (WYSIWYG, architecture.md §4, risk 4–5).
 */

export const PHOTO_W = 1080;
export const PHOTO_H = 1440;

/** A crop of the video frame, in fractions of its width/height (0…1). */
export interface CropRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** The centred 3:4 crop of a vw×vh video frame (port of renderer.js coverCrop). */
export function coverCrop(vw: number, vh: number): CropRect {
  void vw;
  void vh;
  throw new Error('TODO(wave 2, AC): sdk/camera/capture coverCrop');
}

/** Whether the preview and the saved photo are mirrored (front camera only, never the overlay). */
export function isMirrored(facing: 'user' | 'environment'): boolean {
  void facing;
  throw new Error('TODO(wave 2, AC): sdk/camera/capture isMirrored');
}
