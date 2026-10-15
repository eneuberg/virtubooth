import { describe, expect, it } from 'vitest';
import { testResult } from '../ml/fixtures';
import { labelColor } from './labelColors';
import { analysisFrames, analysisViews, testViews, viewFrames } from './objectViews';
import { photoAnalysis } from './fixtures';

describe('object views', () => {
  it('splits a photo analysis into the local, the AI and the merged list', () => {
    const v = analysisViews(photoAnalysis());
    expect(v.local?.map((r) => [r.key, r.label_de, r.mergedIdx])).toEqual([[0, 'Weinglas', 0]]);
    expect(v.ai?.map((r) => [r.key, r.label_de, r.mergedIdx])).toEqual([
      [0, 'Sektglas', 0],
      [1, 'Hut', 1],
    ]);
    expect(v.merged.map((r) => [r.key, r.sources, r.parts.map((p) => p.score)])).toEqual([
      [0, ['local', 'claude'], [0.91, 0.75]],
      [1, ['claude'], [0.8]],
    ]);
    expect([v.aiTitle, v.aiModel]).toEqual(['Claude', 'claude-haiku-5-5']);
  });

  it('a list whose source never ran is null, an empty run is []', () => {
    const a = { ...photoAnalysis(), objects_local: [], objects_ai: [], runs: [] };
    expect(analysisViews(a).local).toBeNull();
    expect(analysisViews(a).ai).toBeNull();
    const ran = { ...a, runs: photoAnalysis().runs };
    expect(analysisViews(ran).local).toEqual([]);
  });

  it("frames in the thing's colour (as on Live), outlined by who found it", () => {
    const v = analysisViews(photoAnalysis());
    const merged = viewFrames(v.merged, 'merged');
    expect(merged.map((f) => [f.label, f.both, f.color, f.outline])).toEqual([
      ['Weinglas · beide', true, labelColor('wine glass').color, 'double'],
    ]);
    const local = viewFrames(v.local ?? [], 'local')[0];
    expect([local?.both, local?.outline, local?.color]).toEqual([
      false,
      'solid',
      labelColor('wine glass').color,
    ]);
    // the same thing has the same colour in every view; an AI's frame is dashed
    const ai = viewFrames(v.ai ?? [], 'ai');
    expect(ai.every((f) => f.outline === 'dashed')).toBe(true);
    expect(ai.map((f) => f.color)).toEqual(ai.map((f) => labelColor(f.key ?? '').color));
    // faces and hands stay whatever the view
    expect(analysisFrames(photoAnalysis(), 'ai').map((f) => f.kind)).toEqual(['face', 'hand', 'object']);
  });

  it('maps a test result: positions link the source lists to the merged preview', () => {
    const v = testViews(testResult);
    expect(v.local?.map((r) => r.mergedIdx)).toEqual([0]);
    expect(v.ai?.map((r) => r.mergedIdx)).toEqual([0, 1]);
    expect(v.merged[0]?.parts.map((p) => `${p.source}:${p.label_de}`)).toEqual([
      'local:Weinglas',
      'claude:Sektglas',
    ]);
    expect(testViews({ ...testResult, external: null }).ai).toBeNull();
  });
});
