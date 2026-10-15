/**
 * „Filter zeigen“ in the admin: one remembered preference for every admin view (Live,
 * Fotos, the big photo, a guest's page). Off shows the Fotobox's unfiltered originals.
 * With `photo`: that photo's switch, disabled with the reason when it has no original.
 */
import type { AdminPhoto } from '@/api/types';
import { hasOriginal, noOriginalHint, useAdminShowFilter } from '@/lib/photoFilter';
import { Switch } from '@/ui/Switch';

export function FilterToggle({ photo, className }: { photo?: AdminPhoto; className?: string }) {
  const show = useAdminShowFilter((s) => s.show);
  const setShow = useAdminShowFilter((s) => s.setShow);
  const without = photo !== undefined && !hasOriginal(photo);
  return (
    <Switch
      isSelected={show || without}
      onChange={setShow}
      isDisabled={without}
      description={photo ? noOriginalHint(photo) || undefined : undefined}
      className={className}
      data-testid="filter-toggle"
    >
      Filter zeigen
    </Switch>
  );
}
