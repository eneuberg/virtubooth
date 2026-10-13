/**
 * UI gallery: every component of src/ui in its states, on both surfaces.
 * Dev only: `pnpm dev` → /ui.html (or /__ui), `pnpm build:gallery` for a CSP check.
 * Never part of the production build input. `?show=sheet|confirm|join|toast|notice`
 * opens an overlay on load (for screenshots).
 */
import {
  Archive,
  AtSign,
  Ban,
  Beer,
  Camera,
  CupSoda,
  Download,
  Eye,
  EyeOff,
  Images,
  LayoutGrid,
  LogOut,
  OctagonPause,
  Radio,
  ScrollText,
  Search,
  ShieldBan,
  SwitchCamera,
  Timer,
  Trash2,
  Upload,
  Users,
  WifiOff,
} from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { formatCount, frameLabel } from '@/lib/format';
import { Badge } from '@/ui/Badge';
import { BottomBar } from '@/ui/BottomBar';
import { Button, LinkButton } from '@/ui/Button';
import { Checkbox } from '@/ui/Checkbox';
import { ConfirmDialog } from '@/ui/ConfirmDialog';
import { ConnectionIndicator } from '@/ui/ConnectionIndicator';
import { Countdown } from '@/ui/Countdown';
import { DataTable, type DataColumn } from '@/ui/DataTable';
import { EmptyState } from '@/ui/EmptyState';
import { FilmEdge } from '@/ui/FilmEdge';
import { HelpDisclosure } from '@/ui/HelpDisclosure';
import { IconButton } from '@/ui/IconButton';
import { Notice } from '@/ui/Notice';
import { PhotoTile } from '@/ui/PhotoTile';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { Select } from '@/ui/Select';
import { Sheet } from '@/ui/Sheet';
import { Shutter } from '@/ui/Shutter';
import { SidebarNav } from '@/ui/SidebarNav';
import { Skeleton, SkeletonGrid } from '@/ui/Skeleton';
import { Progress, Spinner } from '@/ui/Spinner';
import { StatusPill } from '@/ui/StatusPill';
import { Surface, type SurfaceTone } from '@/ui/Surface';
import { Switch } from '@/ui/Switch';
import { TabList, TabPanel, Tabs } from '@/ui/Tabs';
import { TextField } from '@/ui/TextField';
import { showToast, ToastSlot } from '@/ui/Toast';
import { GUESTS, PHOTOS, type SampleGuest } from './sample';

const show = new URLSearchParams(location.search).get('show');

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-h`} className="grid gap-4 border-t border-line pt-6">
      <h2 id={`${id}-h`} className="text-xl font-bold">
        {title}
      </h2>
      {children}
    </section>
  );
}

/** The same content on Rotlicht and on Leuchttisch, side by side from 1024px. */
function Both({ children }: { children: (tone: SurfaceTone) => ReactNode }) {
  return (
    <div className="grid gap-px overflow-hidden rounded-control border border-line lg:grid-cols-2">
      {(['dark', 'light'] as const).map((tone) => (
        <Surface key={tone} tone={tone} className="grid content-start gap-4 p-5">
          <p className="text-xs text-ink-muted">
            {tone === 'dark' ? 'Rotlicht (dunkel)' : 'Leuchttisch (hell)'}
          </p>
          {children(tone)}
        </Surface>
      ))}
    </div>
  );
}

function Stage({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-wrap items-end gap-6 bg-kamera p-5 text-papier ${className ?? ''}`}>
      {children}
    </div>
  );
}

const SWATCHES = [
  ['kamera', 'bg-kamera'],
  ['rot-950', 'bg-rot-950'],
  ['rot-900 Rotlicht', 'bg-rot-900'],
  ['rot-800', 'bg-rot-800'],
  ['rot-700', 'bg-rot-700'],
  ['papier', 'bg-papier'],
  ['papier-muted', 'bg-papier-muted'],
  ['safelight', 'bg-safelight'],
  ['fettstift', 'bg-fettstift'],
  ['fettstift-hell', 'bg-fettstift-hell'],
  ['leuchttisch', 'bg-leuchttisch'],
  ['negativ', 'bg-negativ'],
  ['negativ-muted', 'bg-negativ-muted'],
  ['gruen-hell', 'bg-gruen-hell'],
  ['gruen', 'bg-gruen'],
  ['bernstein', 'bg-bernstein'],
] as const;

function Tokens() {
  return (
    <Section id="tokens" title="Tokens">
      <div className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-3">
        {SWATCHES.map(([name, cls]) => (
          <div key={name} className="grid gap-1">
            <span className={`h-12 rounded-small ring-1 ring-line ${cls}`} />
            <span className="text-xs text-ink-muted">{name}</span>
          </div>
        ))}
      </div>
      <Both>
        {() => (
          <div className="grid gap-2">
            <p className="text-3xl font-bold">Eriks Geburtstag</p>
            <p className="text-2xl font-bold">Display 34</p>
            <p className="text-xl font-bold">Titel 27</p>
            <p className="text-lg font-semibold">Abschnitt 21</p>
            <p className="text-md">Fließtext 17: Halte die Flasche in den Umriss.</p>
            <p className="text-sm">Standard 15: Deine Fotos sehen die Gastgeber.</p>
            <p className="text-xs text-ink-muted">Klein 13: vor 3&nbsp;Min.</p>
            <p className="flex flex-wrap items-baseline gap-4 text-accent-ink">
              <span className="dots text-dots-sm">0031</span>
              <span className="dots text-dots-md">0030</span>
              <span className="text-sm text-ink-muted">von {formatCount(1_000_000)} Bieren</span>
            </p>
          </div>
        )}
      </Both>
    </Section>
  );
}

function Buttons() {
  return (
    <Section id="buttons" title="Button, IconButton">
      <Both>
        {() => (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" icon={Download}>
                Speichern
              </Button>
              <Button variant="secondary" icon={Camera}>
                Neues Foto
              </Button>
              <Button variant="quiet">Auswahl aufheben</Button>
              <Button variant="danger" icon={Trash2}>
                Endgültig löschen
              </Button>
              <Button variant="danger-outline" icon={Ban}>
                Sperren…
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" size="lg">
                Los geht’s
              </Button>
              <Button size="md">Mittel 48</Button>
              <Button size="sm">Klein 44</Button>
              <Button size="xs">Dicht 36</Button>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" isPending pendingLabel="Sendet…">
                Erneut senden
              </Button>
              <Button isDisabled>Gesperrt</Button>
              <LinkButton href="#buttons" variant="secondary">
                Zum Start
              </LinkButton>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <IconButton label="Hilfe" icon={Search} tooltip />
              <IconButton label="Abmelden" icon={LogOut} tooltip />
              <span className="flex gap-2 rounded-control bg-kamera p-2">
                <IconButton label="Kamera wechseln" icon={SwitchCamera} variant="camera" size="lg" />
                <IconButton label="Countdown" icon={Timer} variant="camera" size="lg" />
              </span>
              <span
                className="flex gap-2 bg-cover p-2"
                style={{ backgroundImage: `url(${PHOTOS[1]?.src ?? ''})` }}
              >
                <IconButton label="Ausblenden" icon={Eye} variant="overlay" />
                <IconButton label="Einblenden" icon={EyeOff} variant="overlay" />
              </span>
            </div>
            <span className="w-fit rounded-control bg-kamera p-2">
              <Button variant="camera" size="sm" icon={Timer}>
                3&nbsp;s
              </Button>
            </span>
          </>
        )}
      </Both>
    </Section>
  );
}

function Status() {
  return (
    <Section id="status" title="Badge, ConnectionIndicator, StatusPill, Spinner, Progress">
      <Both>
        {() => (
          <>
            <div className="flex flex-wrap gap-2">
              <Badge tone="mark" icon={EyeOff}>
                Ausgeblendet
              </Badge>
              <Badge tone="mark" icon={Ban}>
                Gesperrt
              </Badge>
              <Badge tone="mark">Automatisch gesperrt</Badge>
              <Badge tone="amber">Hochladen pausiert</Badge>
              <Badge tone="ok">Erledigt</Badge>
              <Badge tone="new">Neu</Badge>
              <Badge>3 Fotos</Badge>
            </div>
            <div className="flex flex-wrap gap-4">
              <ConnectionIndicator status="live" />
              <ConnectionIndicator status="reconnecting" />
              <ConnectionIndicator status="polling" />
              <ConnectionIndicator status="offline" />
            </div>
            <div className="flex flex-wrap gap-2">
              <StatusPill state="on" />
              <StatusPill state="paused-new" />
              <StatusPill state="stopped" />
            </div>
            <div className="flex items-center gap-4">
              <Spinner />
              <Progress label="Zeitraffer wird erstellt…" value={0.42} className="w-72" />
            </div>
          </>
        )}
      </Both>
    </Section>
  );
}

function Forms() {
  const [insta, setInsta] = useState('erik.n');
  const [bad, setBad] = useState('müller');
  const [ext, setExt] = useState<'all' | 'beer' | 'booth'>('all');
  const [vis, setVis] = useState<'all' | 'visible' | 'hidden'>('all');
  const [vessel, setVessel] = useState<'bottle' | 'cup'>('bottle');
  const [pause, setPause] = useState(false);
  const [stop, setStop] = useState(true);
  const [check, setCheck] = useState(true);
  return (
    <Section id="forms" title="TextField, Select, Checkbox, Switch, SegmentedControl">
      <Both>
        {(tone) => (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <TextField
                label="Instagram (freiwillig)"
                description="Dann können wir dich markieren."
                prefix="@"
                placeholder="deinname…"
                value={insta}
                onChange={setInsta}
                maxLength={31}
              />
              <TextField
                label="Instagram-Name"
                prefix="@"
                value={bad}
                onChange={setBad}
                errorMessage="Instagram-Namen haben keine Umlaute und kein ß. Schau nochmal, wie deiner genau geschrieben wird."
              />
              <TextField
                label="Suche"
                hideLabel
                icon={Search}
                size="sm"
                placeholder="Name oder Nr. suchen…"
              />
              <TextField label="Grund (optional)" placeholder="z. B. unpassende Fotos…" isDisabled />
              <Select
                label="Aktivität"
                inlineLabel
                size="sm"
                value={ext}
                onChange={setExt}
                options={[
                  { id: 'all', label: 'Alle' },
                  { id: 'beer', label: 'Beer Cam' },
                  { id: 'booth', label: 'Fotobox' },
                ]}
              />
              <Select
                label="Gast"
                value={null}
                onChange={() => undefined}
                options={GUESTS.map((g) => ({ id: g.id, label: g.name }))}
              />
            </div>
            <div className="flex flex-wrap items-center gap-x-6">
              <Checkbox isSelected={check} onChange={setCheck}>
                Gerätemerkmal auch sperren
              </Checkbox>
              <Checkbox isIndeterminate>Alle auswählen</Checkbox>
              <Checkbox isDisabled>Nicht verfügbar</Checkbox>
            </div>
            <div className="grid gap-3">
              <Switch isSelected={pause} onChange={setPause}>
                Hochladen pausieren
              </Switch>
              <Switch
                variant="emergency"
                icon={OctagonPause}
                isSelected={stop}
                onChange={setStop}
                description={stop ? 'Gestoppt seit 22:41' : 'Aus'}
              >
                Hochladen für alle stoppen
              </Switch>
              <Switch
                variant="row"
                isSelected={tone === 'light'}
                description="Wer ab jetzt beitritt, kann erst nach Freigabe hochladen."
              >
                Neue Gäste pausieren
              </Switch>
              <Switch variant="row" isPending description="Wird gespeichert…">
                Neue Gäste pausieren
              </Switch>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <SegmentedControl
                label="Sichtbarkeit"
                size="sm"
                value={vis}
                onChange={setVis}
                options={[
                  { id: 'all', label: 'Alle' },
                  { id: 'visible', label: 'Sichtbar' },
                  { id: 'hidden', label: 'Ausgeblendet' },
                ]}
              />
              <span className="rounded-control bg-kamera p-2">
                <SegmentedControl
                  label="Gefäß"
                  tone="camera"
                  iconOnly="narrow"
                  value={vessel}
                  onChange={setVessel}
                  options={[
                    { id: 'bottle', label: 'Flasche', icon: Beer },
                    { id: 'cup', label: 'Becher', icon: CupSoda },
                  ]}
                />
              </span>
            </div>
          </>
        )}
      </Both>
    </Section>
  );
}

function Navigation() {
  return (
    <Section id="nav" title="Tabs, SidebarNav, BottomBar">
      <Both>
        {() => (
          <>
            <Tabs defaultSelectedKey="fotos">
              <TabList
                label="Bereiche"
                items={[
                  { id: 'fotos', label: 'Fotos', count: 49 },
                  { id: 'gaeste', label: 'Gäste', count: 13 },
                  { id: 'instagram', label: 'Instagram', count: 8 },
                  { id: 'sperren', label: 'Sperren', count: 3 },
                  { id: 'protokoll', label: 'Protokoll' },
                  { id: 'export', label: 'Export' },
                ]}
              />
              <TabPanel id="fotos">
                <p className="text-sm text-ink-muted">Inhalt „Fotos“</p>
              </TabPanel>
              {['gaeste', 'instagram', 'sperren', 'protokoll', 'export'].map((id) => (
                <TabPanel key={id} id={id}>
                  <p className="text-sm text-ink-muted">Inhalt „{id}“</p>
                </TabPanel>
              ))}
            </Tabs>
            <div className="h-[31rem] overflow-hidden rounded-control border border-line">
              <SidebarNav
                label="Verwaltung"
                currentId="fotos"
                header={
                  <div className="grid gap-1">
                    <p className="text-md font-bold">Eriks Geburtstag</p>
                    <ConnectionIndicator status="live" />
                  </div>
                }
                items={[
                  { id: 'fotos', label: 'Fotos', icon: Images, href: '#nav', count: 49 },
                  { id: 'gaeste', label: 'Gäste', icon: Users, href: '#nav', count: 13 },
                  { id: 'instagram', label: 'Instagram', icon: AtSign, href: '#nav', count: 8 },
                  { id: 'sperren', label: 'Sperren', icon: ShieldBan, href: '#nav', count: 3 },
                  { id: 'protokoll', label: 'Protokoll', icon: ScrollText, href: '#nav' },
                  { id: 'export', label: 'Export', icon: Archive, href: '#nav' },
                ]}
                footer={
                  <>
                    <StatusPill state="on" label="Hochladen: an" className="w-full" />
                    <LinkButton href="#nav" variant="quiet" size="xs" icon={Radio} className="justify-start">
                      Live öffnen
                    </LinkButton>
                  </>
                }
              />
            </div>
            <div className="relative h-20 overflow-hidden rounded-control border border-line">
              <BottomBar
                label="Bereiche"
                currentId="live"
                className="absolute"
                items={[
                  { id: 'live', label: 'Live', icon: Images, href: '#nav' },
                  { id: 'upload', label: 'Hochladen', icon: Upload, onPress: () => undefined },
                  { id: 'manage', label: 'Verwaltung', icon: LayoutGrid, href: '#nav' },
                ]}
              />
            </div>
          </>
        )}
      </Both>
    </Section>
  );
}

const COLUMNS: ReadonlyArray<DataColumn<SampleGuest>> = [
  { id: 'nr', label: 'Nr.', align: 'end', width: 'w-16', allowsSorting: true, render: (g) => g.id },
  {
    id: 'name',
    label: 'Name',
    isRowHeader: true,
    allowsSorting: true,
    render: (g) => <span translate="no">{g.name}</span>,
  },
  { id: 'instagram', label: 'Instagram', render: (g) => (g.instagram ? `@${g.instagram}` : '–') },
  { id: 'photos', label: 'Fotos', align: 'end', allowsSorting: true, render: (g) => g.photos },
  {
    id: 'status',
    label: 'Status',
    render: (g) =>
      g.status === 'ok' ? (
        <span className="text-ink-muted">Darf hochladen</span>
      ) : g.status === 'paused' ? (
        <Badge tone="amber">Hochladen pausiert</Badge>
      ) : (
        <Badge tone="mark">{g.status === 'auto' ? 'Automatisch gesperrt' : 'Gesperrt'}</Badge>
      ),
  },
  { id: 'seen', label: 'Zuletzt', align: 'end', hideBelow: 'md', render: (g) => g.seen },
];

function Tables() {
  return (
    <Section id="table" title="DataTable">
      <Both>
        {() => (
          <>
            <DataTable
              aria-label="Gäste"
              columns={COLUMNS}
              rows={GUESTS}
              getRowId={(g) => g.id}
              sortDescriptor={{ column: 'nr', direction: 'descending' }}
              onSortChange={() => undefined}
              onRowAction={() => undefined}
              maxHeightClass="max-h-72"
            />
            <div className="grid gap-3 sm:grid-cols-2">
              <DataTable aria-label="Leer" columns={COLUMNS} rows={[]} getRowId={(g) => g.id} />
              <DataTable aria-label="Lädt" columns={COLUMNS} rows={[]} getRowId={(g) => g.id} isLoading />
            </div>
          </>
        )}
      </Both>
    </Section>
  );
}

function Tiles() {
  const [hidden, setHidden] = useState<Record<string, boolean>>({ p2: true });
  const [selected, setSelected] = useState<Record<string, boolean>>({ p3: true });
  return (
    <Section id="tiles" title="PhotoTile">
      <Both>
        {(tone) => (
          <div className="grid grid-cols-2 gap-x-3 gap-y-5 sm:grid-cols-4">
            {PHOTOS.slice(0, 8).map((p, i) => {
              const isHidden = hidden[p.id] ?? false;
              return (
                <PhotoTile
                  key={p.id}
                  src={p.src}
                  alt={`${frameLabel(p.ext, p.seq)} von ${p.guest}`}
                  label={frameLabel(p.ext, p.seq)}
                  sublabel={p.guest}
                  isHidden={isHidden}
                  isSelected={tone === 'light' && (selected[p.id] ?? false)}
                  isNew={i === 0}
                  isBusy={i === 5}
                  onOpen={() => undefined}
                  {...(tone === 'dark'
                    ? {
                        overlay: (
                          <IconButton
                            variant="overlay"
                            icon={isHidden ? EyeOff : Eye}
                            label={isHidden ? 'Einblenden' : 'Ausblenden'}
                            onPress={() => setHidden((h) => ({ ...h, [p.id]: !isHidden }))}
                          />
                        ),
                      }
                    : {
                        selection: {
                          label: `${frameLabel(p.ext, p.seq)} auswählen`,
                          isSelected: selected[p.id] ?? false,
                          onChange: (v: boolean) => setSelected((s) => ({ ...s, [p.id]: v })),
                        },
                      })}
                />
              );
            })}
          </div>
        )}
      </Both>
    </Section>
  );
}

function CameraParts() {
  return (
    <Section id="camera" title="FilmEdge, Shutter, Countdown">
      <div className="grid gap-3 bg-kamera p-4 lg:grid-cols-2">
        <FilmEdge label="Nächstes Bier" frame={31} end={<>Ziel 1&nbsp;Mio.</>} />
        <FilmEdge label="Foto" frame={19} state="uploading" progress={0.4} end="Wird hochgeladen… 40 %" />
        <FilmEdge label="Foto" frame={19} state="done" end="Hochgeladen" />
        <FilmEdge label="Foto" frame={19} state="waiting" end="Wartet aufs Hochladen" />
        <FilmEdge label="Foto" frame={19} state="error" end="Erneut senden" />
        <FilmEdge frame={30} size="lg" holes="both" label="Biere" end={<>von 1&nbsp;Mio.</>} />
      </div>
      <Stage>
        <Shutter state="ready" keyHint="Leertaste" />
        <Shutter state="not-ready" />
        <Shutter state="counting" countdownProgress={0.4} />
        <Shutter state="capturing" />
        <Shutter state="blocked" />
        <div
          className="relative ml-auto aspect-[3/4] w-72 overflow-hidden bg-cover"
          style={{ backgroundImage: `url(${PHOTOS[4]?.src ?? ''})` }}
        >
          <Countdown value={2} progress={0.55} onCancel={() => undefined} className="absolute inset-0" />
        </div>
      </Stage>
    </Section>
  );
}

function States() {
  return (
    <Section id="states" title="Notice, EmptyState, Skeleton, HelpDisclosure">
      <Both>
        {() => (
          <>
            <div className="overflow-hidden rounded-control border border-line">
              <Notice
                inline
                headingLevel={2}
                icon={WifiOff}
                title="Keine Verbindung"
                hint="Deine Fotos bleiben auf dem Handy, bis du wieder Netz hast."
                actions={
                  <Button variant="primary" size="lg" block>
                    Seite neu laden
                  </Button>
                }
              >
                Dein Handy ist gerade offline. Sobald du wieder Netz hast, lade die Seite neu.
              </Notice>
            </div>
            <EmptyState
              icon={Images}
              title="Noch keine Fotos"
              action={
                <Button size="sm" variant="secondary">
                  Live öffnen
                </Button>
              }
            >
              Sobald jemand ein Foto macht, erscheint es hier.
            </EmptyState>
            <div className="grid gap-3">
              <Skeleton shape="counter" />
              <Skeleton shape="line" />
              <SkeletonGrid count={4} className="sm:grid-cols-4" />
            </div>
            <HelpDisclosure summary="Was passiert dabei?">
              Neue Gäste können erst hochladen, wenn du sie freigibst. Beim Ausschalten entscheidest du, ob
              die bis dahin pausierten Gäste freigeschaltet werden.
            </HelpDisclosure>
            <HelpDisclosure variant="section" summary="Technische Details" defaultExpanded>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                <dt className="text-ink-muted">Gerät</dt>
                <dd>Android 14, Pixel 7, Chrome 140</dd>
                <dt className="text-ink-muted">IP-Adresse</dt>
                <dd className="tabular">192.168.1.41</dd>
              </dl>
            </HelpDisclosure>
          </>
        )}
      </Both>
    </Section>
  );
}

function Overlays() {
  const [sheet, setSheet] = useState(show === 'sheet');
  const [join, setJoin] = useState(show === 'join');
  const [confirm, setConfirm] = useState(show === 'confirm');
  const [notice, setNotice] = useState(show === 'notice');
  const [stopAll, setStopAll] = useState(true);
  useEffect(() => {
    if (show === 'toast') {
      showToast(
        { message: 'Foto 0018 ausgeblendet', action: { label: 'Rückgängig', onAction: () => undefined } },
        { timeout: 600_000 },
      );
    }
  }, []);
  return (
    <Section id="overlays" title="Sheet, ConfirmDialog, Toast, Notice">
      <div className="flex flex-wrap gap-3">
        <Button onPress={() => setSheet(true)}>Hochladen-Sheet</Button>
        <Button onPress={() => setJoin(true)}>Beitreten-Sheet</Button>
        <Button onPress={() => setConfirm(true)} variant="danger-outline">
          Löschen…
        </Button>
        <Button
          onPress={() =>
            showToast({
              message: 'Foto 0018 ausgeblendet',
              action: { label: 'Rückgängig', onAction: () => undefined },
            })
          }
        >
          Toast mit Aktion
        </Button>
        <Button onPress={() => showToast({ message: 'Keine Verbindung. Nochmal versuchen?', tone: 'error' })}>
          Fehler-Toast
        </Button>
        <Button onPress={() => showToast({ message: 'Gespeichert', tone: 'success' })}>Erfolg-Toast</Button>
        <Button onPress={() => setNotice(true)}>Vollbild</Button>
      </div>
      <Sheet isOpen={sheet} onOpenChange={setSheet} title="Hochladen" data-testid="uploads-sheet">
        <div className="grid gap-3">
          <Switch
            variant="emergency"
            icon={OctagonPause}
            isSelected={stopAll}
            onChange={setStopAll}
            description={stopAll ? 'Gestoppt seit 22:41' : 'Aus'}
          >
            Hochladen für alle stoppen
          </Switch>
          <Switch variant="row" description="Wer ab jetzt beitritt, kann erst nach Freigabe hochladen.">
            Neue Gäste pausieren
          </Switch>
          <HelpDisclosure summary="Was passiert dabei?">
            Pausierte Gäste können weiter schauen und ihren Instagram-Namen ändern, aber nichts hochladen.
          </HelpDisclosure>
          <LinkButton href="#overlays" variant="secondary" size="sm" className="justify-between">
            2 Gäste pausiert
          </LinkButton>
        </div>
      </Sheet>
      <Sheet
        isOpen={join}
        onOpenChange={setJoin}
        isDismissable={false}
        title="Willkommen bei Eriks Geburtstag"
        titleSize="xl"
        data-testid="join"
        footer={
          <div className="grid gap-2">
            <p className="text-center text-xs text-ink-muted">Gleich geht’s zur Beer Cam.</p>
            <Button variant="primary" size="lg" block onPress={() => setJoin(false)}>
              Los geht’s
            </Button>
          </div>
        }
      >
        <div className="grid gap-4">
          <p className="text-md">
            Deine Fotos sehen die Gastgeber, und sie dürfen sie auf <span translate="no">@eriks.party</span>{' '}
            posten. Wenn du das nicht willst, mach hier bitte keine Fotos.
          </p>
          <HelpDisclosure summary="Mehr dazu">
            Damit wir dich wiedererkennen, merkt sich die Seite dein Gerät. Deine Fotos bleiben auf dem
            Party-Server.
          </HelpDisclosure>
          <TextField
            label="Instagram (freiwillig)"
            description="Dann können wir dich markieren."
            prefix="@"
            placeholder="deinname…"
            maxLength={31}
          />
        </div>
      </Sheet>
      <ConfirmDialog
        isOpen={confirm}
        onOpenChange={setConfirm}
        title="3 Fotos endgültig löschen?"
        confirmLabel="Endgültig löschen"
        onConfirm={() => new Promise((resolve) => setTimeout(resolve, 600))}
      >
        <p>Das lässt sich nicht rückgängig machen. Zum Verbergen reicht „Ausblenden“.</p>
      </ConfirmDialog>
      {notice ? (
        <Notice
          icon={Camera}
          title="Kamera nicht erlaubt"
          hint="Danach die Seite neu laden."
          actions={
            <>
              <Button variant="primary" size="lg" block onPress={() => setNotice(false)}>
                Seite neu laden
              </Button>
              <LinkButton href="#overlays" variant="secondary" size="lg" block>
                Zum Start
              </LinkButton>
            </>
          }
        >
          Erlaube der Seite den Zugriff auf die Kamera: Tippe in der Adressleiste auf „aA“ und dann auf
          „Website-Einstellungen“.
        </Notice>
      ) : null}
    </Section>
  );
}

export function Gallery() {
  return (
    <>
      <a
        href="#tokens"
        className="sr-only z-(--z-toast) rounded-control bg-accent px-4 py-2 text-on-accent focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Zum Inhalt springen
      </a>
      <header className="mx-auto grid max-w-[90rem] gap-2 px-4 pt-8 pb-4 sm:px-8">
        <h1 className="text-3xl font-bold">UI-Galerie</h1>
        <p className="max-w-[60ch] text-md text-ink-muted">
          Alle Bausteine aus <code translate="no">src/ui</code> in ihren Zuständen, auf Rotlicht und
          Leuchttisch. Nur für die Entwicklung.
        </p>
      </header>
      <main className="mx-auto grid max-w-[90rem] gap-10 px-4 pb-24 sm:px-8">
        <Tokens />
        <Buttons />
        <Status />
        <Forms />
        <Navigation />
        <Tables />
        <Tiles />
        <CameraParts />
        <States />
        <Overlays />
      </main>
      <ToastSlot />
    </>
  );
}
