/**
 * The printable PDFs (pdf-lib, standard fonts only): the big QR code on A4, and the
 * poster, either a page of the host's template with the QR code in the placed square
 * or the standard poster. Every PDF has one page and the code's name bottom right.
 */
import { degrees, PDFDocument, StandardFonts, type PDFPage } from '@cantoo/pdf-lib';
import { CAP_HEIGHT, COLORS, describe, drawCentred, drawLabel, drawQr, fitText } from './draw';
import { PrintError } from './errors';
import { A4, centredSquare, mm, placePage, relToPdf, type PageBox } from './geometry';
import { qrMatrix } from './qr';
import { drawStandardPoster } from './standardPoster';
import { toWinAnsi } from './text';
import type { CodePrintInput, PosterTemplateInput } from './types';

/** Shown when pdf-lib can't read the template (the editor's reader could). */
export const TEMPLATE_UNREADABLE =
  'Die Vorlage lässt sich nicht verarbeiten. Bitte die PDF neu exportieren (z. B. „Drucken als PDF“).';

const QR_SIDE_BIG = mm(170);

/** A4 with the code as big as fits nicely (≈ 170 mm with its 4-module margin). */
export async function bigQrPdf(input: CodePrintInput): Promise<Uint8Array> {
  const doc = await PDFDocument.create();
  const bold = await doc.embedFont(StandardFonts.HelveticaBold);
  const regular = await doc.embedFont(StandardFonts.Helvetica);
  const page = doc.addPage([A4.width, A4.height]);
  const { width, height } = page.getSize();

  const textWidth = width - 2 * mm(20);
  const head = fitText(bold, toWinAnsi(input.eventName) || 'Party', textWidth, 30, 18, 2);
  const headLine = head.size * 1.1;
  let top = height - mm(22);
  drawCentred(
    page,
    bold,
    head.lines,
    head.size,
    width / 2,
    top - CAP_HEIGHT * head.size,
    headLine,
    COLORS.negativ,
  );
  top -= CAP_HEIGHT * head.size + (head.lines.length - 1) * headLine;
  const subtitle = toWinAnsi(input.subtitle ?? '');
  if (subtitle) {
    const sub = fitText(regular, subtitle, textWidth, 14, 14, 1);
    top -= mm(4);
    drawCentred(page, regular, sub.lines, sub.size, width / 2, top - CAP_HEIGHT * 14, 0, COLORS.negativMuted);
    top -= CAP_HEIGHT * 14;
  }
  // the square in the middle of what is left above the label
  const bottom = mm(20);
  const cy = Math.min(height / 2, (top - mm(6) + bottom) / 2);
  const square = {
    x: (width - QR_SIDE_BIG) / 2,
    y: cy - QR_SIDE_BIG / 2,
    width: QR_SIDE_BIG,
    height: QR_SIDE_BIG,
  };
  drawQr(page, qrMatrix(input.url), square, 4);
  drawLabel(page, regular, input.name);
  describe(doc, input, 'QR-Code');
  return doc.save();
}

/** The template page's visible box: the crop box within the media box, as pdf.js shows it. */
function visibleBox(page: PDFPage): PageBox {
  const media = page.getMediaBox();
  const crop = page.getCropBox();
  const left = Math.max(Math.min(media.x, media.x + media.width), Math.min(crop.x, crop.x + crop.width));
  const bottom = Math.max(Math.min(media.y, media.y + media.height), Math.min(crop.y, crop.y + crop.height));
  const right = Math.min(Math.max(media.x, media.x + media.width), Math.max(crop.x, crop.x + crop.width));
  const top = Math.min(Math.max(media.y, media.y + media.height), Math.max(crop.y, crop.y + crop.height));
  // a crop box outside the media box: pdf.js falls back to the media box
  if (right <= left || top <= bottom) {
    return {
      left: Math.min(media.x, media.x + media.width),
      bottom: Math.min(media.y, media.y + media.height),
      right: Math.max(media.x, media.x + media.width),
      top: Math.max(media.y, media.y + media.height),
    };
  }
  return { left, bottom, right, top };
}

/** The template's page (an empty password opens files only "protected" against editing). */
async function templatePage(pdf: ArrayBuffer, index: number): Promise<PDFPage> {
  let pages: PDFPage[];
  try {
    const source = await PDFDocument.load(pdf, { password: '', updateMetadata: false });
    pages = source.getPages();
  } catch {
    throw new PrintError(TEMPLATE_UNREADABLE);
  }
  const page = pages[index];
  if (!page) throw new PrintError('Diese Seite gibt es in der Vorlage nicht mehr.');
  return page;
}

/** The template's page with the QR code in the placed square (2-module margin). */
async function templatePoster(input: CodePrintInput, template: PosterTemplateInput): Promise<Uint8Array> {
  const sourcePage = await templatePage(template.pdf, template.page);
  try {
    const box = visibleBox(sourcePage);
    const placement = placePage(box, sourcePage.getRotation().angle);
    const doc = await PDFDocument.create();
    const regular = await doc.embedFont(StandardFonts.Helvetica);
    const page = doc.addPage([placement.width, placement.height]);
    // a page without content (blank) has nothing to embed
    if (sourcePage.node.Contents()) {
      const embedded = await doc.embedPage(sourcePage, box);
      page.drawPage(embedded, { x: placement.x, y: placement.y, rotate: degrees(placement.rotate) });
    }
    const square = centredSquare(relToPdf(template.rect, placement.width, placement.height));
    drawQr(page, qrMatrix(input.url), square, 2);
    drawLabel(page, regular, input.name);
    describe(doc, input, 'Plakat');
    // the template's content is copied (and can fail) only here
    return await doc.save();
  } catch {
    throw new PrintError(TEMPLATE_UNREADABLE);
  }
}

/** One page: the template's page with the code, or the standard poster without a template. */
export async function posterPdf(
  input: CodePrintInput,
  template?: PosterTemplateInput | null,
): Promise<Uint8Array> {
  if (template) return templatePoster(input, template);
  const doc = await PDFDocument.create();
  // the standard poster prints the label in its bottom film strip
  await drawStandardPoster(doc, input);
  return doc.save();
}
