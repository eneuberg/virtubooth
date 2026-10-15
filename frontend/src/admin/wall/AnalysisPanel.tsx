/**
 * The photo inspector's (and the phone viewer's) "Analyse" block: what the analysis
 * found on this photo (state, the guest's opt-outs, details, the frozen object list
 * with its detection runs and property scores, raw facts) and the switch for the
 * frames. The frames themselves ({@link AnalysisBoxes}) lie on the big photo of the
 * screen; hovering an object in the list highlights its frame. Analyses are made once
 * and never redone, so there is no "Neu analysieren". Both render nothing when the
 * wall extension is off here.
 */
import { ShieldOff, Sparkles } from 'lucide-react';
import { create } from 'zustand';
import type { AdminPhoto } from '@/api/types';
import { Badge } from '@/ui/Badge';
import { cx } from '@/ui/cx';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { Spinner } from '@/ui/Spinner';
import { Switch } from '@/ui/Switch';
import { durationsText, scoreText, sourceText } from '../ml/text';
import { isNoAnalysis, isRouteMissing } from './api';
import { usePhotoAnalysis, useWallEnabled } from './hooks';
import { ANALYSIS_STATE_LABELS, BOX_KIND_COLORS, BOX_KIND_LABELS } from './labels';
import { boxStyle, factValue, framesOf, type FrameBox } from './text';
import type { AnalysisState, PhotoAnalysis } from './types';

const STATE_TONE: Record<AnalysisState, 'neutral' | 'ok' | 'mark' | 'amber'> = {
  pending: 'neutral',
  running: 'amber',
  done: 'ok',
  failed: 'mark',
  skipped: 'neutral',
};

/** The object the pointer is on in the list (photo id + idx), for its frame. */
const useHovered = create<{ key: string | null; set: (key: string | null) => void }>((set) => ({
  key: null,
  set: (key) => set({ key }),
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
        return (
          <div
            // boxes have no id; their order is the server's
            // oxlint-disable-next-line react/no-array-index-key
            key={i}
            data-testid="analysis-box"
            data-kind={box.kind}
            data-object={box.objectIndex}
            data-lit={lit || undefined}
            className={cx(
              'absolute rounded-[2px] transition-opacity duration-(--duration-quick)',
              lit ? 'border-[3px]' : 'border-2',
              dim && 'opacity-30',
            )}
            style={{ ...boxStyle(box), borderColor: BOX_KIND_COLORS[box.kind] }}
          >
            <span
              className="absolute -top-px -left-px max-w-[12rem] truncate px-1 text-[0.6875rem] leading-4 font-semibold text-black"
              style={{ backgroundColor: BOX_KIND_COLORS[box.kind] }}
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
  if (!data) return null;
  const prefix = `${photoId}:`;
  const highlight = hovered?.startsWith(prefix) ? Number(hovered.slice(prefix.length)) : null;
  return <BoxLayer boxes={framesOf(data)} highlight={highlight} />;
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

function Objects({ photoId, analysis }: { photoId: string; analysis: PhotoAnalysis }) {
  const setHovered = useHovered((s) => s.set);
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
        <ol className="grid border-t border-line text-sm" aria-label="Erkannte Objekte">
          {analysis.objects.map((o) => (
            <li
              key={o.idx}
              data-testid="analysis-object"
              data-idx={o.idx}
              className={cx('grid gap-0.5 border-b border-line py-1.5', o.box && 'hover:bg-surface-hover')}
              onPointerEnter={o.box ? () => setHovered(`${photoId}:${o.idx}`) : undefined}
              onPointerLeave={o.box ? () => setHovered(null) : undefined}
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="w-6 shrink-0 text-ink-muted tabular">{o.idx}</span>
                <span className="min-w-0 flex-1 truncate font-semibold" title={o.label}>
                  {o.label_de}
                </span>
                <span className="tabular">{scoreText(o.score)}</span>
                <Badge
                  tone={o.source === 'local' ? 'neutral' : 'new'}
                  icon={o.source === 'local' ? undefined : Sparkles}
                >
                  {sourceText(o.source)}
                </Badge>
              </div>
              {props.length > 0 ? (
                <p className="pl-8 text-xs text-ink-muted tabular">
                  {props.map((p) => {
                    const score = p.scores[o.idx];
                    return (
                      <span key={p.name} className={cx('mr-3', p.archived && 'line-through')}>
                        <span className="font-mono">{p.name}</span>{' '}
                        {score === null || score === undefined ? '–' : score.toFixed(2).replace('.', ',')}
                      </span>
                    );
                  })}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
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
      {framesOf(analysis).length > 0 ? (
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
