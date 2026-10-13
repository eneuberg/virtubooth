/**
 * The standard poster (no template): A4 in the Kontaktbogen style. White paper, black
 * film strips with sprocket holes and edge printing at the top and bottom, the event
 * name, the QR code in a framed square circled with the grease pencil (the light
 * table's "this one"), a call to action, and the code's name bottom right in the film
 * strip. Print-friendly: ink only where it matters.
 */
import {
  closePath,
  LineCapStyle,
  LineJoinStyle,
  lineTo,
  moveTo,
  popGraphicsState,
  pushGraphicsState,
  setLineCap,
  setLineJoin,
  setLineWidth,
  setStrokingRgbColor,
  StandardFonts,
  stroke,
  type PDFDocument,
  type PDFFont,
  type PDFOperator,
  type PDFPage,
} from '@cantoo/pdf-lib';
import { CAP_HEIGHT, COLORS, describe, drawCentred, drawQr, fitText, LABEL_MARGIN, LABEL_SIZE } from './draw';
import { A4, mm } from './geometry';
import { qrMatrix } from './qr';
import { toWinAnsi } from './text';
import type { CodePrintInput } from './types';

export const SUBLINE = 'Fotos machen und mitfeiern';
export const CTA = 'Handy-Kamera drauf halten und los!';

const STRIP = mm(16);
const HOLE = { width: mm(2.6), height: mm(3.6), pitch: mm(5.5), edge: mm(2) };
const EDGE_TEXT = 8;
/** Courier's cap height per point (AFM). */
const COURIER_CAP = 0.562;
/** from the outer page edge to the edge printing's baseline */
const EDGE_BASELINE = mm(10.6);
const QR_SIDE = mm(120);
/** the grease-pencil ellipse's half axes around the 120 mm square */
const RING = { a: mm(94), b: mm(85) };

interface Fonts {
  regular: PDFFont;
  bold: PDFFont;
  edge: PDFFont;
}

/** One row of rounded sprocket holes across the page, their tops at `top`. */
function drawHoles(page: PDFPage, top: number): void {
  const { width } = page.getSize();
  const count = Math.floor((width - HOLE.width) / HOLE.pitch) + 1;
  const start = (width - (count - 1) * HOLE.pitch - HOLE.width) / 2;
  for (let i = 0; i < count; i++) {
    page.drawRectangle({
      x: start + i * HOLE.pitch,
      y: top - HOLE.height,
      width: HOLE.width,
      height: HOLE.height,
      rx: mm(0.6),
      ry: mm(0.6),
      color: COLORS.papier,
    });
  }
}

/** "2  2A  3  3A …" from the code's number. */
function frameNumbers(first: number, count: number): string[] {
  const out: string[] = [];
  for (let i = 0; out.length < count; i++) {
    const n = first + Math.floor(i / 2);
    out.push(i % 2 === 0 ? String(n) : `${n}A`);
  }
  return out;
}

/**
 * Edge printing from `x` to `maxX` at `baseline`: an optional lead text, then frame
 * numbers on a fixed pitch. Returns the number of frame numbers printed.
 */
function drawEdgePrint(
  page: PDFPage,
  font: PDFFont,
  baseline: number,
  x: number,
  maxX: number,
  lead: string,
  firstFrame: number,
): number {
  let cursor = x;
  const gap = mm(6);
  if (lead) {
    const leadWidth = font.widthOfTextAtSize(lead, EDGE_TEXT);
    if (cursor + leadWidth <= maxX) {
      page.drawText(lead, { x: cursor, y: baseline, size: EDGE_TEXT, font, color: COLORS.safelight });
      cursor += leadWidth + gap;
    }
  }
  const pitch = mm(19);
  const frames = frameNumbers(firstFrame, 64);
  let printed = 0;
  for (const frame of frames) {
    const width = font.widthOfTextAtSize(frame, EDGE_TEXT);
    if (cursor + width > maxX) break;
    page.drawText(frame, { x: cursor, y: baseline, size: EDGE_TEXT, font, color: COLORS.safelight });
    printed += 1;
    cursor += Math.max(pitch / 2, width + gap);
  }
  return printed;
}

function drawFilmStrips(page: PDFPage, fonts: Fonts, input: CodePrintInput): void {
  const { width, height } = page.getSize();
  // the strips
  page.drawRectangle({ x: 0, y: height - STRIP, width, height: STRIP, color: COLORS.black });
  page.drawRectangle({ x: 0, y: 0, width, height: STRIP, color: COLORS.black });
  // holes along the outer edges
  drawHoles(page, height - HOLE.edge);
  drawHoles(page, HOLE.edge + HOLE.height);

  const event = toWinAnsi(input.eventName).toUpperCase();
  const first = Math.max(0, Math.trunc(input.number));
  const left = mm(8);
  const right = width - mm(8);
  const topBaseline = height - EDGE_BASELINE;
  const printed = drawEdgePrint(page, fonts.edge, topBaseline, left, right, event, first);

  // bottom: the label in Papier at the right, frame numbers up to it
  const name = toWinAnsi(input.name);
  const baseline = EDGE_BASELINE - COURIER_CAP * EDGE_TEXT;
  let maxX = right;
  if (name) {
    const nameWidth = fonts.regular.widthOfTextAtSize(name, LABEL_SIZE);
    const x = width - LABEL_MARGIN - nameWidth;
    page.drawText(name, { x, y: baseline, size: LABEL_SIZE, font: fonts.regular, color: COLORS.papier });
    maxX = x - mm(8);
  }
  drawEdgePrint(page, fonts.edge, baseline, left, maxX, '', first + Math.ceil(printed / 2));
}

/** A hand-drawn loop: an ellipse that wobbles a little and overshoots its start. */
function ringPath(
  cx: number,
  cy: number,
  a: number,
  b: number,
  tilt: number,
  start: number,
  sweep: number,
  wobble: number,
  phase: number,
): PDFOperator[] {
  const steps = 160;
  const ops: PDFOperator[] = [];
  const cos = Math.cos(tilt);
  const sin = Math.sin(tilt);
  for (let i = 0; i <= steps; i++) {
    const t = start + (sweep * i) / steps;
    // grows slowly as the pencil goes round, so the end passes outside the start
    const r = 1 + wobble * Math.sin(3 * t + phase) + 0.6 * wobble * Math.sin(5 * t) + 0.018 * (i / steps);
    const ex = a * r * Math.cos(t);
    const ey = b * r * Math.sin(t);
    const x = Math.round((cx + ex * cos - ey * sin) * 100) / 100;
    const y = Math.round((cy + ex * sin + ey * cos) * 100) / 100;
    ops.push(i === 0 ? moveTo(x, y) : lineTo(x, y));
  }
  return ops;
}

function drawGreasePencil(page: PDFPage, cx: number, cy: number): void {
  const { red, green, blue } = { red: 198 / 255, green: 42 / 255, blue: 34 / 255 };
  page.pushOperators(
    pushGraphicsState(),
    setStrokingRgbColor(red, green, blue),
    setLineCap(LineCapStyle.Round),
    setLineJoin(LineJoinStyle.Round),
    setLineWidth(2.6),
    ...ringPath(cx, cy, RING.a, RING.b, (-4 * Math.PI) / 180, 0.35, 2 * Math.PI + 0.42, 0.011, 0.8),
    stroke(),
    // the second, thinner pass over part of the loop: a waxy double line
    setLineWidth(1.3),
    ...ringPath(cx, cy, RING.a * 1.012, RING.b * 1.006, (-2.6 * Math.PI) / 180, 2.2, 3.3, 0.009, 2.1),
    stroke(),
    popGraphicsState(),
  );
}

/** The thin frame around the white QR square. */
function drawFrame(page: PDFPage, x: number, y: number, side: number): void {
  const { red, green, blue } = { red: 22 / 255, green: 32 / 255, blue: 58 / 255 };
  page.pushOperators(
    pushGraphicsState(),
    setStrokingRgbColor(red, green, blue),
    setLineWidth(0.75),
    moveTo(x, y),
    lineTo(x + side, y),
    lineTo(x + side, y + side),
    lineTo(x, y + side),
    closePath(),
    stroke(),
    popGraphicsState(),
  );
}

/** Draw the standard poster on a new A4 page of `doc`. */
export async function drawStandardPoster(doc: PDFDocument, input: CodePrintInput): Promise<PDFPage> {
  const fonts: Fonts = {
    regular: await doc.embedFont(StandardFonts.Helvetica),
    bold: await doc.embedFont(StandardFonts.HelveticaBold),
    edge: await doc.embedFont(StandardFonts.CourierBold),
  };
  const page = doc.addPage([A4.width, A4.height]);
  const { width, height } = page.getSize();
  drawFilmStrips(page, fonts, input);

  const textWidth = width - 2 * mm(18);
  const event = toWinAnsi(input.eventName) || 'Party';
  const head = fitText(fonts.bold, event, textWidth, 54, 28, 2);
  const headLine = head.size * 1.08;
  const sub = fitText(fonts.regular, toWinAnsi(input.subtitle ?? '') || SUBLINE, textWidth, 16, 16, 2);
  const subLine = 16 * 1.3;
  const ctaSize = 20;

  // heights of the blocks (cap top to the lowest baseline), then the free space around them
  const headH = CAP_HEIGHT * head.size + (head.lines.length - 1) * headLine;
  const subH = CAP_HEIGHT * 16 + (sub.lines.length - 1) * subLine;
  const ringH = 2 * RING.b * 1.04;
  const gaps = { head: mm(6), sub: mm(9), ring: mm(7) };
  const used = headH + gaps.head + subH + gaps.sub + ringH + gaps.ring + CAP_HEIGHT * ctaSize;
  const free = Math.max(0, height - 2 * STRIP - used);
  let top = height - STRIP - free * 0.42;

  drawCentred(
    page,
    fonts.bold,
    head.lines,
    head.size,
    width / 2,
    top - CAP_HEIGHT * head.size,
    headLine,
    COLORS.negativ,
  );
  top -= headH + gaps.head;
  drawCentred(
    page,
    fonts.regular,
    sub.lines,
    16,
    width / 2,
    top - CAP_HEIGHT * 16,
    subLine,
    COLORS.negativMuted,
  );
  top -= subH + gaps.sub;

  const cy = top - ringH / 2;
  const square = { x: (width - QR_SIDE) / 2, y: cy - QR_SIDE / 2, width: QR_SIDE, height: QR_SIDE };
  drawQr(page, qrMatrix(input.url), square, 4);
  drawFrame(page, square.x, square.y, QR_SIDE);
  drawGreasePencil(page, width / 2, cy);
  top -= ringH + gaps.ring;

  drawCentred(page, fonts.bold, [CTA], ctaSize, width / 2, top - CAP_HEIGHT * ctaSize, 0, COLORS.negativ);
  describe(doc, input, 'Plakat');
  return page;
}
