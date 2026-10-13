import { Eye } from 'lucide-react';
import { Button as AriaButton } from 'react-aria-components';
import type { AdminPhoto } from '@/api/types';
import { cx } from '@/ui/cx';
import { GreaseX } from '@/ui/GreaseMarks';
import { Spinner } from '@/ui/Spinner';
import { photoLabel } from '../lib/labels';

/**
 * The 44px Ausblenden / Einblenden toggle in a tile's corner. It shows the state like
 * the contact sheet does: an eye while guests see the photo, the grease-pencil X while it
 * is hidden. The name says what pressing it does.
 */
export function HideToggle({
  photo,
  onToggle,
  isPending = false,
  className,
}: {
  photo: AdminPhoto;
  onToggle: () => void;
  isPending?: boolean;
  className?: string;
}) {
  const label = photoLabel(photo);
  return (
    <AriaButton
      onPress={onToggle}
      isPending={isPending}
      aria-label={photo.hidden ? `${label} einblenden` : `${label} ausblenden`}
      data-testid="toggle"
      data-action={photo.hidden ? 'unhide' : 'hide'}
      className={cx(
        'grid size-11 cursor-pointer place-items-center rounded-full bg-black/60 text-white ring-1 ring-white/30 ring-inset',
        'transition-[background-color,transform] duration-(--duration-quick) outline-none hover:bg-black/75 pressed:scale-95',
        'focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-safelight',
        className,
      )}
    >
      {isPending ? (
        <Spinner />
      ) : photo.hidden ? (
        <GreaseX className="size-6 text-fettstift-hell" />
      ) : (
        <Eye aria-hidden="true" className="size-6" strokeWidth={2} />
      )}
    </AriaButton>
  );
}
