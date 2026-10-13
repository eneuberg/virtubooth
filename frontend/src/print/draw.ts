/**
 * Drawing helpers shared by the PDFs: colours, the QR code as vector rectangles,
 * the label in the bottom right corner and text that fits a width.
 */
import {
  type Color,
  fill,
  popGraphicsState,
  pushGraphicsState,
  rectangle,
  rgb,
  setFillingRgbColor,
  type PDFDocument,
  type PDFFont,
  type PDFPage,
} from '@cantoo/pdf-lib';
import { mm, qrPlacement, type Box } from './geometry';
import { darkRuns } from './qr';
import { toWinAnsi } from './text';
import type { CodePrintInput } from './types';

function hex(value: string): Color {
  const n = Number.parseInt(value.slice(1), 16);
  return rgb(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}

/** Kontaktbogen tokens (docs/overhaul/design/DESIGN.md). */
export const COLORS = {
  negativ: hex('#16203a'),
  negativMuted: hex('#5a6272'),
  papier: hex('#fbefe9'),
  safelight: hex('#ffa630'),
  fettstift: hex('#c62a22'),
  white: rgb(1, 1, 1),
  black: rgb(0, 0, 0),
} as const;

/** The label: 9 pt, 8 mm from the bottom right corner. */
export const LABEL_SIZE = 9;
export const LABEL_MARGIN = mm(8);
/** Helvetica's cap height and descender (AFM), per point of size. */
export const CAP_HEIGHT = 0.718;
export const DESCENDER = 0.207;

const round = (v: number) => Math.round(v * 1000) / 1000;

/**
 * The QR code in `square`: a white square, the dark modules as merged rectangles in
 * one black fill, `quiet` modules of white margin inside the square.
 */
export function drawQr(page: PDFPage, matrix: boolean[][], square: Box, quiet: number): void {
  page.drawRectangle({ ...square, color: COLORS.white });
  const { module, left, top } = qrPlacement(square, matrix.length, quiet);
  const ops = [pushGraphicsState(), setFillingRgbColor(0, 0, 0)];
  for (const run of darkRuns(matrix)) {
    ops.push(
      rectangle(
        round(left + run.x * module),
        round(top - (run.y + 1) * module),
        round(run.length * module),
        round(module),
      ),
    );
  }
  ops.push(fill(), popGraphicsState());
  page.pushOperators(...ops);
}

/**
 * The code's name ("Gorilla 2") small in the bottom right corner, on a white pill so
 * it reads on any background. Returns the text's box (nothing when nothing printable).
 */
export function drawLabel(page: PDFPage, font: PDFFont, name: string): Box | null {
  const text = toWinAnsi(name);
  if (!text) return null;
  const { width: pageWidth } = page.getSize();
  const textWidth = font.widthOfTextAtSize(text, LABEL_SIZE);
  const padX = mm(2.2);
  const padY = mm(1.4);
  const capHeight = CAP_HEIGHT * LABEL_SIZE;
  const pill = {
    width: textWidth + 2 * padX,
    height: capHeight + 2 * padY,
    x: pageWidth - LABEL_MARGIN - textWidth - 2 * padX,
    y: LABEL_MARGIN,
  };
  page.drawRectangle({ ...pill, rx: pill.height / 2, ry: pill.height / 2, color: COLORS.white });
  page.drawText(text, { x: pill.x + padX, y: pill.y + padY, size: LABEL_SIZE, font, color: COLORS.negativ });
  return { x: pill.x + padX, y: pill.y + padY, width: textWidth, height: capHeight };
}

/** Lines of `text` (already WinAnsi) that fit `maxWidth` at `size`; long words break. */
export function wrap(font: PDFFont, text: string, size: number, maxWidth: number): string[] {
  const fits = (s: string) => font.widthOfTextAtSize(s, size) <= maxWidth;
  const lines: string[] = [];
  let line = '';
  for (const word of text.split(' ').filter(Boolean)) {
    const candidate = line ? `${line} ${word}` : word;
    if (fits(candidate)) {
      line = candidate;
      continue;
    }
    if (line) lines.push(line);
    line = '';
    if (fits(word)) {
      line = word;
      continue;
    }
    for (const ch of word) {
      if (line && !fits(line + ch)) {
        lines.push(line);
        line = '';
      }
      line += ch;
    }
  }
  if (line) lines.push(line);
  return lines;
}

/** Shorten the line with "…" until it fits. */
function ellipsize(font: PDFFont, line: string, size: number, maxWidth: number): string {
  let s = line;
  while (s.length > 1 && font.widthOfTextAtSize(`${s}…`, size) > maxWidth) s = s.slice(0, -1).trimEnd();
  return `${s}…`;
}

export interface FittedText {
  size: number;
  lines: string[];
}

/**
 * The biggest size from `maxSize` down to `minSize` (1 pt steps) at which `text` takes
 * at most `maxLines` lines of `maxWidth`. Still too long at `minSize`: the last line
 * ends with "…".
 */
export function fitText(
  font: PDFFont,
  text: string,
  maxWidth: number,
  maxSize: number,
  minSize: number,
  maxLines: number,
): FittedText {
  for (let size = maxSize; size >= minSize; size -= 1) {
    const lines = wrap(font, text, size, maxWidth);
    if (lines.length <= maxLines) return { size, lines };
  }
  const lines = wrap(font, text, minSize, maxWidth);
  const kept = lines.slice(0, maxLines);
  const last = kept.length - 1;
  if (lines.length > maxLines && last >= 0) {
    kept[last] = ellipsize(font, kept[last] ?? '', minSize, maxWidth);
  }
  return { size: minSize, lines: kept };
}

/** Lines centred on `centerX`, the first baseline at `baseline`, going down. */
export function drawCentred(
  page: PDFPage,
  font: PDFFont,
  lines: string[],
  size: number,
  centerX: number,
  baseline: number,
  lineHeight: number,
  color: Color,
): void {
  lines.forEach((line, i) => {
    const width = font.widthOfTextAtSize(line, size);
    page.drawText(line, { x: centerX - width / 2, y: baseline - i * lineHeight, size, font, color });
  });
}

/** Title, author and producer of a new PDF. */
export function describe(doc: PDFDocument, input: CodePrintInput, what: string): void {
  const event = input.eventName.trim();
  doc.setTitle([what, input.name.trim(), event].filter(Boolean).join(' – '));
  doc.setCreator('virtubooth');
  doc.setProducer('virtubooth');
  doc.setLanguage('de-DE');
}
