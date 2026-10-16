import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { CategoryWinner, WallCategory } from '../api/types';
import { photo } from '../fixtures.test-util';
import {
  captionOf,
  compactColumns,
  coverBox,
  highlightIds,
  verdictAlign,
  verdictIndex,
  visibleCategories,
} from './categories';
import { Categories, COMPACT_COMMENTS } from './Modes';

const COMMENT = { text: 'Die Sonnenbrille von Gast 2 ist zu cool für diese Welt.', emoji: '😎' };

function winner(i: number, over: Partial<CategoryWinner> = {}): CategoryWinner {
  return { photo: photo(i + 1, String(i)), value: 0.9 - i / 10, label: `Platz ${i + 1}`, ...over };
}

function category(
  n: number,
  over: Partial<WallCategory> = {},
  each: (i: number) => Partial<CategoryWinner> = () => ({}),
): WallCategory {
  return {
    id: 'coolstes_objekt',
    emoji: '🏆',
    title: 'Das coolste Objekt',
    line: 'Was die KI am coolsten findet',
    winners: Array.from({ length: n }, (_, i) => winner(i, each(i))),
    verdict: null,
    ...over,
  };
}

const OLD_VERDICT = { text: 'Der Hut von Gast 2 ist unschlagbar.', emoji: '🎩', photo_id: 'p2' };

describe('category winners and comments', () => {
  it('keeps up to 10 winners in the server order', () => {
    const [out] = visibleCategories([category(12)], [], []);
    expect(out?.winners.map((w) => w.photo.id)).toEqual(Array.from({ length: 10 }, (_, i) => `p${i + 1}`));
    expect(highlightIds([category(4)])).toEqual(['p1', 'p2', 'p3', 'p4']);
  });

  it('keeps each winner its comment and drops removed photos with theirs', () => {
    const c = category(3, {}, (i) => (i === 1 ? { comment: COMMENT } : {}));
    const [kept] = visibleCategories([c], [], ['p9']);
    expect(kept?.winners.map((w) => w.comment)).toEqual([null, COMMENT, null]);
    const [gone] = visibleCategories([c], [], ['p2']);
    expect(gone?.winners.map((w) => w.photo.id)).toEqual(['p1', 'p3']);
    expect(gone?.winners.every((w) => w.comment === null)).toBe(true);
  });

  it('turns an older server’s single verdict into its winner’s comment', () => {
    const [out] = visibleCategories([category(3, { verdict: OLD_VERDICT })], [], []);
    expect(out?.winners[1]?.comment).toEqual({ text: OLD_VERDICT.text, emoji: '🎩' });
    expect(verdictIndex(category(3, { verdict: { ...OLD_VERDICT, photo_id: null } }))).toBe(0);
    const [gone] = visibleCategories([category(3, { verdict: OLD_VERDICT })], [], ['p2']);
    expect(gone?.winners.every((w) => w.comment === null)).toBe(true);
  });

  it('aligns a comment under its photo, sizes the compact grid', () => {
    expect([1, 4, 5, 6, 7, 10].map(compactColumns)).toEqual([2, 2, 3, 3, 4, 5]);
    expect(verdictAlign(0, 1)).toBe('center');
    expect([0, 1, 2].map((i) => verdictAlign(i, 3))).toEqual(['start', 'center', 'end']);
  });
});

describe('the focus object’s frame', () => {
  const box = { x: 0.2, y: 0.3, w: 0.2, h: 0.1 };

  it('is the box itself in percent where the cell has the photo’s shape (the normal row)', () => {
    expect(coverBox(box, 0.75, 0.75)).toEqual({ left: 20, top: 30, width: 20, height: 10 });
    expect(coverBox(null, 0.75, 0.75)).toBeNull();
    expect(coverBox({ ...box, w: 0 }, 0.75, 0.75)).toBeNull();
  });

  it('shifts and scales it in a cropped 3:4 cell (cover), cut at the edges or left out', () => {
    // a 4:3 photo in a 3:4 cell: 16/9 of the cell wide, centred (offset -7/18)
    const k = 16 / 9;
    const x = (1 - k) / 2 + 0.4 * k;
    expect(coverBox({ x: 0.4, y: 0.3, w: 0.2, h: 0.1 }, 4 / 3, 3 / 4)).toEqual({
      left: Math.round(x * 10_000) / 100,
      top: 30,
      width: Math.round(0.2 * k * 10_000) / 100,
      height: 10,
    });
    // a tall photo (9:16) in a 3:4 cell: cropped top and bottom
    const t = coverBox({ x: 0.1, y: 0.5, w: 0.3, h: 0.1 }, 9 / 16, 3 / 4);
    expect(t?.left).toBe(10);
    expect(t?.width).toBe(30);
    expect(t?.top).toBeCloseTo(50, 0);
    // far left on a wide photo: out of view, no frame
    expect(coverBox({ x: 0, y: 0.3, w: 0.15, h: 0.2 }, 4 / 3, 3 / 4)).toBeNull();
    // half in view: cut at the edge
    const cut = coverBox({ x: 0.15, y: 0.3, w: 0.2, h: 0.2 }, 4 / 3, 3 / 4);
    expect(cut?.left).toBe(0);
  });
});

describe('the caption on the wall', () => {
  it('reads the main line and chip, or an older server’s label', () => {
    expect(captionOf(winner(0, { headline: 'Sonnenbrille', detail: '0,93 Coolness' }))).toEqual({
      headline: 'Sonnenbrille',
      detail: '0,93 Coolness',
    });
    expect(captionOf(winner(0, { label: '7 Personen' }))).toEqual({ headline: '7 Personen', detail: null });
  });

  it('shows head, place, main line, value chip, „von“, the frame and the comment with „KI“', () => {
    const c = category(3, {}, (i) => ({
      headline: i === 0 ? 'Sonnenbrille' : `Hut ${i}`,
      detail: `0,9${3 - i} Coolness`,
      object: {
        idx: 0,
        label_de: i === 0 ? 'Sonnenbrille' : 'Hut',
        value: 0.93,
        box: i === 2 ? null : { x: 0.25, y: 0.1, w: 0.3, h: 0.2 },
      },
      comment: i === 0 ? COMMENT : null,
    }));
    render(<Categories categories={[c]} perCategoryS={10} />);
    const card = screen.getByTestId('wall-category');
    expect(card.querySelector('.wall-cat-title')?.textContent).toBe('Das coolste Objekt');
    expect(card.querySelector('.wall-cat-line')?.textContent).toBe('Was die KI am coolsten findet');
    const first = must(card.querySelector<HTMLElement>('.wall-cat-photo[data-index="0"]'));
    expect(within(first).getByTestId('wall-caption').textContent).toBe('1Sonnenbrille0,93 Coolness');
    expect(first.querySelector('.wall-cat-value')?.textContent).toBe('0,93 Coolness');
    expect(first.querySelector('.wall-cat-by')?.textContent).toBe('von Gast 0');
    const frame = within(first).getByTestId('wall-object-box');
    expect(frame.style.left).toBe('25%');
    expect(frame.style.width).toBe('30%');
    expect(frame.textContent).toBe('Sonnenbrille');
    // no box: no frame, the name stays
    const third = must(card.querySelector<HTMLElement>('.wall-cat-photo[data-index="2"]'));
    expect(within(third).queryByTestId('wall-object-box')).toBeNull();
    expect(third.querySelector('.wall-cat-headline')?.textContent).toBe('Hut 2');
    // the comment under its photo; the „KI“ marker is wall.css's
    const verdict = within(first).getByTestId('wall-verdict');
    expect(verdict.textContent).toBe(`😎${COMMENT.text}`);
    expect(verdict.className).toBe('wall-cat-verdict');
    expect(verdict.dataset.align).toBe('start');
    expect(first.hasAttribute('data-many')).toBe(false);
  });

  it('a single winner has no place mark, a value without an object no chip', () => {
    render(
      <Categories
        categories={[category(1, {}, () => ({ headline: '7 Personen', detail: null }))]}
        perCategoryS={10}
      />,
    );
    const caption = screen.getByTestId('wall-caption');
    expect(caption.textContent).toBe('7 Personen');
    expect(caption.querySelector('.wall-cat-place')).toBeNull();
    expect(caption.querySelector('.wall-cat-value')).toBeNull();
  });

  it('puts several comments each under its own photo, as wide as it', () => {
    render(
      <Categories
        categories={[category(3, {}, (i) => ({ comment: i < 2 ? { ...COMMENT, emoji: null } : null }))]}
        perCategoryS={10}
      />,
    );
    const verdicts = screen.getAllByTestId('wall-verdict');
    expect(verdicts.map((v) => v.closest('figure')?.dataset.index)).toEqual(['0', '1']);
    expect(verdicts.every((v) => v.closest('figure')?.hasAttribute('data-many'))).toBe(true);
    expect(verdicts[0]?.textContent).toBe(COMMENT.text);
  });

  it('shows more than 3 winners as a compact grid: frames mapped to the 3:4 cell, comments under it', () => {
    const wide = { width: 1440, height: 1080 };
    const c = category(7, {}, (i) => ({
      photo: photo(i + 1, String(i), wide),
      object: { idx: 0, label_de: 'Hut', value: 0.8, box: { x: 0.4, y: 0.3, w: 0.2, h: 0.1 } },
      comment: i % 2 === 1 ? { ...COMMENT, text: `Kommentar ${i}` } : null,
    }));
    render(<Categories categories={[c]} perCategoryS={10} />);
    const winners = must(screen.getByTestId('wall-category').querySelector<HTMLElement>('.wall-cat-winners'));
    expect(winners.getAttribute('data-compact')).toBe('');
    expect(winners.getAttribute('data-cols')).toBe('4');
    expect(screen.getAllByRole('img')).toHaveLength(7);
    // the 4:3 photo in the 3:4 cell: the frame moved and widened
    const frame = must(winners.querySelector<HTMLElement>('[data-testid="wall-object-box"]'));
    expect(frame.style.left).toBe('32.22%');
    expect(frame.style.width).toBe('35.56%');
    // the comments: under the grid with their place, at most COMPACT_COMMENTS
    const verdicts = screen.getAllByTestId('wall-verdict');
    expect(verdicts).toHaveLength(COMPACT_COMMENTS);
    expect(verdicts.every((v) => v.closest('figure') === null)).toBe(true);
    expect(verdicts.map((v) => v.dataset.place)).toEqual(['2', '4', '6']);
    expect([...winners.querySelectorAll('[data-verdict]')].map((f) => f.getAttribute('data-index'))).toEqual([
      '1',
      '3',
      '5',
    ]);
  });

  it('shows no comment without one', () => {
    render(<Categories categories={[category(2)]} perCategoryS={10} />);
    expect(screen.queryByTestId('wall-verdict')).toBeNull();
  });
});

function must<T>(value: T | null | undefined): T {
  if (value === null || value === undefined) throw new Error('missing');
  return value;
}
