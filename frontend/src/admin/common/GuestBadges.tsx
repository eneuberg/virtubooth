import { Ban, BotOff, EyeOff, PartyPopper, Pause } from 'lucide-react';
import type { AdminUser } from '@/api/types';
import { Badge } from '@/ui/Badge';
import { HOST_MARK } from '../hostGuest/marks';

/**
 * The admin guest („Admin-Gast“, the host's own guest identity), then only the exceptional states: Gesperrt / Automatisch gesperrt, Hochladen pausiert, and
 * the guest's own choices „Gast möchte keine Auswertung“ and „Keine externe KI“ (shown
 * when the user carries them; older shapes without the fields show nothing).
 */
export function GuestBadges({
  user,
}: {
  user: Pick<AdminUser, 'banned' | 'auto_banned' | 'uploads_paused'> &
    Partial<Pick<AdminUser, 'analysis_opt_out' | 'ai_opt_out' | 'is_host'>>;
}) {
  return (
    <>
      {user.is_host ? (
        <span data-testid="host-badge" className="inline-flex">
          <Badge tone="new" icon={PartyPopper}>
            {HOST_MARK}
          </Badge>
        </span>
      ) : null}
      {user.banned ? (
        <span data-testid={user.auto_banned ? 'auto-ban' : 'ban-badge'} className="inline-flex">
          <Badge tone="mark" icon={Ban}>
            {user.auto_banned ? 'Automatisch gesperrt' : 'Gesperrt'}
          </Badge>
        </span>
      ) : null}
      {user.uploads_paused && !user.banned ? (
        <span data-testid="paused-badge" className="inline-flex">
          <Badge tone="amber" icon={Pause}>
            Hochladen pausiert
          </Badge>
        </span>
      ) : null}
      {user.analysis_opt_out ? (
        <span data-testid="analysis-opt-out-badge" className="inline-flex">
          <Badge icon={EyeOff}>Gast möchte keine Auswertung</Badge>
        </span>
      ) : null}
      {user.ai_opt_out ? (
        <span data-testid="ai-opt-out-badge" className="inline-flex">
          <Badge icon={BotOff}>Keine externe KI</Badge>
        </span>
      ) : null}
    </>
  );
}
