/**
 * The external AI's two parts share how they show their state and cost: „Objekte mit KI“
 * (the Modelle card) and „Eigenschaften abfragen“ (the Eigenschaften card).
 */
import { Badge } from '@/ui/Badge';
import { DETECTION_LABELS, partOffReason, partUsage, POLLER_LABELS, type LlmPart } from './forms';
import { usdText } from './text';
import type { LlmStatus, PollerState } from './types';

const PART_TONE: Record<PollerState, 'neutral' | 'ok' | 'amber' | 'mark'> = {
  off: 'neutral',
  idle: 'ok',
  running: 'amber',
  blocked: 'mark',
};

/** „bisher 0,40 $ · 4 Aufrufe“ */
export function CostText({ status, part }: { status: LlmStatus; part: LlmPart }) {
  const { calls, usd } = partUsage(status, part);
  return (
    <span className="text-ink-muted tabular" data-testid={`ml-${part}-cost`}>
      bisher {usdText(usd)} · {calls} {calls === 1 ? 'Aufruf' : 'Aufrufe'}
    </span>
  );
}

/** A part's state badge: off (and why) or what it does now. */
export function PartState({
  status,
  part,
  state,
  partOn,
}: {
  status: LlmStatus;
  part: LlmPart;
  state: PollerState;
  partOn: boolean;
}) {
  const why = state === 'off' ? partOffReason(status, partOn) : null;
  const labels = part === 'poll' ? POLLER_LABELS : DETECTION_LABELS;
  return (
    <span
      className="inline-flex flex-wrap items-center gap-2"
      data-testid={`ml-${part}-state`}
      data-state={state}
    >
      <Badge tone={PART_TONE[state]}>{labels[state]}</Badge>
      {why && why !== 'ausgeschaltet' ? <span className="text-ink-muted">{why}</span> : null}
    </span>
  );
}
