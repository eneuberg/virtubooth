import { Ban, Pause } from 'lucide-react';
import type { AdminUser } from '@/api/types';
import { Badge } from '@/ui/Badge';

/** Only the exceptional states: Gesperrt / Automatisch gesperrt, Hochladen pausiert. */
export function GuestBadges({
  user,
}: {
  user: Pick<AdminUser, 'banned' | 'auto_banned' | 'uploads_paused'>;
}) {
  return (
    <>
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
    </>
  );
}
