import { describe, expect, it } from 'vitest';
import {
  ALGORITHM_LABELS,
  ANALYSIS_STATE_LABELS,
  BOX_KIND_COLORS,
  BOX_KIND_LABELS,
  CORNER_LABELS,
  MODE_LABELS,
  PRESET_LABELS,
  SPEED_LABELS,
  TRANSITION_LABELS,
  WORKER_LABELS,
} from './labels';
import {
  ALGORITHMS,
  ANALYSIS_STATES,
  BOX_KINDS,
  CORNERS,
  MODES,
  PRESETS,
  SPEEDS,
  TRANSITIONS,
  WORKER_STATES,
} from './types';

// PLAN-WALL §5

describe('labels', () => {
  it.each([
    ['mode', MODES, MODE_LABELS],
    ['algorithm', ALGORITHMS, ALGORITHM_LABELS],
    ['transition', TRANSITIONS, TRANSITION_LABELS],
    ['speed', SPEEDS, SPEED_LABELS],
    ['preset', PRESETS, PRESET_LABELS],
    ['corner', CORNERS, CORNER_LABELS],
    ['worker', WORKER_STATES, WORKER_LABELS],
    ['analysis state', ANALYSIS_STATES, ANALYSIS_STATE_LABELS],
    ['box kind', BOX_KINDS, BOX_KIND_LABELS],
    ['box colour', BOX_KINDS, BOX_KIND_COLORS],
  ] as const)('every %s id has one', (_, ids, labels) => {
    const map: Record<string, string> = labels;
    expect(Object.keys(map).toSorted()).toEqual([...ids].toSorted());
    for (const id of ids) expect(map[id]?.trim()).toBeTruthy();
    expect(new Set(Object.values(map)).size).toBe(ids.length);
  });
});
