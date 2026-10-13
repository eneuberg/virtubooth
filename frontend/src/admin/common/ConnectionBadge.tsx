import { ConnectionIndicator } from '@/ui/ConnectionIndicator';
import { useConnection } from '../store/connection';

/** The realtime state in a header: dot plus words (verbunden / verbindet… / nur Abfrage / getrennt). */
export function ConnectionBadge({ className }: { className?: string }) {
  const status = useConnection((s) => s.status);
  return (
    <span data-testid="conn" data-state={status} className={className}>
      <ConnectionIndicator status={status} />
    </span>
  );
}
