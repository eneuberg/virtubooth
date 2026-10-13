/**
 * Admin page placeholders. OWNER: wave 2 "AD" (replace with Login, Live, Manage/*, User,
 * Export, Instagram board, upload controls; see docs/overhaul/design/mockups/04–07).
 */
import {
  Archive,
  AtSign,
  Images,
  LayoutGrid,
  LogOut,
  Radio,
  ScrollText,
  ShieldBan,
  Upload,
  Users,
} from 'lucide-react';
import { BottomBar, bottomBarInset } from '@/ui/BottomBar';
import { Button, LinkButton } from '@/ui/Button';
import { ConnectionIndicator } from '@/ui/ConnectionIndicator';
import { cx } from '@/ui/cx';
import { EmptyState } from '@/ui/EmptyState';
import { SidebarNav } from '@/ui/SidebarNav';
import { SkeletonGrid } from '@/ui/Skeleton';
import { StatusPill } from '@/ui/StatusPill';
import { TextField } from '@/ui/TextField';
import { useDocumentSurface } from './surface';

export function LoginPage() {
  useDocumentSurface('dark');
  return (
    <main className="mx-auto grid min-h-dvh max-w-[24rem] content-center gap-5 px-6">
      <h1 className="text-2xl font-bold">Admin</h1>
      <TextField label="Passwort" type="password" autoComplete="current-password" name="password" />
      <Button variant="primary" size="lg" block isDisabled>
        Anmelden
      </Button>
    </main>
  );
}

export function LivePage() {
  useDocumentSurface('dark');
  return (
    <div className={cx('min-h-dvh', bottomBarInset)}>
      <header className="flex items-center gap-3 border-b border-line py-2 pr-3 pl-4">
        <div className="grid min-w-0">
          <span className="flex items-baseline gap-2.5">
            <h1 className="text-lg font-bold">Live</h1>
            <ConnectionIndicator status="connecting" />
          </span>
        </div>
        <StatusPill state="on" className="ml-auto" />
      </header>
      <SkeletonGrid
        count={6}
        className="p-2 landscape-phone:grid-cols-[repeat(auto-fill,minmax(8rem,1fr))]"
      />
      <BottomBar
        label="Bereiche"
        currentId="live"
        items={[
          { id: 'live', label: 'Live', icon: Images, href: '/live' },
          { id: 'upload', label: 'Hochladen', icon: Upload, onPress: () => undefined },
          { id: 'manage', label: 'Verwaltung', icon: LayoutGrid, href: '/manage' },
        ]}
      />
    </div>
  );
}

const NAV = [
  { id: 'fotos', label: 'Fotos', icon: Images, href: '/manage?tab=fotos' },
  { id: 'gaeste', label: 'Gäste', icon: Users, href: '/manage?tab=gaeste' },
  { id: 'instagram', label: 'Instagram', icon: AtSign, href: '/manage?tab=instagram' },
  { id: 'sperren', label: 'Sperren', icon: ShieldBan, href: '/manage?tab=sperren' },
  { id: 'protokoll', label: 'Protokoll', icon: ScrollText, href: '/manage?tab=protokoll' },
  { id: 'export', label: 'Export', icon: Archive, href: '/manage?tab=export' },
] as const;

export function ManagePage() {
  useDocumentSurface('light');
  return (
    <div className="flex min-h-dvh">
      <SidebarNav
        label="Verwaltung"
        currentId="fotos"
        items={NAV}
        className="sticky top-0 h-dvh max-lg:hidden"
        footer={
          <>
            <StatusPill state="on" label="Hochladen: an" className="w-full" />
            <LinkButton href="/live" variant="quiet" size="xs" icon={Radio} className="justify-start">
              Live öffnen
            </LinkButton>
            <Button variant="quiet" size="xs" icon={LogOut} className="justify-start">
              Abmelden
            </Button>
          </>
        }
      />
      <main className="min-w-0 flex-1 px-6 py-5">
        <h1 className="text-xl font-bold">Fotos</h1>
        <EmptyState icon={Images} title="Noch keine Fotos">
          Sobald jemand ein Foto macht, erscheint es hier.
        </EmptyState>
      </main>
    </div>
  );
}

export function UserPage() {
  useDocumentSurface('light');
  return (
    <main className="mx-auto grid max-w-[67.5rem] gap-6 px-4 py-6">
      <h1 className="text-2xl font-bold">Gast</h1>
      <EmptyState title="Gast wird geladen…" />
    </main>
  );
}
