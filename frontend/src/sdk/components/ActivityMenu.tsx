/**
 * The activity switcher: the title of an activity's top bar ("Beer Cam ▾") is a menu
 * button. The menu lists the other enabled activities (GET /api/extensions ∩ the
 * registry) and Start, as links (client-side navigation through UiProvider).
 * Test ids: `activity-menu` (the button), `activity-menu-<id>` / `activity-menu-start`.
 */
import { Aperture, Beer, Camera, Check, ChevronDown, House, type LucideIcon } from 'lucide-react';
import { Button, Menu, MenuItem, MenuTrigger, Popover, Separator, Text } from 'react-aria-components';
import { t } from '@/lib/messages.de';
import { cx } from '@/ui/cx';
import { useSurface } from '@/ui/Surface';
import { useActivities } from '../activities';

export interface ActivityMenuProps {
  /** the current activity id, e.g. "beer" */
  currentId: string;
  /** its display title, e.g. "Beer Cam" */
  title: string;
  className?: string;
}

const ICONS: Record<string, LucideIcon> = { beer: Beer, booth: Camera };

const ITEM = cx(
  'flex min-h-12 cursor-pointer items-center gap-3 rounded-small px-3 py-2 text-ink no-underline outline-none',
  'hover:bg-surface-hover focus:bg-surface-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus',
  'disabled:cursor-default',
);

export function ActivityMenu({ currentId, title, className }: ActivityMenuProps) {
  const surface = useSurface();
  const { data } = useActivities();
  const others = (data?.activities ?? []).filter((a) => a.id !== currentId);
  const CurrentIcon = ICONS[currentId] ?? Aperture;
  return (
    <MenuTrigger>
      <Button
        data-testid="activity-menu"
        aria-label={`${title}, Aktivität wechseln`}
        className={cx(
          'inline-flex h-11 max-w-full min-w-0 cursor-pointer items-center gap-1 rounded-control px-2 text-md font-semibold outline-none',
          'transition-[background-color] duration-(--duration-quick) hover:bg-white/10 pressed:bg-white/15',
          'focus-visible:outline-2 focus-visible:outline-focus',
          className,
        )}
      >
        <span translate="no" className="truncate">
          {title}
        </span>
        <ChevronDown aria-hidden="true" className="size-4 shrink-0" strokeWidth={2.25} />
      </Button>
      <Popover
        data-surface={surface}
        placement="bottom start"
        offset={6}
        className={({ isEntering, isExiting }) =>
          cx(
            'w-[min(20rem,calc(100vw-2rem))] rounded-control border border-line bg-surface-raised text-ink shadow-float outline-none',
            isEntering && 'animate-fade-in',
            isExiting && 'animate-fade-out',
          )
        }
      >
        <Menu
          aria-label="Aktivität wechseln"
          className="grid max-h-[inherit] gap-0.5 overflow-auto p-1.5 outline-none"
        >
          <MenuItem id={currentId} textValue={title} isDisabled className={ITEM}>
            <CurrentIcon aria-hidden="true" className="size-5 shrink-0 text-accent-ink" strokeWidth={2} />
            <Text slot="label" translate="no" className="min-w-0 flex-1 truncate font-semibold">
              {title}
            </Text>
            <Check aria-hidden="true" className="size-4 shrink-0 text-accent-ink" strokeWidth={2.5} />
            <span className="sr-only">(hier bist du)</span>
          </MenuItem>
          {others.map((activity) => {
            const Icon = ICONS[activity.id] ?? Aperture;
            return (
              <MenuItem
                key={activity.id}
                id={activity.id}
                href={activity.href}
                textValue={activity.title}
                data-testid={`activity-menu-${activity.id}`}
                className={ITEM}
              >
                <Icon aria-hidden="true" className="size-5 shrink-0 text-ink-muted" strokeWidth={2} />
                <Text slot="label" translate="no" className="min-w-0 flex-1 truncate font-semibold">
                  {activity.title}
                </Text>
              </MenuItem>
            );
          })}
          <Separator className="my-1 h-px border-0 bg-line" />
          <MenuItem
            id="start"
            href="/"
            textValue={t.start}
            data-testid="activity-menu-start"
            className={ITEM}
          >
            <House aria-hidden="true" className="size-5 shrink-0 text-ink-muted" strokeWidth={2} />
            <Text slot="label" className="min-w-0 flex-1 font-semibold">
              {t.start}
            </Text>
          </MenuItem>
        </Menu>
      </Popover>
    </MenuTrigger>
  );
}
