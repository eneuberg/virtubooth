/**
 * The small red hint next to every feature that needs the external AI (the „Objekte mit
 * KI“ row, the property poll, the test image's „Auch an die KI schicken“, a category's AI
 * verdict) while it can't work: the master switch „Externe KI verwenden“ is off or no
 * usable key is stored. „Externe KI“ in it scrolls to that card when it is on the page.
 */
import { CircleAlert } from 'lucide-react';
import { cx } from '@/ui/cx';
import { aiUnavailable } from './forms';
import type { LlmStatus } from './types';

/** The card's section (Card renders data-testid="wall-card-<id>"). */
export const EXTERNAL_AI_CARD = 'externe-ki';

function goToCard() {
  const card = document.querySelector<HTMLElement>(`[data-testid="wall-card-${EXTERNAL_AI_CARD}"]`);
  if (!card) return;
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export function ExternalAiHint({
  status,
  className,
  where = 'card',
}: {
  status: Pick<LlmStatus, 'config' | 'key'> | undefined;
  className?: string;
  /** `card`: the card is on this page (a link scrolls to it); `elsewhere`: names the place */
  where?: 'card' | 'elsewhere';
}) {
  const why = aiUnavailable(status);
  if (!why) return null;
  const place =
    where === 'card' ? (
      <button
        type="button"
        onClick={goToCard}
        className="cursor-pointer font-semibold underline underline-offset-2 outline-none focus-visible:outline-2 focus-visible:outline-focus"
      >
        ‚Externe KI‘
      </button>
    ) : (
      <span className="font-semibold">‚ML-Pipeline › Externe KI‘</span>
    );
  return (
    <p
      className={cx('flex items-start gap-1.5 text-xs text-danger', className)}
      data-testid="ml-ai-off-hint"
      data-why={why}
    >
      <CircleAlert aria-hidden="true" className="mt-px size-3.5 shrink-0" />
      <span>
        {why === 'off' ? (
          <>Externe KI ist aus – unter {place} einschalten, um das zu nutzen.</>
        ) : (
          <>Kein gültiger API-Schlüssel – unter {place} eintragen, um das zu nutzen.</>
        )}
      </span>
    </p>
  );
}
