import {
  decodePDFRawStream,
  degrees,
  PDFArray,
  PDFDocument,
  type PDFPage,
  PDFRawStream,
  PDFStream,
  rgb,
} from '@cantoo/pdf-lib';
import { describe, expect, it } from 'vitest';
import { A4, mm } from './geometry';
import { bigQrPdf, exportFileName, posterPdf, qrPng } from './index';
import type { CodePrintInput } from './types';

const CODE: CodePrintInput = {
  url: `https://party.example.com/x/booth/?t=${'k'.repeat(64)}`,
  number: 2,
  name: 'Gorilla 2',
  eventName: 'Lenas 30. Geburtstag 🎉',
  subtitle: null,
};

/** The page's content streams, decoded (pdf-lib writes them compressed). */
function contents(page: PDFPage): string {
  const node = page.node.Contents();
  const streams =
    node instanceof PDFArray ? node.asArray().map((ref) => page.doc.context.lookup(ref)) : [node];
  const decoder = new TextDecoder('latin1');
  return streams
    .map((stream) => {
      if (stream instanceof PDFRawStream) return decoder.decode(decodePDFRawStream(stream).decode());
      if (stream instanceof PDFStream) return decoder.decode(stream.getContents());
      return '';
    })
    .join('\n');
}

/** How pdf-lib writes a standard-font string: WinAnsi bytes in hex. */
function hexText(text: string): string {
  const cp1252: Record<string, number> = { '„': 0x84, '“': 0x93, '–': 0x96 };
  return Array.from(text, (ch) =>
    (cp1252[ch] ?? ch.charCodeAt(0)).toString(16).toUpperCase().padStart(2, '0'),
  ).join('');
}

/** A template like the host's: several pages of different sizes, coloured, with a card. */
async function template(): Promise<ArrayBuffer> {
  const doc = await PDFDocument.create();
  const sizes: Array<[number, number]> = [
    [A4.width, A4.height],
    [mm(148), mm(210)], // A5
    [500, 500],
  ];
  for (const [w, h] of sizes) {
    const page = doc.addPage([w, h]);
    page.drawRectangle({ x: 0, y: 0, width: w, height: h, color: rgb(0.8, 0.2, 0.9) });
    page.drawRectangle({ x: w * 0.25, y: h * 0.2, width: w * 0.5, height: w * 0.5, color: rgb(1, 1, 1) });
  }
  const bytes = await doc.save();
  return bytes.slice().buffer;
}

async function onePage(bytes: Uint8Array): Promise<PDFPage> {
  expect(new TextDecoder().decode(bytes.slice(0, 5))).toBe('%PDF-');
  const doc = await PDFDocument.load(bytes);
  expect(doc.getPageCount()).toBe(1);
  const page = doc.getPage(0);
  return page;
}

describe('posterPdf', () => {
  it('stamps the code on the chosen template page, keeping its size', async () => {
    const rect = { x: 0.25, y: 0.3, w: 0.5, h: (0.5 * mm(148)) / mm(210) };
    const bytes = await posterPdf(CODE, { pdf: await template(), page: 1, rect });
    const page = await onePage(bytes);
    const { width, height } = page.getSize();
    expect(width).toBeCloseTo(mm(148), 2);
    expect(height).toBeCloseTo(mm(210), 2);
    const text = contents(page);
    // the template page is drawn as a form XObject, then the QR (one fill) and the label
    expect(text).toMatch(/\/EmbeddedPdfPage-\d+ Do/);
    expect(text).toContain(`<${hexText('Gorilla 2')}> Tj`);
    // the label sits 8 mm from the bottom right corner (its pill's right edge)
    expect(text).not.toContain(CODE.url);
  });

  it('takes the template page as given (the first page too)', async () => {
    const bytes = await posterPdf(CODE, {
      pdf: await template(),
      page: 0,
      rect: { x: 0.1, y: 0.1, w: 0.3, h: (0.3 * A4.width) / A4.height },
    });
    const page = await onePage(bytes);
    expect(page.getSize().width).toBeCloseTo(A4.width, 2);
    expect(page.getSize().height).toBeCloseTo(A4.height, 2);
  });

  it('turns rotated pages upright, as the editor showed them', async () => {
    const doc = await PDFDocument.create();
    const page = doc.addPage([400, 600]);
    page.drawRectangle({ x: 0, y: 0, width: 100, height: 100, color: rgb(1, 0, 0) });
    page.setRotation(degrees(90));
    doc.addPage([300, 300]); // blank: nothing to embed
    const bytes = await doc.save();
    const out = await onePage(
      await posterPdf(CODE, { pdf: bytes.slice().buffer, page: 0, rect: { x: 0.1, y: 0.1, w: 0.2, h: 0.3 } }),
    );
    // displayed landscape: 600 × 400, no /Rotate left on the poster
    expect(out.getSize()).toEqual({ width: 600, height: 400 });
    expect(out.getRotation().angle).toBe(0);
    const blank = await onePage(
      await posterPdf(CODE, { pdf: bytes.slice().buffer, page: 1, rect: { x: 0, y: 0, w: 0.5, h: 0.5 } }),
    );
    expect(blank.getSize()).toEqual({ width: 300, height: 300 });
  });

  it('refuses a page the template does not have, and junk', async () => {
    await expect(
      posterPdf(CODE, { pdf: await template(), page: 5, rect: { x: 0, y: 0, w: 0.5, h: 0.5 } }),
    ).rejects.toThrow('Diese Seite gibt es in der Vorlage nicht mehr.');
    const junk = new TextEncoder().encode('%PDF-1.7 nothing here').buffer;
    await expect(
      posterPdf(CODE, { pdf: junk, page: 0, rect: { x: 0, y: 0, w: 0.5, h: 0.5 } }),
    ).rejects.toThrow(/Vorlage lässt sich nicht verarbeiten/);
  });

  it('is the standard poster without a template: A4, film strips, the label', async () => {
    const page = await onePage(await posterPdf({ ...CODE, subtitle: 'Fotobox' }));
    expect(page.getSize().width).toBeCloseTo(A4.width, 2);
    expect(page.getSize().height).toBeCloseTo(A4.height, 2);
    const text = contents(page);
    expect(text).toContain(`<${hexText('Gorilla 2')}> Tj`);
    expect(text).toContain(`<${hexText('Fotobox')}> Tj`);
    expect(text).toContain(`<${hexText('Handy-Kamera drauf halten und los!')}> Tj`);
    // event name without the emoji, in capitals on the film edge
    expect(text).toContain(`<${hexText('LENAS 30. GEBURTSTAG')}> Tj`);
    expect(text).toContain(`<${hexText('2A')}> Tj`);
  });

  it('uses the default subline and fits very long event names', async () => {
    const long = {
      ...CODE,
      eventName:
        'Die ganz besonders lange Geburtstagsfeier von Lena und allen ihren Freundinnen und Freunden 2026',
    };
    const text = contents(await onePage(await posterPdf(long)));
    expect(text).toContain(`<${hexText('Fotos machen und mitfeiern')}> Tj`);
    expect(text).toMatch(/\/Helvetica-Bold-\d+ 28 Tf/); // shrunk to the minimum, with an ellipsis
    expect(text).toContain('85> Tj'); // … (0x85) ends the second line
  });
});

describe('bigQrPdf and qrPng', () => {
  it('is one A4 page with the label', async () => {
    const page = await onePage(await bigQrPdf(CODE));
    expect(page.getSize().width).toBeCloseTo(A4.width, 2);
    expect(page.getSize().height).toBeCloseTo(A4.height, 2);
    expect(contents(page)).toContain(`<${hexText('Gorilla 2')}> Tj`);
  });

  it('gives a PNG blob and file names', async () => {
    const blob = await qrPng(CODE);
    expect(blob.type).toBe('image/png');
    expect(blob.size).toBeGreaterThan(1000);
    expect(exportFileName(CODE, 'poster')).toBe('plakat-02-gorilla.pdf');
  });
});
