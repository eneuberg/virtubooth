import { act, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { applyStyle, type ThemeStyle } from '@/styles/theme';
import { aim, settled, SPRINGS, step, type Pupil } from './eyes';
import { GooglyEyes } from './GooglyEyes';
import { currentStyle, isPlayful } from './style';

afterEach(() => {
  document.documentElement.removeAttribute('data-vb-style');
});

describe('googly eye physics', () => {
  it('looks towards the target, all the way once it is far, and sags a little', () => {
    const right = aim({ x: 0, y: 0 }, { x: 500, y: 0 }, 20);
    expect(right.x).toBeGreaterThan(0.9);
    expect(right.y).toBeGreaterThan(0);
    expect(Math.hypot(right.x, right.y)).toBeLessThanOrEqual(1);
    // close by: only part of the way
    expect(aim({ x: 0, y: 0 }, { x: 10, y: 0 }, 20).x).toBeLessThan(0.5);
    // straight at it: just the sag
    expect(aim({ x: 5, y: 5 }, { x: 5, y: 5 }, 20)).toEqual({ x: 0, y: 0.18 });
  });

  it('overshoots its goal, then comes to rest there', () => {
    let p: Pupil = { pos: { x: 0, y: 0 }, vel: { x: 0, y: 0 } };
    const goal = { x: 0.6, y: 0 };
    let peak = 0;
    let frames = 0;
    while (!settled(p, goal) && frames < 600) {
      p = step(p, goal, SPRINGS[0], 1 / 60);
      peak = Math.max(peak, p.pos.x);
      frames++;
    }
    expect(peak).toBeGreaterThan(0.65); // the wobble
    expect(settled(p, goal)).toBe(true);
    expect(frames).toBeLessThan(600);
  });

  it('never leaves its eye', () => {
    let p: Pupil = { pos: { x: 0.9, y: 0 }, vel: { x: 40, y: 0 } };
    for (let i = 0; i < 30; i++) {
      p = step(p, { x: 1, y: 0 }, SPRINGS[1], 1 / 60);
      expect(Math.hypot(p.pos.x, p.pos.y)).toBeLessThanOrEqual(1 + 1e-9);
    }
  });
});

describe('GooglyEyes', () => {
  it('renders nothing in the calm style, two eyes in the party and goofy ones', async () => {
    applyStyle('elegant');
    const { container } = render(<GooglyEyes />);
    expect(container.querySelector('.vb-googly')).toBeNull();
    act(() => applyStyle('party'));
    // the MutationObserver reports asynchronously
    await waitFor(() => expect(container.querySelector('.vb-googly')).not.toBeNull());
    expect(container.querySelector('.vb-googly')?.getAttribute('aria-hidden')).toBe('true');
    expect(container.querySelectorAll('.vb-googly-pupil')).toHaveLength(2);
    act(() => applyStyle('goofy'));
    act(() => applyStyle('elegant'));
    await waitFor(() => expect(container.querySelector('.vb-googly')).toBeNull());
    act(() => applyStyle('goofy'));
    await waitFor(() => expect(container.querySelector('.vb-googly')).not.toBeNull());
  });

  it('no style on the page yet: no eyes', () => {
    const { container } = render(<GooglyEyes />);
    expect(container.querySelector('.vb-googly')).toBeNull();
    expect(isPlayful()).toBe(false);
  });

  it('squeezes shut for the photo', () => {
    applyStyle('party');
    const { container } = render(<GooglyEyes mood="shut" />);
    const eyes = container.querySelector('.vb-googly');
    expect(eyes?.hasAttribute('data-blink')).toBe(true);
    expect(eyes?.getAttribute('data-mood')).toBe('shut');
  });

  it('applyStyle knows three styles; anything else is the default, party', () => {
    applyStyle(undefined);
    expect(document.documentElement.getAttribute('data-vb-style')).toBe('party');
    applyStyle('wild' as ThemeStyle);
    expect(document.documentElement.getAttribute('data-vb-style')).toBe('party');
    for (const style of ['elegant', 'party', 'goofy'] as const) {
      applyStyle(style);
      expect(document.documentElement.getAttribute('data-vb-style')).toBe(style);
      expect(currentStyle()).toBe(style);
      expect(isPlayful()).toBe(style !== 'elegant');
    }
  });
});
