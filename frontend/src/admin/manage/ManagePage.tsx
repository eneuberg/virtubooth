/**
 * /admin/manage: the light-table area (Leuchttisch), desktop first. A sidebar with the
 * sections on desktop; on phones a section strip and the same bottom bar as the live
 * screen. Sections keep the pre-overhaul `?tab=` names (manageUrl.ts).
 */
import {
  Archive,
  AtSign,
  Gauge,
  Images,
  LayoutGrid,
  LogOut,
  Radio,
  QrCode,
  ScrollText,
  Settings,
  ShieldBan,
  Upload,
  Users,
} from 'lucide-react';
import { useEffect, useRef, type ComponentType } from 'react';
import { Link } from 'react-aria-components';
import { useSearchParams } from 'wouter';
import type { AdminStats } from '@/api/types';
import { t } from '@/lib/messages.de';
import { BottomBar, bottomBarInset } from '@/ui/BottomBar';
import { Button, LinkButton } from '@/ui/Button';
import { cx } from '@/ui/cx';
import { IconButton, iconButtonStyles } from '@/ui/IconButton';
import { SidebarNav } from '@/ui/SidebarNav';
import { CodesSection } from '../codes/CodesSection';
import { AdminFrame } from '../common/AdminFrame';
import { ConnectionBadge } from '../common/ConnectionBadge';
import { OverviewSection } from '../dashboard/OverviewSection';
import { QuickControls } from '../dashboard/QuickControls';
import { StatusStrip } from '../dashboard/StatusStrip';
import { DESKTOP, useMediaQuery } from '../lib/browser';
import { logout } from '../store/actions';
import { useStats } from '../store/hooks';
import { useDocumentSurface } from '../surface';
import { SettingsSection } from '../settings/SettingsSection';
import { openUploadSheet } from '../uploads/sheetStore';
import { UploadStatusPill } from '../uploads/UploadStatusPill';
import { AuditSection } from './AuditSection';
import { BansSection } from './BansSection';
import { ExportSection } from './ExportSection';
import { GuestsSection } from './GuestsSection';
import { InstagramSection } from './InstagramSection';
import { parseSection, sectionHref, type Section } from './manageUrl';
import { PhotosSection } from './PhotosSection';

const SECTION_VIEW: Record<Section, ComponentType> = {
  fotos: PhotosSection,
  gaeste: GuestsSection,
  instagram: InstagramSection,
  sperren: BansSection,
  protokoll: AuditSection,
  qr: CodesSection,
  export: ExportSection,
  uebersicht: OverviewSection,
  einstellungen: SettingsSection,
};

function navItem(id: Section, label: string, icon: typeof Images, count?: number) {
  return { id, label, icon, href: sectionHref(id), count };
}

function navItems(stats: AdminStats | undefined) {
  return [
    navItem('uebersicht', 'Übersicht', Gauge),
    navItem('fotos', 'Fotos', Images, stats?.photos),
    navItem('gaeste', 'Gäste', Users, stats?.guests),
    navItem('instagram', 'Instagram', AtSign, stats?.instagram_handles),
    navItem('sperren', 'Sperren', ShieldBan, stats ? stats.banned + stats.fingerprint_bans : undefined),
    navItem('protokoll', 'Protokoll', ScrollText),
    navItem('qr', 'QR-Codes', QrCode),
    navItem('export', 'Export', Archive),
  ];
}

const TOAST =
  'bottom-[calc(4.75rem+env(safe-area-inset-bottom))] lg:right-6 lg:bottom-6 lg:left-auto lg:mx-0';

export function ManagePage() {
  useDocumentSurface('light');
  return (
    <AdminFrame toastClassName={TOAST}>
      <ManageShell />
    </AdminFrame>
  );
}

/** Phones and tablets: the sections as a scrolling strip of links. */
function SectionStrip({ current, stats }: { current: Section; stats: AdminStats | undefined }) {
  return (
    <nav aria-label="Bereiche der Verwaltung" className="border-b border-line">
      <ul className="flex [scrollbar-width:none] gap-1 overflow-x-auto px-2 scroll-shadows-x">
        {navItems(stats).map((item) => {
          const active = item.id === current;
          const Icon = item.icon;
          return (
            <li key={item.id} className="shrink-0">
              <Link
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={cx(
                  'relative flex h-12 items-center gap-1.5 px-3 text-sm font-semibold whitespace-nowrap no-underline outline-none',
                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus',
                  'after:absolute after:inset-x-2 after:bottom-0 after:h-[3px] after:rounded-t-full',
                  active ? 'text-ink after:bg-ink' : 'text-ink-muted hover:text-ink',
                )}
              >
                <Icon aria-hidden="true" className="size-4.5" strokeWidth={2} />
                {item.label}
                {item.count === undefined ? null : (
                  <span className="font-normal text-ink-muted tabular">{item.count}</span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function ManageShell() {
  const [params] = useSearchParams();
  const section = parseSection(params.get('tab'));
  const desktop = useMediaQuery(DESKTOP);
  const { data: stats } = useStats();
  const View = SECTION_VIEW[section];

  // a new section: its heading gets the focus (not on the first load)
  const shown = useRef<Section | null>(null);
  useEffect(() => {
    if (shown.current !== null && shown.current !== section) {
      document.getElementById('section-title')?.focus();
    }
    shown.current = section;
  }, [section]);

  return (
    <div className={cx('min-h-dvh', desktop ? 'flex' : bottomBarInset)}>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-(--z-toast) focus:rounded-control focus:bg-ink focus:px-4 focus:py-2 focus:text-surface"
      >
        Zum Inhalt
      </a>
      {desktop ? (
        <SidebarNav
          label="Verwaltung"
          currentId={section}
          items={navItems(stats)}
          className="sticky top-0 h-dvh"
          header={
            <div className="grid gap-1">
              <span className="text-md font-bold">Verwaltung</span>
              <ConnectionBadge />
            </div>
          }
          footer={
            <>
              <QuickControls className="mb-1 grid-flow-row" />
              <UploadStatusPill long className="mb-2 w-full" />
              <LinkButton href="/live" variant="quiet" size="xs" icon={Radio} className="justify-start">
                Live öffnen
              </LinkButton>
              <LinkButton
                href="/manage?tab=einstellungen"
                variant="quiet"
                size="xs"
                icon={Settings}
                className="justify-start"
                aria-current={section === 'einstellungen' ? 'page' : undefined}
                data-testid="settings-link"
              >
                Einstellungen
              </LinkButton>
              <Button
                variant="quiet"
                size="xs"
                icon={LogOut}
                className="justify-start"
                onPress={() => void logout()}
                data-testid="logout"
              >
                Abmelden
              </Button>
            </>
          }
        />
      ) : (
        <header className="sticky top-0 z-(--z-sticky) bg-surface pt-[env(safe-area-inset-top)] landscape-phone:static">
          <div className="flex items-center gap-2 py-2 pr-2 pl-4">
            <div className="grid min-w-0">
              <span className="truncate text-lg font-bold">Verwaltung</span>
              <ConnectionBadge />
            </div>
            <UploadStatusPill className="ml-auto" />
            <Link
              href="/manage?tab=einstellungen"
              aria-label="Einstellungen"
              aria-current={section === 'einstellungen' ? 'page' : undefined}
              className={iconButtonStyles()}
              data-testid="settings-link"
            >
              <Settings aria-hidden="true" strokeWidth={2} />
            </Link>
            <IconButton label="Abmelden" icon={LogOut} onPress={() => void logout()} data-testid="logout" />
          </div>
          <QuickControls className="px-3 pb-2" />
          <StatusStrip />
          <SectionStrip current={section} stats={stats} />
        </header>
      )}
      <main id="main" tabIndex={-1} className="min-w-0 flex-1 outline-none">
        {desktop ? <StatusStrip className="sticky top-0 z-(--z-sticky)" /> : null}
        <View />
      </main>
      {desktop ? null : (
        <BottomBar
          label="Bereiche"
          currentId="manage"
          items={[
            { id: 'live', label: 'Live', icon: Images, href: '/live' },
            { id: 'upload', label: t.upload, icon: Upload, onPress: openUploadSheet },
            { id: 'manage', label: 'Verwaltung', icon: LayoutGrid, href: '/manage' },
          ]}
        />
      )}
    </div>
  );
}
