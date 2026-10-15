import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { WallCategory } from '../api/types';
import { photo } from '../fixtures.test-util';
import { compactColumns, highlightIds, verdictIndex, visibleCategories } from './categories';
import { Categories } from './Modes';

function category(n: number, verdict: WallCategory['verdict'] = null, id = 'coolstes_objekt'): WallCategory {
  return {
    id,
    emoji: '🏆',
    title: 'Das coolste Objekt',
    line: 'Was die KI am coolsten findet',
    winners: Array.from({ length: n }, (_, i) => ({
      photo: photo(i + 1, String(i)),
      value: n - i,
      label: `Platz ${i + 1}`,
    })),
    verdict,
  };
}

const VERDICT = { text: 'Der Hut von Gast 2 ist unschlagbar.', emoji: '🎩', photo_id: 'p2' };

describe('category winners and verdicts', () => {
  it('keeps up to 10 winners in the server order', () => {
    const [out] = visibleCategories([category(12)], [], []);
    expect(out?.winners.map((w) => w.photo.id)).toEqual(Array.from({ length: 10 }, (_, i) => `p${i + 1}`));
    expect(highlightIds([category(4)])).toEqual(['p1', 'p2', 'p3', 'p4']);
  });

  it('drops a verdict whose photo was removed', () => {
    const [kept] = visibleCategories([category(3, VERDICT)], [], ['p9']);
    expect(kept?.verdict).toEqual(VERDICT);
    const [gone] = visibleCategories([category(3, VERDICT)], [], ['p2']);
    expect(gone?.verdict).toBeNull();
    expect(gone?.winners.map((w) => w.photo.id)).toEqual(['p1', 'p3']);
  });

  it('puts the verdict under its photo, else under the first', () => {
    expect(verdictIndex(category(3, VERDICT))).toBe(1);
    expect(verdictIndex(category(3, { ...VERDICT, photo_id: null }))).toBe(0);
    expect(verdictIndex(category(3, { ...VERDICT, photo_id: 'p77' }))).toBe(0);
    expect([1, 4, 5, 6, 7, 10].map(compactColumns)).toEqual([2, 2, 3, 3, 4, 5]);
  });

  it('renders the verdict text and emoji under the winning photo', () => {
    render(<Categories categories={[category(3, VERDICT)]} perCategoryS={10} />);
    const verdict = screen.getByTestId('wall-verdict');
    expect(verdict.textContent).toBe('🎩Der Hut von Gast 2 ist unschlagbar.');
    const figure = verdict.closest('figure');
    expect(figure?.dataset.index).toBe('1');
    expect(figure?.querySelector('img')?.getAttribute('alt')).toBe('Foto von Gast 1');
  });

  it('shows more than 3 winners as a compact grid, the verdict under it', () => {
    render(<Categories categories={[category(7, VERDICT)]} perCategoryS={10} />);
    const winners = screen.getByTestId('wall-category').querySelector('.wall-cat-winners');
    expect(winners?.getAttribute('data-compact')).toBe('');
    expect(winners?.getAttribute('data-count')).toBe('7');
    expect(winners?.getAttribute('data-cols')).toBe('4');
    expect(screen.getAllByRole('img')).toHaveLength(7);
    const verdict = screen.getByTestId('wall-verdict');
    expect(verdict.closest('figure')).toBeNull();
    expect(winners?.querySelector('[data-verdict]')?.getAttribute('data-index')).toBe('1');
  });

  it('shows no verdict without one', () => {
    render(<Categories categories={[category(2)]} perCategoryS={10} />);
    expect(screen.queryByTestId('wall-verdict')).toBeNull();
  });
});
