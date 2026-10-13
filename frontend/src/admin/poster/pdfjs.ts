/**
 * pdf.js, loaded on demand: the legacy build (the modern one needs APIs iOS 16/17
 * lack), its worker as a same-origin module file (the CSP allows no blob: workers),
 * no WebAssembly (no 'wasm-unsafe-eval' in the CSP; JPX/JBIG2 images then stay blank
 * in the preview only), no ImageDecoder. Pages are drawn to a canvas, nothing else.
 */
import type * as PdfJsModule from 'pdfjs-dist/legacy/build/pdf.mjs';
import type { PDFDocumentProxy } from 'pdfjs-dist/legacy/build/pdf.mjs';

type PdfJs = typeof PdfJsModule;

let loading: Promise<PdfJs> | null = null;

export function loadPdfJs(): Promise<PdfJs> {
  loading ??= Promise.all([
    import('pdfjs-dist/legacy/build/pdf.mjs'),
    import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'),
  ]).then(([pdfjs, worker]) => {
    pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
    return pdfjs;
  });
  // a failed chunk load (offline, new deploy) may be retried
  loading.catch(() => {
    loading = null;
  });
  return loading;
}

/** Shown when pdf.js cannot open the file. */
export const UNREADABLE =
  'Die PDF lässt sich hier nicht anzeigen. Ist sie beschädigt oder mit Passwort geschützt?';

/** Open a PDF (a copy of the bytes goes to the worker; the caller keeps its buffer). */
export async function openPdf(bytes: ArrayBuffer): Promise<PDFDocumentProxy> {
  const pdfjs = await loadPdfJs();
  const task = pdfjs.getDocument({
    data: new Uint8Array(bytes.slice(0)),
    useWasm: false,
    // WebKit's ImageDecoder left JPEG images blank (tested); pdf.js's own decoder works everywhere
    isImageDecoderSupported: false,
    enableXfa: false,
    verbosity: pdfjs.VerbosityLevel.ERRORS,
  });
  try {
    return await task.promise;
  } catch {
    void task.destroy();
    throw new Error(UNREADABLE);
  }
}
