/**
 * The Live screen's analysis chips under a photo tile, as words (pure;
 * summaryText.test.ts): „3 Personen“, „2 lächeln“, „Flasche, Becher“, the guest's
 * opt-outs, the categories the photo wins (they open, CategoryWinDetails.tsx) and
 * „Objekterkennung aus“ for a photo analysed with object detection off. The full
 * analysis is in the viewer.
 */
import { formatNumber, NBSP, pluralize } from '@/lib/format';
import type { CategoryWin, PhotoAnalysisSummary } from './types';

export type ChipTone = 'plain' | 'muted' | 'mark' | 'win';

export interface Chip {
  id: string;
  text: string;
  tone: ChipTone;
  /** a category the photo wins: the chip opens it (§8.6) */
  win?: CategoryWin;
}

/** How many object labels a tile names before „+2“. */
const MAX_OBJECTS = 3;
/** happy_max from this on reads as „fröhlich“ (the emotion analyzer's 0..1 score) */
const HAPPY = 0.5;

const GESTURES: ReadonlyArray<[string, string]> = [
  ['thumbs_up', 'Daumen hoch'],
  ['peace', 'Peace'],
  ['rock', 'Rock'],
];

function count(facts: Record<string, number>, key: string): number {
  const v = facts[key];
  return typeof v === 'number' && Number.isFinite(v) ? Math.round(v) : 0;
}

/** Distinct object labels in list order, people left out (they are counted). */
function objectText(objects: PhotoAnalysisSummary['objects']): string | null {
  const labels = [...new Set(objects.map((o) => o.label_de).filter((l) => l && l !== 'Person'))];
  if (labels.length === 0) return null;
  const shown = labels.slice(0, MAX_OBJECTS).join(', ');
  const more = labels.length - MAX_OBJECTS;
  return more > 0 ? `${shown} +${formatNumber(more)}` : shown;
}

export function analysisChips(summary: PhotoAnalysisSummary): Chip[] {
  const chips: Chip[] = [];
  const { facts } = summary;
  if (summary.opt_out.analysis) chips.push({ id: 'opt-out', text: 'Keine Auswertung (Gast)', tone: 'mark' });
  if (summary.opt_out.external_ai) chips.push({ id: 'no-ai', text: 'Keine externe KI', tone: 'mark' });
  if (summary.state === 'pending' || summary.state === 'running') {
    chips.push({
      id: 'state',
      text: summary.state === 'running' ? 'Analyse läuft…' : 'Analyse wartet',
      tone: 'muted',
    });
    return chips;
  }
  if (summary.state === 'failed') {
    chips.push({ id: 'state', text: 'Analyse fehlgeschlagen', tone: 'mark' });
    return chips;
  }
  if (summary.state === 'skipped') {
    chips.push({ id: 'state', text: 'Nicht ausgewertet', tone: 'muted' });
    return chips;
  }
  for (const win of summary.wins) {
    chips.push({ id: `win-${win.id}`, text: `${win.emoji}${NBSP}${win.title}`, tone: 'win', win });
  }
  const people = count(facts, 'people') || count(facts, 'faces');
  if (people > 0) chips.push({ id: 'people', text: pluralize(people, 'Person', 'Personen'), tone: 'plain' });
  const smiles = count(facts, 'smiles');
  if (smiles > 0) chips.push({ id: 'smiles', text: `${formatNumber(smiles)}${NBSP}lächeln`, tone: 'plain' });
  if ((facts['happy_max'] ?? 0) >= HAPPY) chips.push({ id: 'happy', text: 'fröhlich', tone: 'plain' });
  const hands = count(facts, 'hands');
  if (hands > 0) chips.push({ id: 'hands', text: pluralize(hands, 'Hand', 'Hände'), tone: 'plain' });
  for (const [key, name] of GESTURES) {
    if (count(facts, key) > 0) chips.push({ id: key, text: name, tone: 'plain' });
  }
  const glasses = count(facts, 'glasses');
  if (glasses > 0)
    chips.push({ id: 'glasses', text: pluralize(glasses, 'Brille', 'Brillen'), tone: 'plain' });
  const hats = count(facts, 'hats');
  if (hats > 0) chips.push({ id: 'hats', text: pluralize(hats, 'Hut', 'Hüte'), tone: 'plain' });
  const objects = objectText(summary.objects);
  if (objects) chips.push({ id: 'objects', text: objects, tone: 'plain' });
  // analysed with object detection „Aus“: say so instead of „Nichts erkannt“ (§8.7)
  if (summary.objects_off) chips.push({ id: 'objects-off', text: 'Objekterkennung aus', tone: 'muted' });
  else if (chips.every((c) => c.tone === 'mark'))
    chips.push({ id: 'none', text: 'Nichts erkannt', tone: 'muted' });
  return chips;
}

/** The chips in one line for screen readers (the tile's description). */
export function chipsLabel(chips: readonly Chip[]): string {
  return chips.map((c) => c.text.replaceAll(NBSP, ' ')).join(', ');
}
