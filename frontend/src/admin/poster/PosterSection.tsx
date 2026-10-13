/**
 * Verwaltung → Plakat: the host's own poster template. Upload a PDF (stored on the
 * server, so every admin device has it), pick a page, place the green square where
 * the QR code goes (mouse, touch, keyboard), save it, print a test poster. Without a
 * template the standard poster (Kontaktbogen style) is used.
 *
 * pdf.js and the print library load only here, on demand (separate chunks).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Download, FileText, Printer, RotateCcw, Save, Trash2, Upload } from 'lucide-react';
import type { PDFDocumentProxy } from 'pdfjs-dist/legacy/build/pdf.mjs';
import { useCallback, useEffect, useState } from 'react';
import { DropZone, FileTrigger, Text, type FileDropItem } from 'react-aria-components';
import { formatBytes, formatRelative } from '@/lib/format';
import type { CodePrintInput } from '@/print/types';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { cx } from '@/ui/cx';
import { EmptyState } from '@/ui/EmptyState';
import { Select } from '@/ui/Select';
import { Skeleton } from '@/ui/Skeleton';
import { Spinner } from '@/ui/Spinner';
import { showToast } from '@/ui/Toast';
import { toastAvoid } from '@/ui/toastPlacement';
import { errorText, showError } from '../common/usePhotoActions';
import { DESKTOP, useMediaQuery } from '../lib/browser';
import {
  deleteTemplate,
  fetchPoster,
  saveLayout,
  uploadTemplate,
  type PosterOut,
  type PosterTemplate,
} from './api';
import { defaultRect, sameRect, type PageSize, type RelRect } from './geometry';
import { posterKey, posterPdfKey } from './keys';
import { useContainerWidth } from './measure';
import { PageCanvas } from './PageCanvas';
import { openPdf, UNREADABLE } from './pdfjs';
import { QrFieldEditor } from './QrFieldEditor';
import { templateBytes } from './template';

/** The page is at most this wide on a desktop (CSS px). */
const MAX_PAGE_WIDTH = 720;

/**
 * The code on test prints: the bare address shows the "scan the QR code" gate, so it
 * grants no access. TODO(INT): the real event name (settings API) instead of "Party",
 * and the real codes from the QR table.
 */
function sampleCode(): CodePrintInput {
  return { url: `${location.origin}/`, number: 0, name: 'Muster 0', eventName: 'Party', subtitle: null };
}

const SAMPLE_NOTE = 'Der Probedruck hat einen Muster-Code ohne Zugang.';

function megabytes(bytes: number): string {
  return `${Math.round(bytes / 1_000_000)} MB`;
}

function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || /\.pdf$/i.test(file.name);
}

/** Build the poster with the sample code and save it (the print library loads now). */
async function downloadSamplePoster(template: { pdf: ArrayBuffer; page: number; rect: RelRect } | null) {
  try {
    const print = await import('@/print');
    const sample = sampleCode();
    const pdf = await print.posterPdf(sample, template);
    print.downloadBlob(pdf, print.exportFileName(sample, 'poster'));
  } catch (err) {
    const known = err instanceof Error && err.name === 'PrintError';
    showToast({ message: known ? err.message : 'Das Plakat ließ sich nicht erstellen.', tone: 'error' });
  }
}

function usePosterUpload(maxBytes: number) {
  const qc = useQueryClient();
  const [pending, setPending] = useState(false);
  const upload = async (file: File) => {
    if (!isPdf(file)) {
      showToast({ message: 'Das ist keine PDF-Datei.', tone: 'error' });
      return;
    }
    if (file.size > maxBytes) {
      showToast({ message: `Die PDF ist zu groß (höchstens ${megabytes(maxBytes)}).`, tone: 'error' });
      return;
    }
    setPending(true);
    try {
      qc.setQueryData(posterKey, await uploadTemplate(file));
      showToast({ message: 'Vorlage hochgeladen. Jetzt das grüne Feld platzieren.', tone: 'success' });
    } catch (err) {
      showError(err);
    } finally {
      setPending(false);
    }
  };
  return { upload, pending };
}

function UploadButton({
  label,
  primary,
  pending,
  onFile,
}: {
  label: string;
  primary?: boolean;
  pending: boolean;
  onFile: (file: File) => void;
}) {
  return (
    <FileTrigger
      acceptedFileTypes={['application/pdf']}
      onSelect={(files) => {
        const file = files?.[0];
        if (file) onFile(file);
      }}
    >
      <Button
        size="sm"
        variant={primary ? 'primary' : 'secondary'}
        icon={Upload}
        isPending={pending}
        pendingLabel="Wird hochgeladen…"
        data-testid="poster-upload"
      >
        {label}
      </Button>
    </FileTrigger>
  );
}

/** Desktop: drop a PDF from the file manager. */
function PdfDropZone({ onFile }: { onFile: (file: File) => void }) {
  return (
    <DropZone
      getDropOperation={() => 'copy'}
      onDrop={(e) => {
        const item = e.items.find((i): i is FileDropItem => i.kind === 'file');
        if (item) void item.getFile().then(onFile);
      }}
      className={({ isDropTarget, isFocusVisible }) =>
        cx(
          'grid min-h-24 place-items-center rounded-control border-2 border-dashed border-line-strong p-4 text-center text-sm text-ink-muted outline-none',
          isDropTarget && 'border-accent bg-accent-tint text-ink',
          isFocusVisible && 'outline-2 outline-offset-2 outline-focus',
        )
      }
    >
      <Text slot="label">PDF hierher ziehen</Text>
    </DropZone>
  );
}

function UploadHelp() {
  return <p className="text-sm text-ink-muted">Höchstens 8 MB. Eine Seite davon wird das Plakat.</p>;
}

function NoTemplate({ maxBytes }: { maxBytes: number }) {
  const desktop = useMediaQuery(DESKTOP);
  const { upload, pending } = usePosterUpload(maxBytes);
  const [building, setBuilding] = useState(false);
  return (
    <div className="grid max-w-2xl gap-4" data-testid="poster-empty">
      <EmptyState
        icon={FileText}
        title="Noch keine Vorlage"
        className="max-w-xl py-4"
        action={
          <div className="flex flex-wrap gap-2">
            <UploadButton
              label="PDF-Vorlage hochladen"
              primary
              pending={pending}
              onFile={(f) => void upload(f)}
            />
            <Button
              size="sm"
              icon={Download}
              isPending={building}
              pendingLabel="Wird erstellt…"
              data-testid="poster-standard"
              onPress={() => {
                setBuilding(true);
                void downloadSamplePoster(null).finally(() => setBuilding(false));
              }}
            >
              Standard-Plakat ansehen (PDF)
            </Button>
          </div>
        }
      >
        <UploadHelp />
      </EmptyState>
      {desktop ? <PdfDropZone onFile={(f) => void upload(f)} /> : null}
      <p className="text-sm text-ink-muted">{SAMPLE_NOTE}</p>
    </div>
  );
}

/** pdf.js's view of the template: the document, or why it can't be shown. */
function usePdfDocument(bytes: ArrayBuffer | undefined) {
  const [state, setState] = useState<{ doc: PDFDocumentProxy | null; error: string | null }>({
    doc: null,
    error: null,
  });
  useEffect(() => {
    if (!bytes) return undefined;
    let alive = true;
    let opened: PDFDocumentProxy | null = null;
    openPdf(bytes).then(
      (doc) => {
        opened = doc;
        if (alive) setState({ doc, error: null });
        else void doc.loadingTask.destroy();
      },
      () => {
        if (alive) setState({ doc: null, error: UNREADABLE });
      },
    );
    return () => {
      alive = false;
      void opened?.loadingTask.destroy();
    };
  }, [bytes]);
  return state;
}

/** Page sizes in PDF points as pdf.js shows them (rotation applied), per 0-based page. */
function usePageSize(doc: PDFDocumentProxy | null, page: number): PageSize | null {
  const [sizes, setSizes] = useState<{ doc: PDFDocumentProxy; page: number; size: PageSize } | null>(null);
  useEffect(() => {
    if (!doc) return undefined;
    let alive = true;
    void doc.getPage(page + 1).then((p) => {
      const { width, height } = p.getViewport({ scale: 1 });
      if (alive) setSizes({ doc, page, size: { width, height } });
    });
    return () => {
      alive = false;
    };
  }, [doc, page]);
  return sizes && sizes.doc === doc && sizes.page === page ? sizes.size : null;
}

/** The sample code's modules for the preview inside the green square. */
function useSampleMatrix(): boolean[][] | null {
  const [matrix, setMatrix] = useState<boolean[][] | null>(null);
  useEffect(() => {
    let alive = true;
    void import('@/print').then((print) => {
      if (alive) setMatrix(print.qrMatrix(sampleCode().url));
    });
    return () => {
      alive = false;
    };
  }, []);
  return matrix;
}

type Busy = 'save' | 'print' | null;

function TemplateEditor({ template, maxBytes }: { template: PosterTemplate; maxBytes: number }) {
  const qc = useQueryClient();
  const desktop = useMediaQuery(DESKTOP);
  const { upload, pending: uploading } = usePosterUpload(maxBytes);
  const bytes = useQuery({
    queryKey: posterPdfKey(template.sha256),
    queryFn: () => templateBytes(template.sha256),
    staleTime: Infinity,
    gcTime: 5 * 60_000,
  });
  const { doc, error: openError } = usePdfDocument(bytes.data);
  const [renderError, setRenderError] = useState<string | null>(null);
  const onRenderError = useCallback(() => setRenderError(UNREADABLE), []);
  const matrix = useSampleMatrix();
  const [measure, width] = useContainerWidth(MAX_PAGE_WIDTH);

  // the unsaved choice; null = what the server has
  const [draft, setDraft] = useState<{ page: number; rect: RelRect | null } | null>(null);
  const pages = doc?.numPages ?? template.pages ?? 1;
  const page = Math.min(draft?.page ?? template.page ?? 0, Math.max(0, pages - 1));
  const size = usePageSize(doc, page);
  const saved = template.rect && template.page === page ? template.rect : null;
  const rect = draft?.rect ?? saved ?? (size ? defaultRect(size) : null);
  const dirty = template.rect === null || template.page !== page || !sameRect(rect, template.rect);

  const [busy, setBusy] = useState<Busy>(null);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  const save = async () => {
    if (!doc || !size || !rect) return;
    setBusy('save');
    try {
      const out = await saveLayout({
        page,
        pages: doc.numPages,
        page_width: size.width,
        page_height: size.height,
        rect,
      });
      qc.setQueryData<PosterOut>(posterKey, out);
      setDraft(null);
      showToast({ message: 'QR-Feld gespeichert.', tone: 'success' });
    } catch (err) {
      showError(err);
    } finally {
      setBusy(null);
    }
  };

  const testPrint = async () => {
    if (!bytes.data || !rect) return;
    setBusy('print');
    await downloadSamplePoster({ pdf: bytes.data, page, rect });
    setBusy(null);
  };

  const error = bytes.isError ? errorText(bytes.error) : (openError ?? renderError);
  const ready = doc !== null && size !== null && rect !== null && width > 0;

  return (
    <>
      <div className="grid gap-x-8 gap-y-4 lg:grid-cols-[minmax(0,45rem)_minmax(14rem,20rem)] lg:items-start">
        <div className="grid min-w-0 gap-3">
          <div className="flex min-h-10 flex-wrap items-center gap-2">
            {pages > 1 ? (
              <Select
                label="Seite"
                size="sm"
                inlineLabel
                data-testid="poster-page-select"
                options={Array.from({ length: pages }, (_, i) => ({
                  id: i,
                  label: `Seite ${i + 1} von ${pages}`,
                }))}
                value={page}
                onChange={(next) => setDraft({ page: next, rect: null })}
              />
            ) : null}
            <span className="ml-auto" data-testid="poster-state" data-dirty={dirty ? 'true' : 'false'}>
              {dirty ? <Badge tone="amber">Nicht gespeichert</Badge> : <Badge tone="ok">Gespeichert</Badge>}
            </span>
          </div>
          {/* clip the handle's touch area at the screen edge instead of scrolling sideways */}
          <div className="-mx-4 overflow-x-clip px-4 lg:mx-0 lg:overflow-x-visible lg:px-0">
            <div ref={measure} className="w-full">
              {error ? (
                <p role="alert" className="text-sm font-semibold text-danger" data-testid="poster-error">
                  {error}
                </p>
              ) : ready ? (
                <div className="relative" style={{ width }}>
                  <PageCanvas doc={doc} page={page} size={size} width={width} onError={onRenderError} />
                  <QrFieldEditor
                    rect={rect}
                    size={size}
                    matrix={matrix}
                    onChange={(next) => setDraft({ page, rect: next })}
                  />
                </div>
              ) : (
                <div
                  className="relative grid max-w-180 place-items-center"
                  style={{ aspectRatio: '210 / 297' }}
                >
                  <Skeleton className="absolute inset-0 h-auto rounded-none" />
                  <Spinner label="Vorlage wird geladen…" />
                </div>
              )}
            </div>
          </div>
        </div>
        <aside className="grid content-start gap-3 text-sm" aria-label="Vorlage">
          <p className="text-ink-muted">
            Das grüne Feld zeigt, wo der QR-Code hinkommt. Ziehen verschiebt es, die Ecke unten rechts ändert
            die Größe. Am besten liegt es auf einer hellen Fläche der Vorlage.
          </p>
          <p className="text-ink-muted tabular" data-testid="poster-file">
            Vorlage: {formatBytes(template.bytes)}, hochgeladen {formatRelative(template.uploaded_at)}
          </p>
          <div className="grid justify-items-start gap-2">
            <UploadButton
              label="Andere Vorlage hochladen"
              pending={uploading}
              onFile={(f) => void upload(f)}
            />
            <UploadHelp />
          </div>
          {desktop ? <PdfDropZone onFile={(f) => void upload(f)} /> : null}
          <p className="text-ink-muted">{SAMPLE_NOTE}</p>
        </aside>
      </div>
      <div
        role="toolbar"
        aria-label="Plakat"
        data-testid="poster-actions"
        {...toastAvoid}
        className={cx(
          'sticky bottom-[calc(4rem+env(safe-area-inset-bottom))] z-(--z-sticky) -mx-4 border-t border-line bg-surface px-4 py-2',
          'grid grid-cols-2 gap-2 sm:flex sm:flex-wrap sm:items-center',
          'lg:bottom-0 lg:-mx-6 lg:px-6 lg:py-3 landscape-phone:bottom-0',
        )}
      >
        <Button
          size="xs"
          variant="primary"
          icon={Save}
          isDisabled={!dirty || !ready}
          isPending={busy === 'save'}
          onPress={() => void save()}
          data-testid="poster-save"
        >
          Speichern
        </Button>
        <Button
          size="xs"
          variant="quiet"
          icon={RotateCcw}
          isDisabled={draft === null}
          onPress={() => setDraft(null)}
          data-testid="poster-discard"
        >
          Änderungen verwerfen
        </Button>
        <Button
          size="xs"
          icon={Printer}
          isDisabled={!ready}
          isPending={busy === 'print'}
          pendingLabel="Wird erstellt…"
          onPress={() => void testPrint()}
          data-testid="poster-test-print"
        >
          Probedruck (PDF)
        </Button>
        <Button
          size="xs"
          variant="danger-outline"
          icon={Trash2}
          onPress={() => setRemoving(true)}
          data-testid="poster-remove"
          className="sm:ml-auto"
        >
          Vorlage entfernen…
        </Button>
      </div>
      <ConfirmDialog
        isOpen={removing}
        onOpenChange={(open) => {
          setRemoving(open);
          if (!open) setRemoveError(null);
        }}
        title="Vorlage entfernen?"
        confirmLabel="Entfernen"
        error={removeError}
        data-testid="confirm"
        onConfirm={async () => {
          try {
            qc.setQueryData<PosterOut>(posterKey, await deleteTemplate());
            showToast({ message: 'Vorlage entfernt.', tone: 'success' });
          } catch (err) {
            setRemoveError(errorText(err));
            throw err;
          }
        }}
      >
        <p>Danach gibt es wieder das Standard-Plakat. Die PDF wird vom Server gelöscht.</p>
      </ConfirmDialog>
    </>
  );
}

export function PosterSection() {
  const query = useQuery({
    queryKey: posterKey,
    queryFn: fetchPoster,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });
  const data = query.data;
  return (
    <section aria-labelledby="section-title" className="grid content-start gap-4 px-4 py-4 lg:px-6 lg:py-5">
      <header className="grid gap-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Plakat
        </h1>
        <p className="max-w-prose text-sm text-ink-muted">
          Eine eigene PDF-Vorlage hochladen und das grüne Feld dorthin ziehen, wo der QR-Code hin soll. Ohne
          Vorlage gibt es das Standard-Plakat.
        </p>
      </header>
      {!data ? (
        query.isError ? (
          <EmptyState
            icon={Printer}
            title="Plakat ist gerade nicht erreichbar"
            action={<Button onPress={() => void query.refetch()}>Erneut laden</Button>}
          >
            {errorText(query.error)}
          </EmptyState>
        ) : (
          <Spinner />
        )
      ) : data.template ? (
        <TemplateEditor key={data.template.sha256} template={data.template} maxBytes={data.max_bytes} />
      ) : (
        <NoTemplate maxBytes={data.max_bytes} />
      )}
    </section>
  );
}
