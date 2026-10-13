/**
 * The photo inspector's "Analyse" block: what the Live Wall's analysis found on this
 * photo (state, boxes over the thumb, details, raw facts) and "Neu analysieren".
 * Renders nothing when the wall extension is off on this server.
 */
import { useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { useState } from 'react';
import type { AdminPhoto } from '@/api/types';
import { Badge } from '@/ui/Badge';
import { Button } from '@/ui/Button';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { showError } from '../common/usePhotoActions';
import { isNoAnalysis, isRouteMissing, reanalyzePhoto } from './api';
import { usePhotoAnalysis, useWallEnabled } from './hooks';
import { wk } from './keys';
import { ANALYSIS_STATE_LABELS, BOX_KIND_COLORS, BOX_KIND_LABELS } from './labels';
import { boxStyle, factValue } from './text';
import type { AnalysisState, PhotoAnalysis } from './types';

const STATE_TONE: Record<AnalysisState, 'neutral' | 'ok' | 'mark' | 'amber'> = {
  pending: 'neutral',
  running: 'amber',
  done: 'ok',
  failed: 'mark',
  skipped: 'neutral',
};

export function AnalysisPanel({ photo }: { photo: AdminPhoto }) {
  const enabled = useWallEnabled();
  if (!enabled) return null;
  return <Panel key={photo.id} photo={photo} />;
}

function Panel({ photo }: { photo: AdminPhoto }) {
  const qc = useQueryClient();
  const query = usePhotoAnalysis(photo.id);
  const [busy, setBusy] = useState(false);

  if (query.isError && isRouteMissing(query.error)) return null;

  const rerun = async () => {
    setBusy(true);
    try {
      const next = await reanalyzePhoto(photo.id);
      qc.setQueryData(wk.photoAnalysis(photo.id), next);
    } catch (err) {
      showError(err);
    } finally {
      setBusy(false);
    }
  };

  const data = query.data;
  return (
    <section
      aria-labelledby="analysis-title"
      className="grid gap-3 border-t border-line pt-3"
      data-testid="analysis"
    >
      <div className="flex items-center gap-2">
        <h3 id="analysis-title" className="text-md font-bold">
          Analyse
        </h3>
        {data ? (
          <span className="ml-auto" data-testid="analysis-state">
            <Badge tone={STATE_TONE[data.state]}>{ANALYSIS_STATE_LABELS[data.state]}</Badge>
          </span>
        ) : null}
      </div>
      {query.isPending ? (
        <Spinner label="Analyse lädt…" />
      ) : data ? (
        <Result photo={photo} analysis={data} />
      ) : (
        <p className="text-sm text-ink-muted" data-testid="analysis-empty">
          {isNoAnalysis(query.error)
            ? 'Noch keine Analyse für dieses Foto.'
            : 'Die Analyse ließ sich nicht laden.'}
        </p>
      )}
      <Button
        size="sm"
        variant="secondary"
        icon={RefreshCw}
        isPending={busy}
        onPress={() => void rerun()}
        data-testid="reanalyze"
      >
        Neu analysieren
      </Button>
    </section>
  );
}

function Result({ photo, analysis }: { photo: AdminPhoto; analysis: PhotoAnalysis }) {
  const [showBoxes, setShowBoxes] = useState(true);
  const facts = Object.entries(analysis.facts);
  return (
    <>
      {analysis.error ? <p className="text-sm text-danger">{analysis.error}</p> : null}
      {analysis.boxes.length > 0 ? (
        <>
          <div
            className="relative w-full overflow-hidden bg-surface-sunk"
            style={{ aspectRatio: `${photo.width} / ${photo.height}` }}
            data-testid="analysis-photo"
          >
            <img src={photo.thumb_url} alt="" className="absolute inset-0 size-full" />
            {showBoxes
              ? analysis.boxes.map((box, i) => (
                  <div
                    // boxes have no id; their order is the server's
                    // oxlint-disable-next-line react/no-array-index-key
                    key={i}
                    data-testid="analysis-box"
                    data-kind={box.kind}
                    className="pointer-events-none absolute rounded-[2px] border-2"
                    style={{ ...boxStyle(box), borderColor: BOX_KIND_COLORS[box.kind] }}
                  >
                    <span
                      className="absolute -top-px -left-px max-w-[12rem] truncate px-1 text-[0.6875rem] leading-4 font-semibold text-black"
                      style={{ backgroundColor: BOX_KIND_COLORS[box.kind] }}
                    >
                      {box.label || BOX_KIND_LABELS[box.kind]}
                    </span>
                  </div>
                ))
              : null}
          </div>
          <Switch isSelected={showBoxes} onChange={setShowBoxes} data-testid="analysis-boxes">
            Rahmen zeigen
          </Switch>
        </>
      ) : null}
      {analysis.details.length > 0 ? (
        <dl
          className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-1.5 text-sm"
          data-testid="analysis-details"
        >
          {analysis.details.map((d) => (
            <div key={d.label} className="contents">
              <dt className="text-ink-muted">{d.label}</dt>
              <dd>{d.value}</dd>
            </div>
          ))}
        </dl>
      ) : analysis.state === 'done' ? (
        <p className="text-sm text-ink-muted">Nichts Besonderes gefunden.</p>
      ) : null}
      {facts.length > 0 ? (
        <HelpDisclosure summary="Rohwerte" variant="section" headingLevel={4}>
          <dl className="font-mono grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-1 text-xs">
            {facts.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-ink-muted">{k}</dt>
                <dd className="tabular">{factValue(v)}</dd>
              </div>
            ))}
          </dl>
        </HelpDisclosure>
      ) : null}
    </>
  );
}
