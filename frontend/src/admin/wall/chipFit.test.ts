import { describe, expect, it } from 'vitest';
import { chipRows, fitChips } from './chipFit';

describe('chipRows', () => {
  it('wraps like flex-wrap, a chip wider than the row taking one row', () => {
    expect(chipRows([], 100, 4)).toBe(0);
    expect(chipRows([48, 48], 100, 4)).toBe(1);
    expect(chipRows([48, 49], 100, 4)).toBe(2);
    expect(chipRows([300, 20, 20], 100, 4)).toBe(2);
  });
});

describe('fitChips', () => {
  it('shows every chip when they fit the rows', () => {
    expect(fitChips([40, 40, 40, 40], 100, 4, 2, 24)).toBe(4);
    expect(fitChips([], 100, 4, 2, 24)).toBe(0);
  });

  it('ends in „+N“: the most chips that fit together with the more chip', () => {
    // rows: [40 40] [40 40] [40] → 4 chips + „+1“ would need a third row, 3 + „+2“ fit
    expect(fitChips([40, 40, 40, 40, 40], 100, 4, 2, 24)).toBe(3);
    // a long first chip fills a row by itself (truncated), „+2“ shares the second
    expect(fitChips([200, 60, 60, 60], 100, 4, 2, 24)).toBe(2);
    // the more chip alone when even the first chip leaves no room for it
    expect(fitChips([200, 200, 60], 100, 4, 2, 24)).toBe(1);
    expect(fitChips([200, 200, 60], 100, 4, 1, 24)).toBe(0);
  });

  it('counts everything as fitting before the area has a width', () => {
    expect(fitChips([40, 40, 40, 40, 40], 0, 4, 2, 24)).toBe(5);
  });
});
