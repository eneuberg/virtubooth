/**
 * Test data for the Live Wall admin (Vitest only): the contract's defaults (§4.1) and
 * PLAN-NIGHT §4.2/§4.3 shapes (analyzers, objects, values, categories).
 */
import type {
  Aggregate,
  Analyzer,
  AnalysisStatus,
  CategoryItem,
  CategorySpec,
  CategoryWinner,
  Measure,
  MeasureObjects,
  PhotoAnalysis,
  ValuesOut,
  WallAdminOut,
  WallConfig,
} from './types';

export function defaultConfig(): WallConfig {
  return {
    rev: 0,
    updated_at: null,
    by: null,
    playlist: [
      { mode: 'spotlight', enabled: true, duration_s: 120 },
      { mode: 'gallery', enabled: true, duration_s: 45 },
      { mode: 'categories', enabled: true, duration_s: 60 },
    ],
    spotlight: { algorithm: 'fresh_first', n: 12, interval_s: 8, transition: 'random', transition_ms: 1200 },
    gallery: { speed: 'medium', rows: 3 },
    categories: { per_category_s: 10, disabled: [] },
    sources: [],
    delay_s: 20,
    show_instagram: false,
    look: {
      preset: 'blobs',
      primary: '#a855f7',
      secondary: '#ff4fa3',
      background: '#2b2b31',
      fps: 30,
      calm: false,
    },
    overlay: { event_name: true, counter: true, qr: false, qr_code_id: null, corner: 'bottom-right' },
  };
}

export function adminOut(config: WallConfig = defaultConfig()): WallAdminOut {
  return {
    config,
    defaults: defaultConfig(),
    password: { set: false, changed_at: null },
    wall_path: '/livewall',
    sources: [{ id: 'beer', title: 'Bier', emoji: '🍺' }],
    categories: [
      {
        id: 'volles_haus',
        emoji: '👥',
        title: 'Volles Haus',
        line: 'Die meisten Leute auf einem Foto',
        enabled: true,
        available: false,
        reason: 'Braucht die Gesichtserkennung.',
      },
    ],
    open_walls: 1,
    event_name: 'Party',
  };
}

const STATS = { processed: 128, errors: 2, avg_ms: 340, last_ms: 290 };

function analyzer(a: Partial<Analyzer> & Pick<Analyzer, 'name' | 'title' | 'kind'>): Analyzer {
  return {
    version: '1',
    enabled: true,
    available: true,
    reason: null,
    facts: [],
    description: '',
    size_mb: null,
    stats: STATS,
    settings: null,
    settings_schema: [],
    ...a,
  };
}

export const analysisStatus: AnalysisStatus = {
  worker: {
    state: 'running',
    ml: true,
    message: null,
    last_beat_at: null,
    processed: null,
    rss_mb: null,
    load_errors: {},
  },
  counts: { pending: 2, running: 1, done: 12, failed: 1, skipped: 0, total: 16 },
  queue: { pending: 3, running: 1, oldest_pending_s: 12 },
  analyzers: [
    analyzer({
      name: 'basic',
      title: 'Helligkeit und Farben',
      kind: 'basic',
      facts: ['brightness'],
      description: 'Misst Helligkeit, Schärfe und Farbigkeit.',
      stats: { processed: 130, errors: 0, avg_ms: 12, last_ms: 9 },
    }),
    analyzer({
      name: 'faces',
      title: 'Gesichter',
      kind: 'ml',
      facts: ['faces'],
      description: 'Findet Gesichter und Lächeln.',
      size_mb: 3.4,
    }),
    analyzer({
      name: 'objects',
      title: 'Objekte',
      kind: 'ml',
      facts: ['people', 'drinks'],
      description: 'Erkennt Dinge auf dem Foto: Gläser, Hüte, Personen …',
      size_mb: 12,
      settings: { score_min: 0.35, max_objects: 50 },
      settings_schema: [
        { key: 'score_min', title: 'Mindest-Sicherheit', min: 0.05, max: 0.95, step: 0.05 },
        { key: 'max_objects', title: 'Höchstens Objekte', min: 1, max: 100, step: 1 },
      ],
    }),
  ],
  models: {
    ml: true,
    missing: [],
    missing_mb: 0,
    dest: '/data/wall/models',
    can_download: false,
    download: {
      state: 'idle',
      current: null,
      models: [],
      done_bytes: 0,
      total_bytes: 0,
      error: null,
      finished_at: null,
    },
  },
  image: 'original',
};

export function photoAnalysis(state: PhotoAnalysis['state'] = 'done'): PhotoAnalysis {
  return {
    photo_id: 'p1',
    state,
    attempts: 1,
    error: null,
    finished_at: '2026-10-13T20:41:00Z',
    versions: { basic: '1' },
    facts: { faces: 2, brightness: 0.4123 },
    boxes: [
      { kind: 'face', x: 0.1, y: 0.2, w: 0.25, h: 0.3, label: 'Gesicht 1', score: 0.9 },
      { kind: 'hand', x: 0.6, y: 0.5, w: 0.2, h: 0.2, label: 'Hand', score: 0.7 },
    ],
    details: [{ label: 'Gesichter', value: '2' }],
    objects: [
      {
        idx: 0,
        label: 'wine glass',
        label_de: 'Weinglas',
        score: 0.91,
        box: { x: 0.3, y: 0.5, w: 0.1, h: 0.2 },
        source: 'local',
        model: 'objects@1',
        sources: ['local', 'claude'],
      },
      {
        idx: 1,
        label: 'hat',
        label_de: 'Hut',
        score: 0.8,
        box: null,
        source: 'claude',
        model: 'claude-haiku-5-5',
        sources: ['claude'],
      },
    ],
    objects_local: [
      {
        pos: 0,
        label: 'wine glass',
        label_de: 'Weinglas',
        score: 0.91,
        box: { x: 0.3, y: 0.5, w: 0.1, h: 0.2 },
        source: 'local',
        model: 'objects@1',
        merged_idx: 0,
      },
    ],
    objects_ai: [
      {
        pos: 0,
        label: 'glass of wine',
        label_de: 'Sektglas',
        score: 0.75,
        box: { x: 0.31, y: 0.5, w: 0.1, h: 0.21 },
        source: 'claude',
        model: 'claude-haiku-5-5',
        merged_idx: 0,
      },
      {
        pos: 1,
        label: 'hat',
        label_de: 'Hut',
        score: 0.8,
        box: null,
        source: 'claude',
        model: 'claude-haiku-5-5',
        merged_idx: 1,
      },
    ],
    runs: [
      { source: 'local', state: 'done', model: 'objects@1', error: null },
      { source: 'claude', state: 'done', model: 'claude-haiku-5-5', error: null },
    ],
    objects_fallback: null,
    opt_out: { analysis: false, external_ai: false },
    properties: [{ name: 'coolness', inactive: false, scores: [0.2, 0.9] }],
    durations_ms: { basic: 12, faces: 140 },
  };
}

// ---------------------------------------------------------------- categories

const pv = (
  key: string,
  title: string,
  group: string,
  kind: 'number' | 'count' | 'time',
  unit = '',
): ValuesOut['photo_values'][number] => ({ key, title, group, kind, unit, needs: [], available: true, reason: null });

export const valuesOut: ValuesOut = {
  photo_values: [
    pv('people', 'Personen', 'Gesichter und Personen', 'count'),
    pv('smiles', 'Lächeln', 'Gesichter und Personen', 'count'),
    pv('happy_max', 'Fröhlichkeit (höchste)', 'Gesichter und Personen', 'number', '0–1'),
    pv('colorfulness', 'Farbigkeit', 'Bild', 'number'),
    pv('sharpness', 'Schärfe', 'Bild', 'number'),
    pv('photo.created_at', 'Aufnahmezeit', 'Foto', 'time'),
    pv('photo.guest_photos', 'Fotos dieses Gasts', 'Foto', 'count'),
  ],
  object_fields: [
    { field: 'confidence', title: 'Erkennungssicherheit', property: null, unit: '0–1' },
    { field: 'prop:coolness', title: 'coolness', property: 'coolness', unit: '0–1' },
  ],
  aggregates: [],
  objects_available: true,
  objects_reason: null,
  labels: [
    { label: 'wine glass', label_de: 'Weinglas', count: 14 },
    { label: 'hat', label_de: 'Hut', count: 3 },
    { label: 'person', label_de: 'Person', count: 40 },
  ],
};

const NO_FILTER = { labels: [], exclude: [], min_confidence: null };

/** v2 measures for the fixtures */
export const measure = {
  value: (key: string): Measure => ({ kind: 'value', key }),
  objects: (agg: Aggregate, field: string | null = null, labels: string[] = []): MeasureObjects => ({
    kind: 'objects',
    where: { ...NO_FILTER, labels },
    field,
    agg,
    k: null,
    t: null,
  }),
};

export function spec(over: Partial<CategorySpec> = {}): CategorySpec {
  return {
    version: 2,
    emoji: '👥',
    title: 'Volles Haus',
    line: 'Die meisten Leute auf einem Foto',
    pool: [],
    rank: { by: measure.value('people'), order: 'desc', threshold: 3, then_by: [] },
    select: { count: 3, one_per_guest: true },
    caption: { value: null, format: 'count', one: 'Person', many: 'Personen', show_object: false },
    verdict: null,
    ...over,
  };
}

const ITEM = {
  explanation: 'Höchster Wert bei „Personen“, mindestens 3',
  needs_ai: false,
  properties: [],
  locked: null,
  off_reason: null,
  off_detail: null,
  off_at: null,
  verdict_paused: false,
} satisfies Partial<CategoryItem>;

export function winner(photo: string, value: number, label: string): CategoryWinner {
  return {
    photo_id: photo,
    thumb_url: `/media/${photo}?thumb=1`,
    value,
    label,
    headline: label,
    detail: null,
    object_idx: null,
    object: null,
    comment: null,
  };
}

export function categoryItems(): CategoryItem[] {
  return [
    {
      ...ITEM,
      id: 'volles_haus',
      enabled: true,
      preset: 'volles_haus',
      position: 0,
      spec: spec(),
      available: true,
      reason: null,
      verdict: null,
      winners: [winner('p1', 7, '7 Personen')],
    },
    {
      ...ITEM,
      id: 'coolstes_objekt',
      enabled: false,
      preset: 'coolstes_objekt',
      position: 1,
      spec: spec({
        emoji: '🏆',
        title: 'Das coolste Objekt',
        line: 'Was die KI am coolsten findet',
        rank: { by: measure.objects('max', 'prop:coolness'), order: 'desc', threshold: null, then_by: [] },
        select: { count: 1, one_per_guest: false },
        caption: { value: null, format: 'none', one: '', many: '', show_object: true },
        verdict: {
          prompt: 'Werte das coolste Objekt aus den Ergebnissen raus und sag mir, von wem und was.',
          count: 1,
          model: null,
          effort: 'low',
        },
      }),
      explanation: 'Höchster coolness-Wert unter allen Objekten',
      needs_ai: true,
      properties: ['coolness'],
      available: false,
      reason: 'Braucht die Eigenschaft „coolness“.',
      verdict: { text: 'Der Hut von Gast 3 ist unschlagbar.', emoji: '🎩', photo_id: 'p2' },
      winners: [],
    },
    {
      ...ITEM,
      id: 'mein_prost',
      enabled: true,
      preset: null,
      position: 2,
      spec: spec({
        emoji: '🥂',
        title: 'Prost!',
        line: 'Die meisten Gläser',
        pool: [{ measure: measure.objects('count', null, ['wine glass']), op: 'gte', operand: 1 }],
        rank: {
          by: measure.objects('count', null, ['wine glass']),
          order: 'desc',
          threshold: null,
          then_by: [],
        },
        select: { count: 3, one_per_guest: false },
        caption: { value: null, format: 'count', one: 'Glas', many: 'Gläser', show_object: false },
      }),
      explanation: 'Die meisten Objekte (nur wine glass)',
      available: true,
      reason: null,
      verdict: null,
      winners: [],
    },
  ];
}
