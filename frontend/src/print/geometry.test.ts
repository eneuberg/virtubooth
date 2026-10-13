// @vitest-environment node
// pdf.js (legacy build, as the admin loads it) runs here in Node to check that the
// editor's view of a page (pdf.js) and the export's (pdf-lib) agree.
import { degrees, PDFDocument } from '@cantoo/pdf-lib';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { describe, expect, it } from 'vitest';
import {
  A4,
  centredSquare,
  mm,
  normalizeRotation,
  pdfToRel,
  placedPoint,
  placePage,
  qrPlacement,
  relToPdf,
} from './geometry';

describe('relative and PDF coordinates', () => {
  it('flips the origin from top left to bottom left', () => {
    const box = relToPdf({ x: 0.1, y: 0.2, w: 0.3, h: 0.4 }, 500, 1000);
    expect(box.x).toBeCloseTo(50, 9);
    expect(box.y).toBeCloseTo(400, 9);
    expect(box.width).toBeCloseTo(150, 9);
    expect(box.height).toBeCloseTo(400, 9);
    // the top-left corner of the page is (0, height) in PDF space
    expect(relToPdf({ x: 0, y: 0, w: 0.1, h: 0.1 }, 500, 1000).y).toBe(900);
  });

  it('round-trips', () => {
    const rect = { x: 0.123, y: 0.456, w: 0.25, h: 0.177 };
    const back = pdfToRel(relToPdf(rect, A4.width, A4.height), A4.width, A4.height);
    for (const key of ['x', 'y', 'w', 'h'] as const) expect(back[key]).toBeCloseTo(rect[key], 10);
  });

  it('uses the centred square of a nearly square field', () => {
    expect(centredSquare({ x: 10, y: 20, width: 102, height: 100 })).toEqual({
      x: 11,
      y: 20,
      width: 100,
      height: 100,
    });
  });

  it('places the modules inside the quiet zone', () => {
    const p = qrPlacement({ x: 0, y: 0, width: 100, height: 100 }, 21, 2);
    expect(p.module).toBeCloseTo(4, 10);
    expect(p.left).toBeCloseTo(8, 10);
    expect(p.top).toBeCloseTo(92, 10);
    expect(mm(25.4)).toBeCloseTo(72, 10);
  });

  it('normalises /Rotate', () => {
    expect([0, 90, 180, 270, 360, -90, 450, -180].map(normalizeRotation)).toEqual([
      0, 90, 180, 270, 0, 270, 90, 180,
    ]);
  });
});

describe('template pages: pdf.js (editor) and pdf-lib (export) agree', () => {
  const cases = [
    { rotate: 0, media: [0, 0, 595, 842], crop: null },
    { rotate: 90, media: [0, 0, 595, 842], crop: null },
    { rotate: 180, media: [0, 0, 400, 300], crop: null },
    { rotate: 270, media: [0, 0, 400, 300], crop: null },
    // a crop box away from the origin, and a media box that does not start at 0
    { rotate: 0, media: [-20, 10, 600, 900], crop: [30, 40, 330, 640] },
    { rotate: 90, media: [100, 200, 700, 1000], crop: [150, 260, 550, 760] },
    { rotate: -90, media: [0, 0, 500, 700], crop: [50, 50, 450, 650] },
  ];

  it.each(cases)('rotate $rotate, media $media, crop $crop', async ({ rotate, media, crop }) => {
    const doc = await PDFDocument.create();
    const page = doc.addPage();
    const [mx0 = 0, my0 = 0, mx1 = 0, my1 = 0] = media;
    page.setMediaBox(mx0, my0, mx1 - mx0, my1 - my0);
    if (crop) {
      const [cx0 = 0, cy0 = 0, cx1 = 0, cy1 = 0] = crop;
      page.setCropBox(cx0, cy0, cx1 - cx0, cy1 - cy0);
    }
    page.setRotation(degrees(rotate));
    const bytes = await doc.save();

    const task = getDocument({ data: bytes, useWasm: false, verbosity: 0 });
    const pdf = await task.promise;
    const viewport = (await pdf.getPage(1)).getViewport({ scale: 1 });
    const [x0, y0, x1, y1] = crop ?? media;
    const box = { left: x0 ?? 0, bottom: y0 ?? 0, right: x1 ?? 0, top: y1 ?? 0 };
    const placed = placePage(box, rotate);
    expect(placed.width).toBeCloseTo(viewport.width, 6);
    expect(placed.height).toBeCloseTo(viewport.height, 6);
    // any point of the page lands where pdf.js shows it
    for (const [px, py] of [
      [box.left, box.bottom],
      [box.right, box.top],
      [box.left + 17, box.top - 5],
      [(box.left + box.right) / 2, box.bottom + 3],
    ] as const) {
      const [vx, vy] = viewport.convertToViewportPoint(px, py);
      const [x, y] = placedPoint(box, rotate, px, py);
      expect(x).toBeCloseTo(vx ?? Number.NaN, 6);
      expect(y).toBeCloseTo(vy ?? Number.NaN, 6);
    }
    await task.destroy();
  });
});
