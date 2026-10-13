/**
 * The activity switcher: the camera top-bar title ("Beer Cam ▾") opens a sheet that
 * lists the enabled activities and Start. OWNER: wave 2 "GP".
 */
import { ChevronDown } from 'lucide-react';
import { Button } from 'react-aria-components';

export interface ActivityMenuProps {
  /** the current activity id, e.g. "beer" */
  currentId: string;
  /** its display title, e.g. "Beer Cam" */
  title: string;
}

export function ActivityMenu({ currentId, title }: ActivityMenuProps) {
  // TODO(wave 2, GP): Sheet with GET /api/extensions entries + Start
  void currentId;
  return (
    <Button className="inline-flex h-11 min-w-0 cursor-pointer items-center gap-1 rounded-control px-2 text-md font-semibold outline-none focus-visible:outline-2 focus-visible:outline-focus">
      <span translate="no" className="truncate">
        {title}
      </span>
      <ChevronDown aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.25} />
    </Button>
  );
}
