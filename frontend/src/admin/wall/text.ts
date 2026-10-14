/**
 * Status lines of the Live Wall admin (text.test.ts).
 */
import { formatDateTime, formatNumber, NBSP } from '@/lib/format';
import type { AnalysisBox, AnalysisStatus, PasswordState } from './types';

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
