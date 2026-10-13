import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { useEffect, useRef, useState } from 'react';
import { cx } from '@/ui/cx';
import { loadPdfJs } from './pdfjs';
import type { PageSize } from './geometry';

/** iOS refuses canvases above ~16.7 MP; stay well below. */
const MAX_PIXELS = 10_000_000;

/**
 * One page of the PDF drawn to a canvas at `width` CSS pixels (sharp on high-DPI
 * screens). The aspect ratio comes from `size` so the space is kept while it draws.
 * Annotations are left out, like the export (which embeds the page content only).
 */
export function PageCanvas({
  doc,
  page,
  size,
  width,
  onError,
  className,
}: {
  doc: PDFDocumentProxy;
  /** 0-based */
  page: number;
  size: PageSize;
  width: number;
  onError: (err: unknown) => void;
  className?: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [drawn, setDrawn] = useState<string | null>(null);
  const key = `${page}:${width}`;

  useEffect(() => {
    const target = canvas.current;
    if (!target || width <= 0) return undefined;
    let cancelled = false;
    let task: RenderTask | null = null;
    const draw = async () => {
      const [pdfjs, pdfPage] = await Promise.all([loadPdfJs(), doc.getPage(page + 1)]);
      if (cancelled) return;
      const base = pdfPage.getViewport({ scale: 1 });
      let scale = (width / base.width) * Math.min(window.devicePixelRatio || 1, 3);
      const pixels = base.width * base.height * scale * scale;
      if (pixels > MAX_PIXELS) scale *= Math.sqrt(MAX_PIXELS / pixels);
      const viewport = pdfPage.getViewport({ scale });
      // an offscreen canvas first: the old picture stays until the new one is ready
      const buffer = document.createElement('canvas');
      buffer.width = Math.floor(viewport.width);
      buffer.height = Math.floor(viewport.height);
      task = pdfPage.render({
        canvas: buffer,
        viewport,
        annotationMode: pdfjs.AnnotationMode.DISABLE,
      });
      await task.promise;
      if (cancelled) return;
      target.width = buffer.width;
      target.height = buffer.height;
      target.getContext('2d')?.drawImage(buffer, 0, 0);
      setDrawn(key);
    };
    draw().catch((err: unknown) => {
      if (cancelled || (err instanceof Error && err.name === 'RenderingCancelledException')) return;
      onError(err);
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, page, width, key, onError]);

  return (
    <canvas
      ref={canvas}
      aria-hidden="true"
      data-testid="poster-page"
      data-drawn={drawn === key ? 'true' : 'false'}
      style={{ aspectRatio: `${size.width} / ${size.height}` }}
      className={cx('block h-auto w-full bg-white', className)}
    />
  );
}
