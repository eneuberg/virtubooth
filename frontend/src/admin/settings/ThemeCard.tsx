/**
 * „Erscheinungsbild“ (its own section, LookSection.tsx): the colours of the guest pages and the Live Wall (the admin keeps
 * its look). A preset („Neon Nacht“, „Klassisch“, „Rummel“) or own colours and a style
 * (Ruhig, Party, Verspielt; the default is Neon Nacht, Verspielt), with a live preview
 * of a guest card and a wall tile. The server checks that text stays readable (4.5:1);
 * the card shows the same check before saving. Guests get a new theme when their page
 * comes back to the foreground, open walls at once.
 */
import { useQueryClient } from '@tanstack/react-query';
import { Palette, RotateCcw } from 'lucide-react';
import { useState, type CSSProperties } from 'react';
import {
  contrastProblems,
  DEFAULT_STYLE,
  HEX_RE,
  themeVariables,
  THEME_COLOR_KEYS,
  type ThemeColorKey,
  type ThemeColors,
  type ThemeStyle,
} from '@/styles/theme';
import { Button } from '@/ui/Button';
import { SegmentedControl } from '@/ui/SegmentedControl';
import { showToast } from '@/ui/Toast';
import { errorText } from '../common/usePhotoActions';
import { ColorField } from '../wall/fields';
import { SettingsCard } from './SettingsCard';
import { resetTheme, saveTheme, type AdminThemeOut, type ThemeChoice } from './themeApi';

const COLOR_LABELS: Record<ThemeColorKey, { label: string; hint: string }> = {
  background: { label: 'Hintergrund', hint: 'Grundfläche aller Gästeseiten' },
  surface: { label: 'Fläche', hint: 'Karten, Fenster, Gästepass' },
  depth: { label: 'Tiefe', hint: 'Schatten, Felder, Abdunkeln' },
  primary: { label: 'Hauptfarbe', hint: 'Knöpfe, Auslöser, Leuchten' },
  secondary: { label: 'Schriftzug', hint: 'Der Partyname' },
  tertiary: { label: 'Kühles Detail', hint: 'Ruhige Akzente' },
  accent: { label: 'Akzent', hint: 'Abzeichen, Übergänge auf der Wall' },
  highlight: { label: 'Glanzlicht', hint: 'Kleine Lichtkanten' },
  hit: { label: 'Blitz', hint: 'Nur kurz: ein Foto ist gemacht' },
  text: { label: 'Text', hint: 'Gut lesbar auf Hintergrund und Fläche' },
  text_muted: { label: 'Nebentext', hint: 'Hinweise, Zeiten' },
};

const CHOICES: { id: ThemeChoice; label: string }[] = [
  { id: 'neon_nacht', label: 'Neon Nacht' },
  { id: 'klassisch', label: 'Klassisch' },
  { id: 'rummel', label: 'Rummel' },
  { id: 'custom', label: 'Eigene' },
];

// goofy (Verspielt) is the default, with Neon Nacht: the fairground look
const STYLES: { id: ThemeStyle; label: string }[] = [
  { id: 'elegant', label: 'Ruhig' },
  { id: 'party', label: 'Party' },
  { id: 'goofy', label: 'Verspielt' },
];

function sameColors(a: ThemeColors, b: ThemeColors): boolean {
  return THEME_COLOR_KEYS.every((k) => a[k] === b[k]);
}

type Busy = 'save' | 'reset' | null;

export function ThemeCard({ data }: { data: AdminThemeOut }) {
  const qc = useQueryClient();
  const saved = data.theme.colors;
  // null: not edited, the card shows the saved theme (also when another admin changes it)
  const [draft, setDraft] = useState<{ choice: ThemeChoice; colors: ThemeColors; style: ThemeStyle } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const choice: ThemeChoice = draft?.choice ?? data.theme.preset;
  const colors = draft?.colors ?? saved;
  const savedStyle: ThemeStyle = data.theme.style ?? DEFAULT_STYLE;
  const style = draft?.style ?? savedStyle;
  const presetOf = (id: ThemeChoice) => data.presets.find((p) => p.id === id);

  const badHex = THEME_COLOR_KEYS.filter((k) => !HEX_RE.test(colors[k]));
  const problems = badHex.length ? [] : contrastProblems(colors);
  const dirty =
    draft !== null &&
    (draft.choice !== data.theme.preset || !sameColors(draft.colors, saved) || draft.style !== savedStyle);

  const pick = (id: ThemeChoice) => {
    setError(null);
    const preset = presetOf(id);
    // a preset brings its style (Rummel: the fairground layer); own colours keep it
    setDraft({ choice: id, colors: preset ? preset.colors : colors, style: preset ? preset.style : style });
  };
  const setColor = (key: ThemeColorKey, value: string) => {
    setError(null);
    const next = { ...colors, [key]: value };
    const preset = presetOf(choice);
    const stillPreset = preset && sameColors(preset.colors, next);
    setDraft({ choice: stillPreset ? choice : 'custom', colors: next, style });
  };

  const run = async (which: Exclude<Busy, null>, action: () => Promise<unknown>, done: string) => {
    if (busy) return;
    setBusy(which);
    setError(null);
    try {
      await action();
      setDraft(null);
      showToast({ message: done, tone: 'success' });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(null);
    }
  };

  const save = () => {
    const preset = presetOf(choice);
    const asPreset = choice !== 'custom' && preset && sameColors(preset.colors, colors);
    void run(
      'save',
      () => saveTheme(qc, asPreset ? choice : 'custom', asPreset ? null : colors, style),
      'Erscheinungsbild gespeichert.',
    );
  };

  return (
    <div className="md:col-span-2 xl:col-span-3">
      <SettingsCard title="Farben und Stil" icon={Palette} testid="settings-theme">
        <p className="max-w-prose text-sm text-ink-muted">
          Farben der Gästeseiten und der Live-Wall. Die Verwaltung behält ihr Aussehen. Gäste sehen neue
          Farben, sobald sie die Seite wieder öffnen; die Live-Wall sofort.
        </p>
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <div className="grid min-w-0 gap-4">
            <SegmentedControl
              label="Vorlage"
              size="sm"
              options={CHOICES}
              value={choice}
              onChange={pick}
              className="flex-wrap justify-self-start"
              data-testid="theme-preset"
            />
            <SegmentedControl
              label="Stil"
              size="sm"
              options={STYLES}
              value={style}
              onChange={(next) => {
                setError(null);
                setDraft({ choice, colors, style: next });
              }}
              className="justify-self-start"
              data-testid="theme-style"
            />
            <p className="-mt-2 text-xs text-ink-muted" data-testid="theme-default">
              Standard: „Neon Nacht“ im Stil „Verspielt“.
            </p>
            <div className="grid gap-3 sm:grid-cols-[repeat(auto-fill,minmax(11rem,1fr))]">
              {THEME_COLOR_KEYS.map((key) => (
                <div key={key} className="grid min-w-0 gap-1">
                  <ColorField
                    label={COLOR_LABELS[key].label}
                    value={colors[key]}
                    onChange={(value) => setColor(key, value)}
                    error={badHex.includes(key) ? 'Bitte eine Farbe wie #c026ff.' : undefined}
                    testid={`theme-color-${key}`}
                  />
                  <span className="text-xs text-ink-muted">{COLOR_LABELS[key].hint}</span>
                </div>
              ))}
            </div>
            {problems.length ? (
              <ul className="grid gap-1 text-sm text-danger" data-testid="theme-contrast" aria-live="polite">
                {problems.map(([fg, bg, ratio]) => (
                  <li key={`${fg}-${bg}`}>
                    {COLOR_LABELS[fg].label} auf {COLOR_LABELS[bg].label} ist schlecht lesbar (
                    {ratio.toFixed(1).replace('.', ',')}:1, nötig 4,5:1).
                  </li>
                ))}
              </ul>
            ) : null}
            {error ? (
              <p role="alert" className="text-sm text-danger" data-testid="theme-error">
                {error}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                variant="primary"
                size="sm"
                isDisabled={!dirty || badHex.length > 0 || problems.length > 0}
                isPending={busy === 'save'}
                pendingLabel="Speichert…"
                onPress={save}
                data-testid="theme-save"
              >
                Speichern
              </Button>
              {dirty ? (
                <Button variant="quiet" size="sm" onPress={() => setDraft(null)} data-testid="theme-discard">
                  Verwerfen
                </Button>
              ) : null}
              {data.theme.custom ? (
                <Button
                  variant="secondary"
                  size="sm"
                  icon={RotateCcw}
                  isPending={busy === 'reset'}
                  pendingLabel="Setzt zurück…"
                  onPress={() => void run('reset', () => resetTheme(qc), 'Erscheinungsbild zurückgesetzt.')}
                  data-testid="theme-reset"
                >
                  Zurücksetzen
                </Button>
              ) : null}
            </div>
          </div>
          <ThemePreview colors={colors} />
        </div>
      </SettingsCard>
    </div>
  );
}

const v = (name: string) => `var(--t-${name})`;

/** A guest card and a wall tile in the given colours (CSSOM custom properties). */
export function ThemePreview({ colors }: { colors: ThemeColors }) {
  const vars = themeVariables(colors) as CSSProperties;
  return (
    <div className="grid gap-3" style={vars} data-testid="theme-preview" aria-hidden="true">
      <div
        className="grid gap-3 overflow-hidden rounded-[18px] p-4"
        style={{
          background: `radial-gradient(22rem 10rem at 50% -3rem, color-mix(in oklab, ${v('depth')} 90%, transparent), transparent), ${v('background')}`,
          color: v('text'),
        }}
      >
        <span className="text-2xl font-semibold" style={{ color: v('secondary'), letterSpacing: '-0.03em' }}>
          Sommerfest
        </span>
        <div className="grid gap-1 rounded-[18px] p-4" style={{ background: v('surface') }}>
          <span className="flex items-center justify-between gap-2">
            <span className="text-lg font-semibold" style={{ letterSpacing: '-0.015em' }}>
              Fotobox
            </span>
            <span
              className="rounded-full px-2 py-0.5 text-xs font-semibold"
              style={{ background: v('accent'), color: v('on-accent') }}
            >
              Neu
            </span>
          </span>
          <span className="text-sm" style={{ color: v('text-muted') }}>
            Selfie mit Filter und Countdown.
          </span>
          <span className="pt-1 text-sm font-semibold" style={{ color: v('primary-ink') }}>
            128 Fotos
          </span>
        </div>
        <span
          className="flex h-11 items-center justify-center rounded-full text-sm font-semibold"
          style={{
            background: v('primary'),
            color: v('on-primary'),
            boxShadow: `0 10px 28px -12px color-mix(in oklab, ${v('primary')} 75%, transparent), inset 0 1px 0 color-mix(in oklab, ${v('highlight')} 30%, transparent)`,
          }}
        >
          Foto machen
        </span>
      </div>
      <div
        className="relative grid aspect-video place-items-center overflow-hidden rounded-[12px]"
        style={{
          background: `radial-gradient(60% 80% at 20% 30%, color-mix(in oklab, ${v('primary')} 45%, transparent), transparent), radial-gradient(50% 70% at 85% 80%, color-mix(in oklab, ${v('accent')} 35%, transparent), transparent), ${v('background')}`,
          color: v('text'),
        }}
      >
        <div className="relative h-[70%] w-[34%]">
          <div
            className="absolute inset-0 rounded-[8px]"
            style={{
              background: `linear-gradient(160deg, ${v('tertiary')}, ${v('depth')})`,
              boxShadow: `0 0 0 2px color-mix(in oklab, ${v('primary')} 80%, ${v('highlight')}), 0 12px 24px -10px rgb(0 0 0 / 0.6)`,
            }}
          />
          <span
            className="absolute -bottom-3 left-[-12%] rounded-[6px] px-2 py-1 text-[11px] font-semibold whitespace-nowrap"
            style={{ background: `color-mix(in oklab, ${v('depth')} 85%, transparent)`, color: v('text') }}
          >
            von Anna <span style={{ color: v('text-muted') }}>vor 2 Min.</span>
          </span>
        </div>
        <span
          className="absolute top-2 right-2 rounded-full px-2 py-0.5 text-[11px] font-semibold"
          style={{ background: v('accent'), color: v('on-accent') }}
        >
          7 Personen
        </span>
        <span
          className="absolute bottom-2 left-2 size-2 rounded-full"
          style={{ background: v('hit'), boxShadow: `0 0 8px ${v('hit')}` }}
        />
      </div>
    </div>
  );
}
