import { afterEach, describe, expect, it } from 'vitest';
import { actionAreas, measureToastRoom, toastLift, translateY, type Box } from './toastPlacement';

// a 390 × 844 phone; the toast is 56 px high, 16 px from the bottom, 16 px gutters
const box = (top: number, bottom: number, left = 0, right = 390): Box => ({ top, bottom, left, right });
const TOAST = box(772, 828, 16, 374);
const MIN_TOP = 8;

describe('toastLift', () => {
  it('stays put with nothing under it', () => {
    expect(toastLift(TOAST, [], MIN_TOP)).toBe(0);
    // the bottom bar below the toast's place, a header far above
    expect(toastLift(TOAST, [box(830, 844), box(0, 56)], MIN_TOP)).toBe(0);
  });

  it('ignores an area beside it (bottom right on desktop)', () => {
    expect(toastLift(TOAST, [box(700, 844, 380, 390)], MIN_TOP)).toBe(0);
  });

  it('moves just above the area under it (8 px gap)', () => {
    // the viewer's panel: 560-844
    expect(toastLift(TOAST, [box(560, 844)], MIN_TOP)).toBe(772 - (560 - 8 - 56));
  });

  it('clears areas stacked above each other (camera: controls, hint, filter strip)', () => {
    const controls = box(709, 789);
    const hint = box(660, 697);
    const strip = box(610, 650);
    const lift = toastLift(TOAST, [controls, hint, strip], MIN_TOP);
    expect(772 - lift + 56).toBe(610 - 8);
  });

  it('above a sheet that leaves room, above its footer when the sheet fills the screen', () => {
    const footer = box(764, 844);
    expect(toastLift(TOAST, [box(600, 844), footer], MIN_TOP)).toBe(772 - (600 - 8 - 56));
    expect(toastLift(TOAST, [box(30, 844), footer], MIN_TOP)).toBe(772 - (764 - 8 - 56));
  });

  it('never leaves the top edge, and with no room at all it keeps its place', () => {
    const lift = toastLift(TOAST, [box(70, 844), box(500, 844)], MIN_TOP);
    expect(772 - lift).toBe(500 - 8 - 56);
    expect(toastLift(TOAST, [box(40, 844)], MIN_TOP)).toBe(0);
  });

  it('never moves onto a bar above: it takes the free gap, or keeps its place', () => {
    // landscape phone camera column: header, filter strip, hint, controls
    const toast = box(302, 358);
    const [hint, controls] = [box(250, 290), box(300, 380)];
    expect(302 - toastLift(toast, [box(0, 56), box(150, 240), hint, controls], MIN_TOP)).toBe(150 - 8 - 56);
    expect(toastLift(toast, [box(0, 100), box(150, 240), hint, controls], MIN_TOP)).toBe(0);
  });
});

describe('translateY', () => {
  it('reads the y of a computed translate', () => {
    expect(translateY('none')).toBe(0);
    expect(translateY('0px -96px')).toBe(-96);
    expect(translateY('12px')).toBe(0);
  });
});

function area(parent: HTMLElement, top: number): HTMLElement {
  const el = document.createElement('div');
  el.setAttribute('data-toast-avoid', '');
  el.getBoundingClientRect = () => new DOMRect(0, top, 390, 40);
  parent.append(el);
  return el;
}

/** an open sheet or viewer (`vb-scrim`) */
function layer(): HTMLElement {
  const el = document.createElement('div');
  el.className = 'vb-scrim';
  document.body.append(el);
  return el;
}

describe('actionAreas', () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it('takes the page areas, or only the topmost open sheet or viewer', () => {
    area(document.body, 780);
    expect(actionAreas().map((b) => b.top)).toEqual([780]);
    const viewer = layer();
    area(viewer, 600);
    expect(actionAreas().map((b) => b.top)).toEqual([600]);
    const confirm = layer();
    area(confirm, 700);
    expect(actionAreas().map((b) => b.top)).toEqual([700]);
    // the confirm dialog slides out: the viewer counts again
    confirm.setAttribute('data-exiting', 'true');
    expect(actionAreas().map((b) => b.top)).toEqual([600]);
  });

  it('skips areas that are not shown', () => {
    const el = area(document.body, 780);
    el.getBoundingClientRect = () => new DOMRect(0, 0, 0, 0);
    expect(actionAreas()).toEqual([]);
  });
});

describe('measureToastRoom', () => {
  it('reaches from the toast top (where it rests) to the window bottom, plus the gap', () => {
    const region = document.createElement('div');
    document.body.append(region);
    region.getBoundingClientRect = () => new DOMRect(16, 772, 358, 56);
    const root = document.documentElement;
    const before = Object.getOwnPropertyDescriptor(root, 'clientHeight');
    Object.defineProperty(root, 'clientHeight', { configurable: true, value: 844 });
    try {
      expect(measureToastRoom(region, 0)).toBe(844 - 772 + 8);
      // lifted above a bar: the room grows with it
      expect(measureToastRoom(region, 64)).toBe(844 - 772 + 64 + 8);
    } finally {
      if (before) Object.defineProperty(root, 'clientHeight', before);
      else Reflect.deleteProperty(root, 'clientHeight');
      region.remove();
    }
  });
});
