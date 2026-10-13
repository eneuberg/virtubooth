/**
 * Page geometry. PDF user space has its origin bottom left and counts in points
 * (1/72 inch); the editor's rectangles are relative (0..1) with the origin top left,
 * on the page as it is displayed (crop box, rotation applied, like pdf.js shows it).
 */
import type { RelRect } from './types';

export const PT_PER_MM = 72 / 25.4;

export function mm(value: number): number {
  return value * PT_PER_MM;
}

/** A4 portrait in points. */
export const A4 = { width: 595.28, height: 841.89 } as const;

/** A box in PDF points, origin bottom left. */
export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** A relative rectangle (origin top left) on a width × height page → PDF box. */
export function relToPdf(rect: RelRect, width: number, height: number): Box {
  return {
    x: rect.x * width,
    y: height - (rect.y + rect.h) * height,
    width: rect.w * width,
    height: rect.h * height,
  };
}

/** A PDF box on a width × height page → relative rectangle (origin top left). */
export function pdfToRel(box: Box, width: number, height: number): RelRect {
  return {
    x: box.x / width,
    y: (height - box.y - box.height) / height,
    w: box.width / width,
    h: box.height / height,
  };
}

/** The largest square inside `box`, centred (the saved field is square within 2 %). */
export function centredSquare(box: Box): Box {
  const side = Math.min(box.width, box.height);
  return {
    x: box.x + (box.width - side) / 2,
    y: box.y + (box.height - side) / 2,
    width: side,
    height: side,
  };
}

/** Where a QR code of `modules` modules sits in `square` with `quiet` modules of margin. */
export interface QrPlacement {
  /** side of one module, points */
  module: number;
  /** left edge of the first module column */
  left: number;
  /** top edge of the first module row (PDF y, so rows go down from here) */
  top: number;
}

export function qrPlacement(square: Box, modules: number, quiet: number): QrPlacement {
  const module = Math.min(square.width, square.height) / (modules + 2 * quiet);
  return {
    module,
    left: square.x + quiet * module,
    top: square.y + square.height - quiet * module,
  };
}

export type Rotation = 0 | 90 | 180 | 270;

/** A page's /Rotate as one of 0, 90, 180, 270 (PDF allows any multiple of 90). */
export function normalizeRotation(degrees: number): Rotation {
  const r = (((Math.round(degrees / 90) * 90) % 360) + 360) % 360;
  return r === 90 || r === 180 || r === 270 ? r : 0;
}

/** A page box in PDF points (left < right, bottom < top). */
export interface PageBox {
  left: number;
  bottom: number;
  right: number;
  top: number;
}

/**
 * How a template page lands on the poster: the poster page is the page as displayed
 * (`width` × `height`, rotation applied), and the embedded page (its box moved to the
 * origin) is drawn at (`x`, `y`) turned by `rotate` degrees (counter-clockwise, as
 * pdf-lib's drawPage takes it). /Rotate turns clockwise, hence the minus.
 */
export interface PagePlacement {
  width: number;
  height: number;
  x: number;
  y: number;
  rotate: number;
}

export function placePage(box: PageBox, rotation: number): PagePlacement {
  const w = box.right - box.left;
  const h = box.top - box.bottom;
  switch (normalizeRotation(rotation)) {
    case 90:
      return { width: h, height: w, x: 0, y: w, rotate: -90 };
    case 180:
      return { width: w, height: h, x: w, y: h, rotate: -180 };
    case 270:
      return { width: h, height: w, x: h, y: 0, rotate: -270 };
    default:
      return { width: w, height: h, x: 0, y: 0, rotate: 0 };
  }
}

/**
 * Where a point of the original page (PDF user space) ends up on the poster page,
 * as a top-left-origin position: the same as pdf.js's viewport at scale 1.
 */
export function placedPoint(box: PageBox, rotation: number, px: number, py: number): [number, number] {
  const p = placePage(box, rotation);
  const u = px - box.left;
  const v = py - box.bottom;
  const rad = (p.rotate * Math.PI) / 180;
  const cos = Math.round(Math.cos(rad));
  const sin = Math.round(Math.sin(rad));
  const x = p.x + cos * u - sin * v;
  const y = p.y + sin * u + cos * v;
  return [x, p.height - y];
}
