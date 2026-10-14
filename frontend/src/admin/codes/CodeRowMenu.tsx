/**
 * The QR table's row menu (active codes): the code sheet's three downloads, without
 * opening the sheet. A menu button in its own cell; the rest of the row still opens
 * the sheet.
 */
import { EllipsisVertical } from 'lucide-react';
import { Button as AriaButton, Menu, MenuItem, MenuTrigger, Popover, Text } from 'react-aria-components';
import { cx } from '@/ui/cx';
import { iconButtonStyles } from '@/ui/IconButton';
import { Spinner } from '@/ui/Spinner';
import { useSurface } from '@/ui/Surface';
import type { Activities, AdminCode } from './api';
import { EXPORTS, useCodeExport } from './useCodeExport';

const ITEM = cx(
  'flex min-h-11 cursor-pointer items-center gap-3 rounded-small px-3 py-2 text-ink outline-none',
  'hover:bg-surface-hover focus:bg-surface-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus',
);

export function CodeRowMenu({
  code,
  baseUrl,
  activities,
}: {
  code: AdminCode;
  baseUrl: string | null;
  activities: Activities;
}) {
  const surface = useSurface();
  const { busy, run } = useCodeExport(baseUrl, activities);
  return (
    <MenuTrigger>
      <AriaButton
        aria-label={busy ? `${code.name}: wird erstellt…` : `Drucken: ${code.name}`}
        isDisabled={busy !== null}
        data-testid="code-row-menu"
        className={iconButtonStyles({ className: 'size-9 [&_svg]:size-5' })}
      >
        {busy ? <Spinner label="Wird erstellt…" /> : <EllipsisVertical aria-hidden="true" strokeWidth={2} />}
      </AriaButton>
      <Popover
        data-surface={surface}
        placement="bottom end"
        offset={4}
        className={({ isEntering, isExiting }) =>
          cx(
            'w-56 rounded-control border border-line bg-surface-raised text-ink shadow-float outline-none',
            isEntering && 'animate-fade-in',
            isExiting && 'animate-fade-out',
          )
        }
      >
        <Menu
          aria-label={`Drucken: ${code.name}`}
          onAction={(key) => {
            const kind = EXPORTS.find((e) => e.kind === key)?.kind;
            if (kind) void run(code, kind);
          }}
          className="grid max-h-[inherit] gap-0.5 overflow-auto p-1.5 outline-none"
        >
          {EXPORTS.map(({ kind, label, icon: Icon }) => (
            <MenuItem
              key={kind}
              id={kind}
              textValue={label}
              className={ITEM}
              data-testid={`code-menu-${kind}`}
            >
              <Icon aria-hidden="true" className="size-5 shrink-0 text-ink-muted" strokeWidth={2} />
              <Text slot="label" className="min-w-0 flex-1 font-semibold">
                {label}
              </Text>
            </MenuItem>
          ))}
        </Menu>
      </Popover>
    </MenuTrigger>
  );
}
