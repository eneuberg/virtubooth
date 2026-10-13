import { describe, expect, it } from 'vitest';
import { ALGORITHMS, type WallAlgorithm, type WallPhoto } from '../api/types';
import { photo, pool } from '../fixtures.test-util';
import { seededRng } from '../rng';
import { createSelector, emptyContext, recordShown, type SelectContext, type Selector } from './algorithms';

function draw(sel: Selector, photos: readonly WallPhoto[], ctx: SelectContext, k: number): string[] {
  const out: string[] = [];
  for (let i = 0; i < k; i++) {
    const p = sel.next(photos, ctx);
    if (!p) break;
    recordShown(ctx, p.id);
    out.push(p.id);
  }
  return out;
}

const make = (kind: WallAlgorithm, n = 12, seed = 7) => createSelector(kind, { n }, seededRng(seed));

describe('selection algorithms', () => {
  it('newest cycles the newest n, newest first', () => {
    const ids = draw(make('newest', 3), pool(10), emptyContext(), 7);
    expect(ids).toEqual(['p10', 'p9', 'p8', 'p10', 'p9', 'p8', 'p10']);
  });

  it('newest puts a new arrival into the cycle', () => {
    const sel = make('newest', 3);
    const ctx = emptyContext();
    expect(draw(sel, pool(10), ctx, 2)).toEqual(['p10', 'p9']);
    const more = [photo(11), ...pool(10)];
    expect(draw(sel, more, ctx, 2)).toEqual(['p11', 'p10']);
  });

  it('random never shows the same photo twice in a row', () => {
    const ids = draw(make('random'), pool(3), emptyContext(), 200);
    for (let i = 1; i < ids.length; i++) expect(ids[i]).not.toBe(ids[i - 1]);
    expect(new Set(ids).size).toBe(3);
  });

  it('shuffle empties the bag before repeating, new photos join the bag', () => {
    const sel = make('shuffle');
    const ctx = emptyContext();
    const first = draw(sel, pool(5), ctx, 5);
    expect(new Set(first).size).toBe(5);
    // a new photo arrives mid-round: it is drawn in the same round
    const sel2 = make('shuffle', 12, 3);
    const ctx2 = emptyContext();
    const part = draw(sel2, pool(4), ctx2, 2);
    const rest = draw(sel2, [photo(5), ...pool(4)], ctx2, 3);
    expect(new Set([...part, ...rest])).toEqual(new Set(['p1', 'p2', 'p3', 'p4', 'p5']));
    // next round starts with anything but the last one
    const next = draw(sel2, [photo(5), ...pool(4)], ctx2, 1);
    expect(next[0]).not.toBe(rest.at(-1));
  });

  it('fair alternates between guests, newest unshown photo per guest', () => {
    // a has p4, p3, p2 (newest first); b has p1
    const photos = pool(4, (n) => (n === 1 ? 'b' : 'a'));
    const ids = draw(make('fair'), photos, emptyContext(), 6);
    expect(ids).toEqual(['p4', 'p1', 'p3', 'p1', 'p2', 'p1']);
  });

  it('fair gives a new guest the next turn', () => {
    const sel = make('fair');
    const ctx = emptyContext();
    const photos = pool(4, (n) => (n % 2 ? 'a' : 'b'));
    draw(sel, photos, ctx, 3);
    const ids = draw(sel, [photo(9, 'c'), ...photos], ctx, 1);
    expect(ids).toEqual(['p9']);
  });

  it('least_shown picks the least shown, ties go to the newer photo', () => {
    const ctx = emptyContext();
    ctx.shown.set('p3', 2);
    ctx.shown.set('p2', 1);
    const ids = draw(make('least_shown'), pool(3), ctx, 3);
    expect(ids).toEqual(['p1', 'p2', 'p1']);
  });

  it('fresh_first lets unshown arrivals jump the queue in arrival order', () => {
    const sel = make('fresh_first');
    const ctx = emptyContext();
    const first = draw(sel, pool(5), ctx, 2);
    const photos = [photo(7), photo(6), ...pool(5)];
    ctx.fresh = ['p6', 'p7'];
    expect(draw(sel, photos, ctx, 2)).toEqual(['p6', 'p7']);
    // shown once: they no longer jump, and the shuffle bag counts them as drawn
    const next = draw(sel, photos, ctx, 3);
    expect(new Set(next)).toEqual(
      new Set(['p1', 'p2', 'p3', 'p4', 'p5'].filter((id) => !first.includes(id))),
    );
  });

  it('highlights shows the category winners first, then shuffles', () => {
    const ctx = emptyContext();
    ctx.highlights = ['p2', 'p9', 'p4'];
    const ids = draw(make('highlights'), pool(5), ctx, 7);
    expect(ids.slice(0, 2)).toEqual(['p2', 'p4']); // p9 is not visible
    // the bag already counts the winners as drawn
    expect(new Set(ids.slice(2, 5))).toEqual(new Set(['p1', 'p3', 'p5']));
  });

  it.each(ALGORITHMS)('%s never returns a removed photo', (kind) => {
    const sel = make(kind, 3);
    const ctx = emptyContext();
    ctx.fresh = ['p5', 'p4'];
    ctx.highlights = ['p5', 'p3'];
    let photos = pool(6, (n) => (n % 2 ? 'a' : 'b'));
    draw(sel, photos, ctx, 2);
    const removed: string[] = [];
    for (const gone of ['p5', 'p6', 'p3']) {
      removed.push(gone);
      photos = photos.filter((p) => p.id !== gone);
      for (const id of draw(sel, photos, ctx, 8)) expect(removed).not.toContain(id);
    }
  });

  it.each(ALGORITHMS)('%s answers null for an empty pool', (kind) => {
    expect(make(kind).next([], emptyContext())).toBeNull();
  });
});
