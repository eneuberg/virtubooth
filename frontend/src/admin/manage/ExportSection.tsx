import { useQueryClient } from '@tanstack/react-query';
import { Archive, Download, Film, Trash2, X } from 'lucide-react';
import { useState, type FormEvent, type ReactNode } from 'react';
import type { ExportJob, ExportKind, ExportRequest } from '@/api/types';
import { formatBytes, formatRelative } from '@/lib/format';
import { Button, LinkButton } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { Checkbox } from '@/ui/Checkbox';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { EmptyState } from '@/ui/EmptyState';
import { IconButton } from '@/ui/IconButton';
import { Select } from '@/ui/Select';
import { Progress, Spinner } from '@/ui/Spinner';
import { showToast } from '@/ui/Toast';
import { errorText, showError } from '../common/usePhotoActions';
import { exportJobTitle } from '../lib/labels';
import { deleteExport, startExport } from '../store/actions';
import { useExports, useExtensionMap, useExtensions } from '../store/hooks';

const KIND_LABEL: Record<ExportKind, string> = { archive: 'Archiv', timelapse: 'Zeitraffer' };
const FPS = [6, 8, 12, 15, 24, 30] as const;

function Panel({
  icon: Icon,
  title,
  text,
  children,
  onSubmit,
  testid,
}: {
  icon: typeof Archive;
  title: string;
  text: string;
  children: ReactNode;
  onSubmit: () => void;
  testid: string;
}) {
  return (
    <form
      noValidate
      data-testid={testid}
      onSubmit={(e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        onSubmit();
      }}
      className="grid content-start gap-3 border-t-2 border-ink pt-3"
    >
      <h2 className="flex items-center gap-2 text-lg font-bold">
        <Icon aria-hidden="true" className="size-5" strokeWidth={2} />
        {title}
      </h2>
      <p className="text-sm text-ink-muted">{text}</p>
      {children}
    </form>
  );
}

function JobStatus({ job }: { job: ExportJob }) {
  switch (job.status) {
    case 'queued':
      return (
        <span className="inline-flex items-center gap-2 text-sm text-ink-muted">
          <Spinner label="Wartet…" /> Wartet…
        </span>
      );
    case 'running':
      return <Progress label="Wird erstellt…" value={job.progress ?? 0} className="w-full max-w-xs" />;
    case 'done':
      return (
        <span className="text-sm text-ink-muted tabular">
          <span translate="no" className="break-all">
            {job.file_name}
          </span>
          {job.bytes !== null ? `, ${formatBytes(job.bytes)}` : ''}
        </span>
      );
    default:
      return (
        <span role="alert" className="text-sm font-semibold text-danger">
          {job.error ?? 'Der Export ist fehlgeschlagen.'}
        </span>
      );
  }
}

/**
 * Export: archive and timelapse as background jobs on the server. (The QR sheet is gone:
 * the QR-Codes tab makes each code's PNG, PDF and poster.)
 */
export function ExportSection() {
  const qc = useQueryClient();
  const exportsQuery = useExports();
  const { data: extensions } = useExtensions();
  const extensionMap = useExtensionMap();
  const data = exportsQuery.data;
  const [archive, setArchive] = useState({ include_hidden: false, include_db: false });
  const [timelapse, setTimelapse] = useState({
    extension: '',
    fps: 12,
    crossfade: false,
    include_hidden: false,
  });
  const [starting, setStarting] = useState<ExportKind | null>(null);
  const [errors, setErrors] = useState<Partial<Record<ExportKind, string>>>({});
  const [deleting, setDeleting] = useState<ExportJob | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const activities = (extensions ?? []).filter((e) => e.uploads);
  const timelapseExt = timelapse.extension || activities[0]?.id || 'beer';
  const ffmpeg = data?.ffmpeg ?? true;

  const start = async (request: ExportRequest) => {
    setStarting(request.kind);
    setErrors((e) => ({ ...e, [request.kind]: undefined }));
    try {
      const { created } = await startExport(qc, request);
      showToast(
        created
          ? { message: `${KIND_LABEL[request.kind]} wird erstellt`, tone: 'success' }
          : { message: `Läuft schon: ${KIND_LABEL[request.kind]} ist bereits in Arbeit.`, tone: 'info' },
      );
    } catch (err) {
      setErrors((e) => ({ ...e, [request.kind]: errorText(err) }));
    } finally {
      setStarting(null);
    }
  };

  const cancel = async (job: ExportJob) => {
    try {
      await deleteExport(qc, job.id);
      showToast({ message: `${KIND_LABEL[job.kind]} abgebrochen`, tone: 'info' });
    } catch (err) {
      showError(err);
    }
  };

  if (exportsQuery.isError && !data) {
    return (
      <section aria-labelledby="section-title" className="grid content-start gap-4 px-4 py-4 lg:px-6 lg:py-5">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Export
        </h1>
        <EmptyState
          icon={Archive}
          title="Export ist gerade nicht erreichbar"
          action={<Button onPress={() => void exportsQuery.refetch()}>Erneut laden</Button>}
        >
          {exportsQuery.error.message}
        </EmptyState>
      </section>
    );
  }

  const jobs = data?.jobs ?? [];
  return (
    <section aria-labelledby="section-title" className="grid content-start gap-6 px-4 py-4 lg:px-6 lg:py-5">
      <header className="grid gap-1">
        <h1 id="section-title" tabIndex={-1} className="text-xl font-bold outline-none">
          Export
        </h1>
        <p className="max-w-prose text-sm text-ink-muted">
          Die Dateien entstehen im Hintergrund auf dem Server. Du kannst die Seite verlassen; fertige Exporte
          stehen unten zum Herunterladen bereit.
        </p>
      </header>
      <section aria-labelledby="export-jobs" className={cx('grid gap-2', jobs.length === 0 && 'order-1')}>
        <h2 id="export-jobs" className="text-lg font-bold">
          Erstellte Exporte
        </h2>
        {exportsQuery.isPending ? (
          <Spinner />
        ) : jobs.length === 0 ? (
          <p className="text-sm text-ink-muted">Noch keine Exporte.</p>
        ) : (
          <ul className="grid border-t border-line" data-testid="export-jobs">
            {jobs.map((job) => (
              <li
                key={job.id}
                data-testid="export-job"
                data-status={job.status}
                data-kind={job.kind}
                className="grid gap-x-4 gap-y-2 border-b border-line py-3 sm:flex sm:items-center"
              >
                <div className="grid min-w-0 flex-1 gap-1">
                  <span className="font-semibold">{exportJobTitle(job, extensionMap)}</span>
                  <JobStatus job={job} />
                </div>
                <div className="flex items-center gap-2">
                  {job.status === 'done' && job.download_url ? (
                    <LinkButton
                      size="xs"
                      variant="primary"
                      icon={Download}
                      href={job.download_url}
                      download={job.file_name ?? ''}
                      data-testid="export-download"
                    >
                      Herunterladen
                    </LinkButton>
                  ) : null}
                  {job.status === 'queued' ? (
                    <Button
                      size="xs"
                      variant="quiet"
                      icon={X}
                      onPress={() => void cancel(job)}
                      data-testid="export-cancel"
                    >
                      Abbrechen
                    </Button>
                  ) : job.status === 'running' ? null : (
                    <IconButton
                      label={`${KIND_LABEL[job.kind]} löschen`}
                      icon={Trash2}
                      onPress={() => setDeleting(job)}
                      data-testid="export-delete"
                    />
                  )}
                  {job.finished_at ? (
                    <time
                      dateTime={job.finished_at}
                      className="ml-auto text-xs text-ink-muted sm:ml-2 sm:min-w-32 sm:text-right"
                    >
                      fertig {formatRelative(job.finished_at)}
                    </time>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <div className="grid gap-8 md:grid-cols-2">
        <Panel
          icon={Archive}
          title="Archiv"
          text="Alle Fotos als ZIP, mit Listen der Fotos, Gäste und Instagram-Namen."
          onSubmit={() => void start({ kind: 'archive', options: archive })}
          testid="export-archive"
        >
          <div className="grid">
            <Checkbox
              isSelected={archive.include_hidden}
              onChange={(v) => setArchive({ ...archive, include_hidden: v })}
            >
              Ausgeblendete Fotos mitnehmen
            </Checkbox>
            <Checkbox
              isSelected={archive.include_db}
              onChange={(v) => setArchive({ ...archive, include_db: v })}
            >
              Datenbank mitnehmen (für ein Backup)
            </Checkbox>
          </div>
          {errors.archive ? <p className="text-sm font-semibold text-danger">{errors.archive}</p> : null}
          <Button
            type="submit"
            variant="primary"
            size="sm"
            isPending={starting === 'archive'}
            className="justify-self-start"
          >
            Archiv erstellen
          </Button>
        </Panel>
        <Panel
          icon={Film}
          title="Zeitraffer"
          text="Ein Video aus allen Fotos einer Aktivität, in der Reihenfolge der Aufnahme."
          onSubmit={() =>
            void start({ kind: 'timelapse', options: { ...timelapse, extension: timelapseExt } })
          }
          testid="export-timelapse"
        >
          {!ffmpeg ? (
            <p className="text-sm font-semibold text-accent-ink" data-testid="no-ffmpeg">
              Auf dem Server fehlt ffmpeg, darum geht der Zeitraffer gerade nicht.
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Select
              label="Aktivität"
              inlineLabel
              size="sm"
              options={activities.map((e) => ({ id: e.id, label: e.title }))}
              value={timelapseExt}
              onChange={(extension) => setTimelapse({ ...timelapse, extension })}
              isDisabled={!ffmpeg}
            />
            <Select
              label="Fotos pro Sekunde"
              inlineLabel
              size="sm"
              options={FPS.map((n) => ({ id: String(n), label: String(n) }))}
              value={String(timelapse.fps)}
              onChange={(fps) => setTimelapse({ ...timelapse, fps: Number(fps) })}
              isDisabled={!ffmpeg}
            />
          </div>
          <div className="grid">
            <Checkbox
              isSelected={timelapse.crossfade}
              onChange={(v) => setTimelapse({ ...timelapse, crossfade: v })}
              isDisabled={!ffmpeg}
            >
              Weich überblenden
            </Checkbox>
            <Checkbox
              isSelected={timelapse.include_hidden}
              onChange={(v) => setTimelapse({ ...timelapse, include_hidden: v })}
              isDisabled={!ffmpeg}
            >
              Ausgeblendete Fotos mitnehmen
            </Checkbox>
          </div>
          {errors.timelapse ? <p className="text-sm font-semibold text-danger">{errors.timelapse}</p> : null}
          <Button
            type="submit"
            variant="primary"
            size="sm"
            isPending={starting === 'timelapse'}
            isDisabled={!ffmpeg}
            className="justify-self-start"
          >
            Zeitraffer erstellen
          </Button>
        </Panel>
      </div>
      <ConfirmDialog
        isOpen={deleting !== null}
        onOpenChange={(open) => {
          if (!open) {
            setDeleting(null);
            setDeleteError(null);
          }
        }}
        title={deleting ? `${exportJobTitle(deleting, extensionMap)} löschen?` : ''}
        confirmLabel="Löschen"
        error={deleteError}
        data-testid="confirm"
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await deleteExport(qc, deleting.id);
          } catch (err) {
            setDeleteError(errorText(err));
            throw err;
          }
        }}
      >
        <p>Die Datei wird vom Server gelöscht. Du kannst den Export jederzeit neu erstellen.</p>
      </ConfirmDialog>
    </section>
  );
}
