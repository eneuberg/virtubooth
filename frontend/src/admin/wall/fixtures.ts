/**
 * Test data for the Live Wall admin (Vitest only): the contract's defaults (§4.1).
 */
import type { AnalysisStatus, PhotoAnalysis, WallAdminOut, WallConfig } from './types';

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

export const analysisStatus: AnalysisStatus = {
  worker: { state: 'running', ml: true, message: null, last_beat_at: null },
  counts: { pending: 2, running: 1, done: 12, failed: 1, skipped: 0, total: 16 },
  analyzers: [
    {
      name: 'basic',
      title: 'Helligkeit und Farben',
      kind: 'basic',
      version: '1',
      enabled: true,
      available: true,
      reason: null,
      facts: ['brightness'],
    },
    {
      name: 'faces',
      title: 'Gesichter',
      kind: 'ml',
      version: '1',
      enabled: true,
      available: true,
      reason: null,
      facts: ['faces'],
    },
  ],
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
  };
}
