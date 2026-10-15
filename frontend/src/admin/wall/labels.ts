/**
 * German labels of the Live Wall admin (every enum id has one: labels.test.ts).
 */
import type {
  AnalysisState,
  AnalyzerKind,
  BoxKind,
  GallerySpeed,
  LookPreset,
  OverlayCorner,
  SpotlightAlgorithm,
  WallMode,
  WallTransition,
  WorkerState,
} from './types';

export const MODE_LABELS: Record<WallMode, string> = {
  spotlight: 'Einzelbild',
  gallery: 'Galerie',
  categories: 'Kategorien',
};

export const ALGORITHM_LABELS: Record<SpotlightAlgorithm, string> = {
  newest: 'Die neuesten N im Kreis',
  random: 'Zufällig',
  shuffle: 'Gemischt, ohne Wiederholung',
  fair: 'Fair: jeder Gast reihum',
  least_shown: 'Selten gezeigte zuerst',
  fresh_first: 'Neue Fotos sofort, sonst gemischt',
  highlights: 'Kategorie-Highlights',
};

export const TRANSITION_LABELS: Record<WallTransition, string> = {
  crossfade: 'Überblenden',
  kenburns: 'Langsamer Zoom',
  spring: 'Federnd',
  dither: 'Pixelrauschen',
  pixelate: 'Verpixeln',
  glitch: 'Glitch',
  polaroid: 'Polaroid-Fall',
  slot: 'Spielautomat',
  jelly: 'Wackelpudding',
  stamp: 'Stempel',
  confetti: 'Konfetti',
  random: 'Zufall (alle gemischt)',
};

export const SPEED_LABELS: Record<GallerySpeed, string> = {
  slow: 'Langsam',
  medium: 'Mittel',
  fast: 'Schnell',
};

export const PRESET_LABELS: Record<LookPreset, string> = {
  blobs: 'Farbblasen',
  aurora: 'Polarlicht',
  disco: 'Disco-Gitter',
  confetti: 'Konfetti-Regen',
  plain: 'Ruhig (ohne Animation)',
};

export const CORNER_LABELS: Record<OverlayCorner, string> = {
  'bottom-right': 'Unten rechts',
  'bottom-left': 'Unten links',
  'top-right': 'Oben rechts',
  'top-left': 'Oben links',
};

export const WORKER_LABELS: Record<WorkerState, string> = {
  running: 'läuft',
  starting: 'startet',
  off: 'aus',
  stopped: 'gestoppt',
  crashed: 'abgestürzt',
};

export const ANALYSIS_STATE_LABELS: Record<AnalysisState, string> = {
  pending: 'wartet',
  running: 'läuft',
  done: 'fertig',
  failed: 'fehlgeschlagen',
  skipped: 'übersprungen',
};

export const ANALYZER_KIND_LABELS: Record<AnalyzerKind, string> = {
  basic: 'Basis',
  ml: 'KI',
};

export const BOX_KIND_LABELS: Record<BoxKind, string> = {
  face: 'Gesicht',
  hand: 'Hand',
  person: 'Person',
  object: 'Gegenstand',
};

/** Box outline colours per kind (CSSOM, so the CSP allows them). */
export const BOX_KIND_COLORS: Record<BoxKind, string> = {
  face: '#ffa630',
  hand: '#22c55e',
  person: '#38bdf8',
  object: '#ff4fa3',
};

/** Select/SegmentedControl options: the ids in their order, with their labels. */
export function optionsOf<K extends string>(
  ids: ReadonlyArray<K>,
  labels: Record<K, string>,
): Array<{ id: K; label: string }> {
  return ids.map((id) => ({ id, label: labels[id] }));
}
