/**
 * The photo inspector's (and the phone viewer's) "Analyse" block: what the Live Wall's
 * analysis found on this photo (state, details, raw facts), the switch for the frames
 * and "Neu analysieren". The frames themselves ({@link AnalysisBoxes}) lie on the big
 * photo of the screen. Both render nothing when the wall extension is off here.
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

export interface AnalysisPanelProps {
  photo: AdminPhoto;
  /** the frames on the photo are shown (the switch „Rahmen zeigen“) */
  showBoxes: boolean;
  onShowBoxesChange: (show: boolean) => void;
}

export function AnalysisPanel(props: AnalysisPanelProps) {
  const enabled = useWallEnabled();
  if (!enabled) return null;
  return <Panel key={props.photo.id} {...props} />;
}

/**
 * The analysis frames over a photo: put it inside a box that covers exactly the photo
 * (FittedPhoto); the frames are placed in % of it.
 */
export function AnalysisBoxes({ photo, visible }: { photo: AdminPhoto; visible: boolean }) {
  const enabled = useWallEnabled();
  if (!enabled || !visible) return null;
  return <Boxes photoId={photo.id} />;
}

function Boxes({ photoId }: { photoId: string }) {
  const { data } = usePhotoAnalysis(photoId);
  if (!data || data.boxes.length === 0) return null;
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0" data-testid="analysis-boxes">
      {data.boxes.map((box, i) => (
        <div
          // boxes have no id; their order is the server's
          // oxlint-disable-next-line react/no-array-index-key
          key={i}
          data-testid="analysis-box"
          data-kind={box.kind}
          className="absolute rounded-[2px] border-2"
          style={{ ...boxStyle(box), borderColor: BOX_KIND_COLORS[box.kind] }}
        >
          <span
            className="absolute -top-px -left-px max-w-[12rem] truncate px-1 text-[0.6875rem] leading-4 font-semibold text-black"
            style={{ backgroundColor: BOX_KIND_COLORS[box.kind] }}
          >
            {box.label || BOX_KIND_LABELS[box.kind]}
          </span>
        </div>
      ))}
    </div>
  );
}

function Panel({ photo, showBoxes, onShowBoxesChange }: AnalysisPanelProps) {
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
        <Result analysis={data} showBoxes={showBoxes} onShowBoxesChange={onShowBoxesChange} />
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

function Result({
  analysis,
  showBoxes,
  onShowBoxesChange,
}: {
  analysis: PhotoAnalysis;
  showBoxes: boolean;
  onShowBoxesChange: (show: boolean) => void;
}) {
  const facts = Object.entries(analysis.facts);
  return (
    <>
      {analysis.error ? <p className="text-sm text-danger">{analysis.error}</p> : null}
      {analysis.boxes.length > 0 ? (
        <Switch isSelected={showBoxes} onChange={onShowBoxesChange} data-testid="analysis-boxes-switch">
          Rahmen auf dem Foto zeigen
        </Switch>
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
