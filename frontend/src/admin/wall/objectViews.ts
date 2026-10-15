/**
 * The three views of a photo's (or a test image's) objects: „Lokales Modell“ (the
 * local detector's own list), „KI“ (the external AI's own list) and „Zusammengeführt“
 * (the merged list the poll rates and the categories count: local and AI objects,
 * duplicates linked). Rows and frames per view, each view with its own frame colour
 * (objectViews.test.ts).
 */
import { sourceText } from '../ml/text';
import type { MergedTestObject, TestImageResult } from '../ml/types';
import { boxOf, type FrameBox } from './text';
import type { PhotoAnalysis } from './types';

export const OBJECT_VIEWS = ['local', 'ai', 'merged'] as const;
export type ObjectView = (typeof OBJECT_VIEWS)[number];

/** Frame colours per view (CSSOM, so the CSP allows them). */
export const OBJECT_VIEW_COLORS: Record<ObjectView, string> = {
  local: '#38bdf8',
  ai: '#c084fc',
  merged: '#ff4fa3',
};

type Box = { x: number; y: number; w: number; h: number };

/** What one source found of a row (a merged row found by both has two). */
export interface RowPart {
  source: string;
  label_de: string;
  score: number;
}

export interface ObjectRow {
  /** merged: the idx; a source's list: the position in it */
  key: number;
  label: string;
  label_de: string;
  score: number;
  box: Box | null;
  /** the sources that found it (a source's list: just that one) */
  sources: string[];
  /** a source's list: the merged entry it is; merged: null */
  mergedIdx: number | null;
  /** merged: what each source found (both scores when both found it) */
  parts: RowPart[];
}

export interface ObjectViews {
  /** null: the local detector did not run */
  local: ObjectRow[] | null;
  /** null: no external AI result */
  ai: ObjectRow[] | null;
  merged: ObjectRow[];
  /** „Claude“, „Mistral“ */
  aiTitle: string;
  aiModel: string | null;
}

/** The merged row was found by the local model and an AI. */
export const fromBoth = (row: Pick<ObjectRow, 'sources'>) =>
  row.sources.includes('local') && row.sources.some((s) => s !== 'local');

/** „lokal + Claude“ */
export const sourcesText = (sources: readonly string[]) => sources.map(sourceText).join(' + ');

const aiSource = (a: Pick<PhotoAnalysis, 'objects_ai' | 'runs'>) =>
  a.objects_ai[0]?.source ?? a.runs.find((r) => r.source !== 'local')?.source ?? 'claude';

const sourceRow = (o: PhotoAnalysis['objects_ai'][number]): ObjectRow => ({
  key: o.pos,
  label: o.label,
  label_de: o.label_de,
  score: o.score,
  box: o.box,
  sources: [o.source],
  mergedIdx: o.merged_idx,
  parts: [{ source: o.source, label_de: o.label_de, score: o.score }],
});

/** The views of a stored photo's analysis. */
export function analysisViews(a: PhotoAnalysis): ObjectViews {
  const source = aiSource(a);
  const localRan = a.runs.some((r) => r.source === 'local' && r.state === 'done');
  const aiRun = a.runs.find((r) => r.source !== 'local' && r.state === 'done');
  const all = [...a.objects_local, ...a.objects_ai];
  return {
    local: localRan || a.objects_local.length > 0 ? a.objects_local.map(sourceRow) : null,
    ai: aiRun || a.objects_ai.length > 0 ? a.objects_ai.map(sourceRow) : null,
    merged: a.objects.map((o) => ({
      key: o.idx,
      label: o.label,
      label_de: o.label_de,
      score: o.score,
      box: o.box,
      sources: o.sources.length > 0 ? o.sources : [o.source],
      mergedIdx: null,
      parts: all
        .filter((s) => s.merged_idx === o.idx)
        .map((s) => ({ source: s.source, label_de: s.label_de, score: s.score })),
    })),
    aiTitle: sourceText(source),
    aiModel: a.objects_ai[0]?.model ?? aiRun?.model ?? null,
  };
}

const row = (
  o: TestImageResult['merged'][number] | NonNullable<TestImageResult['local']>['objects'][number],
  key: number,
  source: string,
  mergedIdx: number | null,
): ObjectRow => ({
  key,
  label: o.label,
  label_de: o.label_de,
  score: o.score,
  box: boxOf(o.box),
  sources: [source],
  mergedIdx,
  parts: [{ source, label_de: o.label_de, score: o.score }],
});

/** The views of a test image's result (the merged list is the server's preview). */
export function testViews(r: TestImageResult): ObjectViews {
  const ext = r.external;
  const idxOf = (pick: (m: MergedTestObject) => number | null, pos: number) =>
    r.merged.find((m) => pick(m) === pos)?.idx ?? null;
  return {
    local: r.local
      ? r.local.objects.map((o, i) =>
          row(
            o,
            i,
            'local',
            idxOf((m) => m.local_pos, i),
          ),
        )
      : null,
    ai: ext
      ? ext.objects.map((o, i) =>
          row(
            o,
            i,
            ext.source,
            idxOf((m) => m.ai_pos, i),
          ),
        )
      : null,
    merged: r.merged.map((m) => {
      const local = m.local_pos === null ? undefined : r.local?.objects[m.local_pos];
      const ai = m.ai_pos === null ? undefined : ext?.objects[m.ai_pos];
      return {
        ...row(m, m.idx, 'local', null),
        sources: m.sources,
        parts: [
          ...(local ? [{ source: 'local', label_de: local.label_de, score: local.score }] : []),
          ...(ai && ext ? [{ source: ext.source, label_de: ai.label_de, score: ai.score }] : []),
        ],
      };
    }),
    aiTitle: sourceText(ext?.source ?? 'claude'),
    aiModel: ext?.model ?? null,
  };
}

/** The view's objects with a box as frames in its colour; a merged entry both found
 * is labelled so („Weinglas · beide“). */
export function viewFrames(rows: readonly ObjectRow[], view: ObjectView): FrameBox[] {
  const out: FrameBox[] = [];
  for (const r of rows) {
    if (!r.box) continue;
    const both = view === 'merged' && fromBoth(r);
    out.push({
      kind: 'object',
      ...r.box,
      label: both ? `${r.label_de} · beide` : r.label_de,
      score: r.score,
      objectIndex: r.key,
      color: OBJECT_VIEW_COLORS[view],
      sources: r.sources.join(','),
      both,
    });
  }
  return out;
}

/** Faces and hands from `boxes` (persons and objects only when there is no object
 * list), plus the chosen view's object frames. */
export function analysisFrames(a: PhotoAnalysis, view: ObjectView): FrameBox[] {
  const rest =
    a.objects.length > 0 ? a.boxes.filter((b) => b.kind !== 'object' && b.kind !== 'person') : a.boxes;
  const views = analysisViews(a);
  return [...rest, ...viewFrames(views[view] ?? [], view)];
}
