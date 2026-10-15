/**
 * Status lines of the Live Wall admin (text.test.ts).
 */
import { formatDateTime, formatNumber, formatRelative, NBSP } from '@/lib/format';
import type { AnalysisBox, AnalysisStatus, PasswordState, PhotoAnalysis } from './types';

/** "1 Wand offen", "3 Wände offen" */
export function openWallsText(n: number): string {
  return `${formatNumber(n)}${NBSP}${n === 1 ? 'Wand' : 'Wände'} offen`;
}

export function passwordText(password: PasswordState): string {
  if (!password.set) return 'Noch kein Passwort: die Live-Wall ist gesperrt.';
  return password.changed_at
    ? `Passwort gesetzt am ${formatDateTime(password.changed_at)}.`
    : 'Passwort gesetzt.';
}

/** "12 fertig · 3 warten · 1 fehlgeschlagen" (running ones wait too) */
export function countsText(counts: AnalysisStatus['counts']): string {
  const waiting = counts.pending + counts.running;
  return [
    `${formatNumber(counts.done)} fertig`,
    `${formatNumber(waiting)} warten`,
    `${formatNumber(counts.failed)} fehlgeschlagen`,
  ].join(' · ');
}

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const pct = (v: number) => `${(v * 100).toFixed(2)}%`;

/** A box (0..1, top-left) as CSS geometry in % of the photo; the part on the photo. */
export function boxStyle(box: Pick<AnalysisBox, 'x' | 'y' | 'w' | 'h'>): {
  left: string;
  top: string;
  width: string;
  height: string;
} {
  const x0 = clamp01(box.x);
  const y0 = clamp01(box.y);
  return {
    left: pct(x0),
    top: pct(y0),
    width: pct(clamp01(box.x + box.w) - x0),
    height: pct(clamp01(box.y + box.h) - y0),
  };
}

/** A raw fact for the "Rohwerte" list: integers as they are, fractions to 3 places. */
export function factValue(value: number): string {
  return Number.isInteger(value) ? formatNumber(value) : value.toFixed(3);
}

/** "gerade eben", "vor 3 Min.": when the worker last beat; null when it never did. */
export function lastBeatText(lastBeatAt: string | null, now = Date.now()): string {
  return lastBeatAt ? formatRelative(lastBeatAt, now) : 'noch nie';
}

/** "1.234 Fotos" since the worker started */
export function processedText(n: number): string {
  return `${formatNumber(n)}${NBSP}${n === 1 ? 'Foto' : 'Fotos'}`;
}

/** "412 MB" */
export function memoryText(mb: number): string {
  return `${formatNumber(Math.round(mb))}${NBSP}MB`;
}

type Box = { x: number; y: number; w: number; h: number };

/** An object's box as {x, y, w, h}, whether it came as a tuple (test runs) or an object. */
export function boxOf(box: Box | [number, number, number, number] | null): Box | null {
  if (!box) return null;
  if (Array.isArray(box)) {
    const [x, y, w, h] = box;
    return { x, y, w, h };
  }
  return box;
}

/** A frame on the photo; object frames know the object's idx (hover highlight), and
 * the object views (objectViews.ts) give theirs a colour of their own. */
export type FrameBox = AnalysisBox & {
  objectIndex?: number;
  /** outline colour; default: the kind's */
  color?: string;
  /** the sources that found the object („local,claude“) */
  sources?: string;
  /** a merged entry both the local model and an AI found */
  both?: boolean;
};

/** Objects with a box as frames of kind "object", labelled in German. */
export function objectBoxes(
  objects: ReadonlyArray<{
    label_de: string;
    score: number;
    box: Box | [number, number, number, number] | null;
    idx?: number;
  }>,
): FrameBox[] {
  const out: FrameBox[] = [];
  objects.forEach((o, i) => {
    const b = boxOf(o.box);
    if (b) out.push({ kind: 'object', ...b, label: o.label_de, score: o.score, objectIndex: o.idx ?? i });
  });
  return out;
}

/**
 * Faces and hands from `boxes`, plus every object with a box. Persons and objects are
 * in the object list now (N2): when there is one, their `boxes` copies are dropped.
 */
export function framesOf(analysis: Pick<PhotoAnalysis, 'boxes' | 'objects'>): FrameBox[] {
  const rest =
    analysis.objects.length > 0
      ? analysis.boxes.filter((b) => b.kind !== 'object' && b.kind !== 'person')
      : analysis.boxes;
  return [...rest, ...objectBoxes(analysis.objects)];
}
