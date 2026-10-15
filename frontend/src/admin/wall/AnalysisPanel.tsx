/**
 * The photo inspector's (and the phone viewer's) "Analyse" block: what the analysis
 * found on this photo (state, the guest's opt-outs, details, the frozen object lists
 * — „Lokales Modell“, „KI (Claude)“ and the merged list the properties are rated on,
 * as tabs — with the detection runs and property scores, raw facts) and the switch for
 * the frames. The frames themselves ({@link AnalysisBoxes}) lie on the big photo of the
 * screen, those of the chosen tab in its colour; hovering an object in the list
 * highlights its frame. Analyses are made once
 * and never redone, so there is no "Neu analysieren". Both render nothing when the
 * wall extension is off here.
 */
import { ShieldOff } from 'lucide-react';
import { create } from 'zustand';
import type { AdminPhoto } from '@/api/types';
import { Badge } from '@/ui/Badge';
import { cx } from '@/ui/cx';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { durationsText, sourceText } from '../ml/text';
import { isNoAnalysis, isRouteMissing } from './api';
import { usePhotoAnalysis, useWallEnabled } from './hooks';
import { labelColor, textOn } from './labelColors';
import { ANALYSIS_STATE_LABELS, BOX_KIND_LABELS } from './labels';
import { analysisFrames, analysisViews, type ObjectView } from './objectViews';
import { ObjectViewTabs } from './ObjectViewTabs';
import { boxStyle, factValue, type FrameBox } from './text';
import type { AnalysisState, PhotoAnalysis } from './types';

const STATE_TONE: Record<AnalysisState, 'neutral' | 'ok' | 'mark' | 'amber'> = {
  pending: 'neutral',
  running: 'amber',
  done: 'ok',
  failed: 'mark',
  skipped: 'neutral',
};

/** The object the pointer is on in the list (photo id + view + key), for its frame. */
const useHovered = create<{ key: string | null; set: (key: string | null) => void }>((set) => ({
  key: null,
  set: (key) => set({ key }),
}));

/** The object list whose frames lie on the photo (the tab chosen in the panel). */
const useObjectView = create<{ view: ObjectView; set: (view: ObjectView) => void }>((set) => ({
  view: 'merged',
  set: (view) => set({ view }),
}));

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

/** Frames in % of the box they lie in; `highlight` = an object idx to stand out. */
export function BoxLayer({
  boxes,
  highlight = null,
}: {
  boxes: readonly FrameBox[];
  highlight?: number | null;
}) {
  if (boxes.length === 0) return null;
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0" data-testid="analysis-boxes">
      {boxes.map((box, i) => {
        const lit = highlight !== null && box.objectIndex === highlight;
        const dim = highlight !== null && !lit;
        // the thing's colour, as on the Live tiles (faces and hands by their kind)
        const color = box.color ?? labelColor(box.key ?? box.kind).color;
        const outline = box.outline ?? (box.both ? 'double' : 'solid');
        return (
          <div
            // boxes have no id; their order is the server's
            // oxlint-disable-next-line react/no-array-index-key
            key={i}
            data-testid="analysis-box"
            data-kind={box.kind}
            data-object={box.objectIndex}
            data-sources={box.sources}
            data-both={box.both || undefined}
            data-outline={outline}
            data-lit={lit || undefined}
            className={cx(
              'absolute rounded-[2px] transition-opacity duration-(--duration-quick)',
              // who found it: the local model solid, an AI dashed, both double
              outline === 'double' ? 'border-4 border-double' : lit ? 'border-[3px]' : 'border-2',
              outline === 'dashed' && 'border-dashed',
              dim && 'opacity-30',
            )}
            style={{ ...boxStyle(box), borderColor: color }}
          >
            <span
              className="absolute -top-px -left-px max-w-[12rem] truncate px-1 text-[0.6875rem] leading-4 font-semibold"
              style={{ backgroundColor: color, color: textOn(color) }}
            >
              {box.label || BOX_KIND_LABELS[box.kind]}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Boxes({ photoId }: { photoId: string }) {
  const { data } = usePhotoAnalysis(photoId);
  const hovered = useHovered((s) => s.key);
  const view = useObjectView((s) => s.view);
  if (!data) return null;
  const prefix = `${photoId}:${view}:`;
  const highlight = hovered?.startsWith(prefix) ? Number(hovered.slice(prefix.length)) : null;
  return <BoxLayer boxes={analysisFrames(data, view)} highlight={highlight} />;
}

function Panel({ photo, showBoxes, onShowBoxesChange }: AnalysisPanelProps) {
  const query = usePhotoAnalysis(photo.id);

  if (query.isError && isRouteMissing(query.error)) return null;

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
        <Result
          photoId={photo.id}
          analysis={data}
          showBoxes={showBoxes}
          onShowBoxesChange={onShowBoxesChange}
        />
      ) : (
        <p className="text-sm text-ink-muted" data-testid="analysis-empty">
          {isNoAnalysis(query.error)
            ? 'Noch keine Analyse für dieses Foto.'
            : 'Die Analyse ließ sich nicht laden.'}
        </p>
      )}
    </section>
  );
}

function OptOutMarks({ optOut }: { optOut: PhotoAnalysis['opt_out'] }) {
  if (!optOut.analysis && !optOut.external_ai) return null;
  return (
    <div className="flex flex-wrap gap-2" data-testid="analysis-opt-out">
      {optOut.analysis ? (
        <Badge tone="mark" icon={ShieldOff}>
          Gast möchte keine Auswertung
        </Badge>
      ) : null}
      {optOut.external_ai ? (
        <Badge tone="mark" icon={ShieldOff}>
          Keine externe KI
        </Badge>
      ) : null}
    </div>
  );
}

const RUN_STATE: Record<PhotoAnalysis['runs'][number]['state'], string> = {
  done: 'fertig',
  failed: 'fehlgeschlagen',
  skipped: 'übersprungen',
};

const EMPTY: Record<ObjectView, string> = {
  local: 'Das lokale Modell lief für dieses Foto nicht (aus oder übersprungen).',
  ai: 'Keine KI-Erkennung für dieses Foto (aus, noch nicht dran oder fehlgeschlagen).',
  merged: 'Keine Objekte erkannt.',
};

function Objects({ photoId, analysis }: { photoId: string; analysis: PhotoAnalysis }) {
  const setHovered = useHovered((s) => s.set);
  const view = useObjectView((s) => s.view);
  const setView = useObjectView((s) => s.set);
  const props = analysis.properties;
  return (
    <div className="grid gap-2" data-testid="analysis-objects">
      <h4 className="text-sm font-bold">Objekte</h4>
      {analysis.objects.length === 0 ? (
        <p className="text-sm text-ink-muted">
          {analysis.runs.length === 0
            ? 'Keine Objektliste: das Foto wurde ohne Objekterkennung ausgewertet (z. B. vor dem Update).'
            : 'Keine Objekte erkannt.'}
        </p>
      ) : (
        <ObjectViewTabs
          views={analysisViews(analysis)}
          value={view}
          onChange={setView}
          onHover={(v, key) => setHovered(key === null ? null : `${photoId}:${v}:${key}`)}
          empty={EMPTY}
          properties={props}
        />
      )}
      {analysis.runs.length > 0 ? (
        <ul
          className="grid gap-0.5 text-xs text-ink-muted"
          data-testid="analysis-runs"
          aria-label="Erkennungsläufe"
        >
          {analysis.runs.map((r) => (
            <li key={r.source}>
              Erkennung {sourceText(r.source)}: {RUN_STATE[r.state]}
              {r.model ? <span className="font-mono"> ({r.model})</span> : null}
              {r.error ? <span className="text-danger"> – {r.error}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Result({
  photoId,
  analysis,
  showBoxes,
  onShowBoxesChange,
}: {
  photoId: string;
  analysis: PhotoAnalysis;
  showBoxes: boolean;
  onShowBoxesChange: (show: boolean) => void;
}) {
  const facts = Object.entries(analysis.facts);
  const durations = durationsText(analysis.durations_ms);
  return (
    <>
      <OptOutMarks optOut={analysis.opt_out} />
      {analysis.error ? <p className="text-sm text-danger">{analysis.error}</p> : null}
      {analysisFrames(analysis, 'merged').length > 0 || analysis.objects_local.length > 0 ? (
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
      ) : analysis.state === 'done' && analysis.objects.length === 0 ? (
        <p className="text-sm text-ink-muted">Nichts Besonderes gefunden.</p>
      ) : null}
      {analysis.state === 'done' || analysis.objects.length > 0 ? (
        <Objects photoId={photoId} analysis={analysis} />
      ) : null}
      {facts.length > 0 || durations ? (
        <HelpDisclosure summary="Rohwerte" variant="section" headingLevel={4}>
          <dl className="font-mono grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-1 text-xs">
            {facts.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-ink-muted">{k}</dt>
                <dd className="tabular">{factValue(v)}</dd>
              </div>
            ))}
          </dl>
          {durations ? <p className="mt-2 text-xs text-ink-muted tabular">Dauer: {durations}</p> : null}
        </HelpDisclosure>
      ) : null}
    </>
  );
}
