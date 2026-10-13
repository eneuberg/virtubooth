/**
 * The Live-Wall cards that edit the draft: Ablauf, Einzelbild, Galerie, Fotos, Aussehen,
 * Einblendungen. Nothing is sent until "Änderungen speichern".
 */
import {
  ArrowDown,
  ArrowUp,
  Images,
  LayoutGrid,
  ListOrdered,
  Palette,
  PanelTop,
  Presentation,
} from 'lucide-react';
import { Button } from '@/ui/Button';
import { Checkbox } from '@/ui/Checkbox';
import { IconButton } from '@/ui/IconButton';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { Select } from '@/ui/Select';
import { Switch } from '@/ui/Switch';
import { moveMode, setModeDuration, setModeEnabled, toggleIn, type ValidationErrors } from './draft';
import { Card, ColorField, NumberField } from './fields';
import {
  ALGORITHM_LABELS,
  CORNER_LABELS,
  MODE_LABELS,
  optionsOf,
  PRESET_LABELS,
  SPEED_LABELS,
  TRANSITION_LABELS,
} from './labels';
import {
  ALGORITHMS,
  CORNERS,
  PRESETS,
  SPEEDS,
  TRANSITIONS,
  type WallAdminOut,
  type WallConfig,
} from './types';
import { WallPreview } from './WallPreview';

export interface DraftProps {
  draft: WallConfig;
  update: (change: (config: WallConfig) => WallConfig) => void;
  errors: ValidationErrors;
}

function GroupLabel({ children }: { children: string }) {
  return (
    <span aria-hidden="true" className="text-sm font-semibold">
      {children}
    </span>
  );
}

// ------------------------------------------------------------------ Ablauf

export function PlaylistCard({ draft, update, errors }: DraftProps) {
  const on = draft.playlist.filter((e) => e.enabled).length;
  const last = draft.playlist.length - 1;
  return (
    <Card
      id="ablauf"
      title="Ablauf"
      icon={ListOrdered}
      intro="Die Wand spielt die Modi nacheinander, von oben nach unten, und fängt dann von vorn an."
    >
      <ol className="grid gap-3" data-testid="wall-playlist">
        {draft.playlist.map((entry, i) => (
          <li
            key={entry.mode}
            data-mode={entry.mode}
            className="grid grid-cols-[minmax(0,1fr)_auto] items-end gap-x-3 gap-y-2 rounded-control bg-surface-sunk px-3 py-2 sm:grid-cols-[minmax(0,1fr)_10rem_auto]"
          >
            <Switch
              isSelected={entry.enabled}
              isDisabled={entry.enabled && on <= 1}
              onChange={(enabled) =>
                update((c) => ({ ...c, playlist: setModeEnabled(c.playlist, entry.mode, enabled) }))
              }
            >
              {MODE_LABELS[entry.mode]}
            </Switch>
            <div className="flex gap-1 self-center sm:order-last">
              <IconButton
                label="Nach oben"
                icon={ArrowUp}
                tooltip
                isDisabled={i === 0}
                onPress={() => update((c) => ({ ...c, playlist: moveMode(c.playlist, entry.mode, -1) }))}
              />
              <IconButton
                label="Nach unten"
                icon={ArrowDown}
                tooltip
                isDisabled={i === last}
                onPress={() => update((c) => ({ ...c, playlist: moveMode(c.playlist, entry.mode, 1) }))}
              />
            </div>
            <NumberField
              label="Dauer (Sekunden)"
              value={entry.duration_s}
              error={errors[`playlist.${entry.mode}`]}
              onChange={(v) =>
                update((c) => ({ ...c, playlist: setModeDuration(c.playlist, entry.mode, v) }))
              }
              className="col-span-2 min-w-0 sm:col-span-1"
            />
          </li>
        ))}
      </ol>
      {on <= 1 ? <p className="text-sm text-ink-muted">Mindestens ein Modus bleibt an.</p> : null}
    </Card>
  );
}

// -------------------------------------------------------------- Einzelbild

export function SpotlightCard({ draft, update, errors }: DraftProps) {
  const s = draft.spotlight;
  const set = (patch: Partial<WallConfig['spotlight']>) =>
    update((c) => ({ ...c, spotlight: { ...c.spotlight, ...patch } }));
  return (
    <Card id="einzelbild" title="Einzelbild" icon={Presentation} intro="Ein Foto groß, dann das nächste.">
      <Select
        label="Auswahl"
        options={optionsOf(ALGORITHMS, ALGORITHM_LABELS)}
        value={s.algorithm}
        onChange={(algorithm) => set({ algorithm })}
        data-testid="wall-algorithm"
      />
      {s.algorithm === 'newest' ? (
        <NumberField
          label="Anzahl N"
          value={s.n}
          error={errors['spotlight.n']}
          onChange={(n) => set({ n })}
        />
      ) : null}
      <NumberField
        label="Wechsel alle (Sekunden)"
        value={s.interval_s}
        error={errors['spotlight.interval_s']}
        onChange={(interval_s) => set({ interval_s })}
      />
      <Select
        label="Übergang"
        options={optionsOf(TRANSITIONS, TRANSITION_LABELS)}
        value={s.transition}
        onChange={(transition) => set({ transition })}
        data-testid="wall-transition"
      />
      <NumberField
        label="Übergangsdauer (ms)"
        value={s.transition_ms}
        error={errors['spotlight.transition_ms']}
        onChange={(transition_ms) => set({ transition_ms })}
      />
    </Card>
  );
}

// ----------------------------------------------------------------- Galerie

export function GalleryCard({ draft, update, errors }: DraftProps) {
  return (
    <Card
      id="galerie"
      title="Galerie"
      icon={LayoutGrid}
      intro="Viele Fotos auf einmal, in langsam laufenden Reihen."
    >
      <div className="grid gap-1.5">
        <GroupLabel>Tempo</GroupLabel>
        <SegmentedControl
          label="Tempo"
          size="sm"
          options={optionsOf(SPEEDS, SPEED_LABELS)}
          value={draft.gallery.speed}
          onChange={(speed) => update((c) => ({ ...c, gallery: { ...c.gallery, speed } }))}
          className="justify-self-start"
          data-testid="wall-speed"
        />
      </div>
      <NumberField
        label="Reihen"
        value={draft.gallery.rows}
        error={errors['gallery.rows']}
        onChange={(rows) => update((c) => ({ ...c, gallery: { ...c.gallery, rows } }))}
      />
      <h3 className="text-md font-bold">Kategorien</h3>
      <NumberField
        label="Sekunden pro Kategorie"
        value={draft.categories.per_category_s}
        error={errors['categories.per_category_s']}
        onChange={(per_category_s) =>
          update((c) => ({ ...c, categories: { ...c.categories, per_category_s } }))
        }
      />
    </Card>
  );
}

// ------------------------------------------------------------------- Fotos

export function PhotosCard({
  draft,
  update,
  errors,
  sources,
}: DraftProps & { sources: WallAdminOut['sources'] }) {
  return (
    <Card id="fotos" title="Fotos" icon={Images}>
      <fieldset className="grid gap-1">
        <legend className="mb-1 text-sm font-semibold">Quellen</legend>
        {sources.map((src) => (
          <Checkbox
            key={src.id}
            isSelected={draft.sources.includes(src.id)}
            onChange={(on) => update((c) => ({ ...c, sources: toggleIn(c.sources, src.id, on) }))}
            data-testid={`wall-source-${src.id}`}
          >
            <span aria-hidden="true">{src.emoji}</span> {src.title}
          </Checkbox>
        ))}
        <p className="text-xs text-ink-muted">
          {draft.sources.length === 0
            ? 'Keine ausgewählt: alle Aktivitäten.'
            : 'Nur Fotos aus den ausgewählten Aktivitäten.'}
        </p>
      </fieldset>
      <NumberField
        label="Verzögerung (Sekunden)"
        value={draft.delay_s}
        error={errors.delay_s}
        onChange={(delay_s) => update((c) => ({ ...c, delay_s }))}
        description="Neue Fotos erscheinen erst nach dieser Zeit, damit du vorher noch etwas ausblenden kannst. Ausgeblendete und gelöschte Fotos verschwinden sofort."
      />
      <Switch
        isSelected={draft.show_instagram}
        onChange={(show_instagram) => update((c) => ({ ...c, show_instagram }))}
      >
        Instagram-Namen zeigen
      </Switch>
    </Card>
  );
}

// ----------------------------------------------------------------- Aussehen

const FPS_OPTIONS = [
  { id: '30', label: '30 fps' },
  { id: '60', label: '60 fps' },
] as const;

export function LookCard({ draft, update, errors, defaults }: DraftProps & { defaults: WallConfig }) {
  const look = draft.look;
  const set = (patch: Partial<WallConfig['look']>) =>
    update((c) => ({ ...c, look: { ...c.look, ...patch } }));
  return (
    <Card id="aussehen" title="Aussehen" icon={Palette}>
      <WallPreview look={look} overlay={draft.overlay} />
      <Select
        label="Hintergrund"
        options={optionsOf(PRESETS, PRESET_LABELS)}
        value={look.preset}
        onChange={(preset) => set({ preset })}
        data-testid="wall-preset"
      />
      <div className="grid gap-3 sm:grid-cols-[repeat(auto-fit,minmax(11rem,1fr))]">
        <ColorField
          label="Hauptfarbe"
          value={look.primary}
          error={errors['look.primary']}
          onChange={(primary) => set({ primary })}
          testid="wall-color-primary"
        />
        <ColorField
          label="Zweitfarbe"
          value={look.secondary}
          error={errors['look.secondary']}
          onChange={(secondary) => set({ secondary })}
          testid="wall-color-secondary"
        />
        <ColorField
          label="Hintergrundfarbe"
          value={look.background}
          error={errors['look.background']}
          onChange={(background) => set({ background })}
          testid="wall-color-background"
        />
      </div>
      <Button
        size="xs"
        variant="secondary"
        className="justify-self-start"
        onPress={() =>
          set({
            primary: defaults.look.primary,
            secondary: defaults.look.secondary,
            background: defaults.look.background,
          })
        }
      >
        Standardfarben
      </Button>
      <div className="grid gap-1.5">
        <GroupLabel>Bildrate</GroupLabel>
        <SegmentedControl
          label="Bildrate"
          size="sm"
          options={FPS_OPTIONS}
          value={look.fps === 60 ? '60' : '30'}
          onChange={(fps) => set({ fps: fps === '60' ? 60 : 30 })}
          className="justify-self-start"
        />
      </div>
      <Switch
        isSelected={look.calm}
        onChange={(calm) => set({ calm })}
        description="Ruhigere Übergänge und ein stiller Hintergrund."
      >
        Weniger Bewegung
      </Switch>
    </Card>
  );
}

// ------------------------------------------------------------- Einblendungen

export function OverlayCard({ draft, update }: DraftProps) {
  const set = (patch: Partial<WallConfig['overlay']>) =>
    update((c) => ({ ...c, overlay: { ...c.overlay, ...patch } }));
  const o = draft.overlay;
  return (
    <Card id="einblendungen" title="Einblendungen" icon={PanelTop}>
      <Switch isSelected={o.event_name} onChange={(event_name) => set({ event_name })}>
        Eventname
      </Switch>
      <Switch isSelected={o.counter} onChange={(counter) => set({ counter })}>
        Fotozähler
      </Switch>
      <Switch isSelected={o.qr} isDisabled description="Kommt mit den QR-Codes.">
        QR-Code
      </Switch>
      <Select
        label="Ecke"
        options={optionsOf(CORNERS, CORNER_LABELS)}
        value={o.corner}
        onChange={(corner) => set({ corner })}
        data-testid="wall-corner"
      />
    </Card>
  );
}
