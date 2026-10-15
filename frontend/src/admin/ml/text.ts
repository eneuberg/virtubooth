/**
 * Lines of the ML-Pipeline section (text.test.ts): sizes, durations, queue, money.
 */
import { formatNumber, NBSP } from '@/lib/format';
import type { AnalysisStatus, AnalyzerStats } from '../wall/types';
import type { LlmModel, UsageRow } from './types';

/** "12 MB", "3,4 MB" */
export function sizeText(mb: number): string {
  const n = mb >= 10 ? Math.round(mb) : Math.round(mb * 10) / 10;
  return `${formatNumber(n)}${NBSP}MB`;
}

const ms = (n: number) => `${formatNumber(Math.round(n))}${NBSP}ms`;
const photos = (n: number) => `${formatNumber(n)}${NBSP}${n === 1 ? 'Foto' : 'Fotos'}`;

/** "Ø 340 ms · zuletzt 290 ms · 128 Fotos · 2 Fehler" (missing parts left out) */
export function statsText(stats: AnalyzerStats): string {
  const parts: string[] = [];
  if (stats.avg_ms !== null) parts.push(`Ø ${ms(stats.avg_ms)}`);
  if (stats.last_ms !== null) parts.push(`zuletzt ${ms(stats.last_ms)}`);
  parts.push(photos(stats.processed));
  parts.push(`${formatNumber(stats.errors)}${NBSP}Fehler`);
  return parts.join(' · ');
}

/** "12 s", "3 min", "2 h" */
export function ageText(seconds: number): string {
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))}${NBSP}s`;
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)}${NBSP}min`;
  return `${Math.round(seconds / 3600)}${NBSP}h`;
}

/** "Warteschlange: 3 Fotos (ältestes seit 12 s)", "Warteschlange: leer" */
export function queueText(queue: AnalysisStatus['queue']): string {
  const waiting = queue.pending;
  if (waiting === 0)
    return queue.running > 0 ? 'Warteschlange: leer, 1 Foto in Arbeit' : 'Warteschlange: leer';
  const oldest =
    queue.oldest_pending_s === null
      ? ''
      : ` (${waiting === 1 ? 'seit' : 'ältestes seit'} ${ageText(queue.oldest_pending_s)})`;
  return `Warteschlange: ${photos(waiting)}${oldest}`;
}

const USD = new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'USD' });
const USD_SMALL = new Intl.NumberFormat('de-DE', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 4,
});

/** "1,25 $"; below a cent with up to 4 places ("0,0022 $") */
export function usdText(usd: number): string {
  return usd > 0 && usd < 0.01 ? USD_SMALL.format(usd) : USD.format(usd);
}

/** "Claude Haiku 5.5 · 1 $ / 5 $ pro Mio. Tokens (ein/aus)" */
const dollars = (n: number) => `${formatNumber(n)}${NBSP}$`;

export function modelText(model: LlmModel): string {
  return `${model.title} · ${dollars(model.usd_in_mtok)} / ${dollars(model.usd_out_mtok)} pro Mio. Tokens`;
}

/** "Erkennung", "Eigenschaft „coolness“", "Urteil „coolstes_objekt“", "Test" */
export function usageKindText(row: Pick<UsageRow, 'kind' | 'ref'>): string {
  const ref = row.ref ? ` „${row.ref}“` : '';
  switch (row.kind) {
    case 'detect':
      return 'Erkennung';
    case 'property':
      return `Eigenschaft${ref}`;
    case 'verdict':
      return `Urteil${ref}`;
    case 'test':
      return 'Test';
    default:
      return `${row.kind}${ref}`;
  }
}

/** "82 %" */
export function scoreText(score: number): string {
  return `${Math.round(score * 100)}${NBSP}%`;
}

/** „lokal“ / „Claude“ / the source id */
export function sourceText(source: string): string {
  if (source === 'local') return 'lokal';
  if (source === 'claude') return 'Claude';
  if (source === 'mistral') return 'Mistral';
  return source;
}

/** "basic 12 ms · faces 150 ms" */
export function durationsText(durations: Record<string, number>, titles?: Map<string, string>): string {
  return Object.entries(durations)
    .map(([name, n]) => `${titles?.get(name) ?? name} ${ms(n)}`)
    .join(' · ');
}
