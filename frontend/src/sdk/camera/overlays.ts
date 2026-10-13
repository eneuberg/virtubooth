/**
 * Drawn overlays (party frame, emoji props, VHS date, pixel text, beer outlines).
 * OWNER: wave 2 "AC". Port of booth/static/overlays.js and beer/static/shapes.js.
 * Overlays are drawn into the captured frame unmirrored, in 1080×1440 coordinates.
 */

export interface OverlayInfo {
  width: number;
  height: number;
  date: Date;
  partyName: string;
}

/** Draws the overlay of `filterId` (if it has one) onto the canvas. */
export function drawOverlay(ctx: CanvasRenderingContext2D, filterId: string, info: OverlayInfo): void {
  void ctx;
  void filterId;
  void info;
  throw new Error('TODO(wave 2, AC): sdk/camera/overlays drawOverlay');
}
