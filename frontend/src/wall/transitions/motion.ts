/**
 * The DOM transitions (WAAPI only: CSP-safe, no stylesheet changes at runtime).
 */
import { releaseImage } from '../tv/preload';
import { captionIn, cardOf, fadeOut, imgOf, picOf, play, type Transition } from './types';

export const crossfade: Transition = ({ from, to, ms, signal }) =>
  play(
    [
      to.animate([{ opacity: 0 }, { opacity: 1 }], {
        duration: ms,
        easing: 'ease-in-out',
        fill: 'backwards',
      }),
      ...fadeOut(from, ms),
    ],
    signal,
  );

/** Crossfade, and the photo keeps zooming and drifting slowly while it is shown. */
export const kenburns: Transition = (args) => {
  const img = imgOf(args.to);
  if (img) {
    const dx = (args.rng() - 0.5) * 6;
    const dy = (args.rng() - 0.5) * 6;
    const zoomIn = args.rng() < 0.6;
    const near = 'scale(1.14) translate(' + dx.toFixed(2) + '%, ' + dy.toFixed(2) + '%)';
    const far = 'scale(1.02) translate(0, 0)';
    img.animate([{ transform: zoomIn ? far : near }, { transform: zoomIn ? near : far }], {
      duration: args.ms + args.hold + 1500,
      easing: 'linear',
      fill: 'forwards',
    });
  }
  return crossfade({ ...args, ms: Math.max(args.ms, 900) });
};

/** Overshooting scale + lift. */
export const spring: Transition = ({ from, to, ms, signal }) => {
  const card = cardOf(to);
  return play(
    [
      card.animate(
        [
          { transform: 'translateY(14vh) scale(0.6) rotate(-4deg)', opacity: 0 },
          { transform: 'translateY(-2.5vh) scale(1.07) rotate(1.5deg)', opacity: 1, offset: 0.42 },
          { transform: 'translateY(1vh) scale(0.97) rotate(-0.6deg)', offset: 0.62 },
          { transform: 'translateY(-0.4vh) scale(1.015) rotate(0.2deg)', offset: 0.8 },
          { transform: 'none', opacity: 1 },
        ],
        { duration: ms, easing: 'ease-out', fill: 'backwards' },
      ),
      ...captionIn(to, ms * 0.5, ms * 0.45),
      ...(from
        ? [
            cardOf(from).animate(
              [
                { transform: 'none', opacity: 1 },
                { transform: 'translateY(-6vh) scale(0.82)', opacity: 0 },
              ],
              { duration: ms * 0.55, easing: 'ease-in', fill: 'forwards' },
            ),
          ]
        : []),
      ...fadeOut(from, ms * 0.3, ms * 0.4),
    ],
    signal,
  );
};

const CHANNELS = ['#ff0000', '#00ff00', '#0000ff'] as const;
const GLITCH_STEPS = 9;

/** One step of one colour channel: the band (insets in %) that shows the new photo. */
export interface GlitchSlice {
  top: number;
  bottom: number;
  /** shift of the new photo inside its band, in % */
  x: number;
  y: number;
}

/**
 * The glitch's bands: per channel GLITCH_STEPS + 1 slices that grow from a thin band to
 * the whole picture; the last one is the settled photo (no inset, no shift).
 */
export function glitchSlices(rng: () => number, steps = GLITCH_STEPS): GlitchSlice[][] {
  return CHANNELS.map((_, i) => {
    const slices: GlitchSlice[] = [];
    for (let s = 0; s <= steps; s++) {
      if (s === steps) {
        slices.push({ top: 0, bottom: 0, x: 0, y: 0 });
        continue;
      }
      const p = s / steps;
      const amp = (1 - p) * 7;
      const size = 12 + p * 70 + rng() * 18; // the band's height in %
      const top = Math.floor(rng() * Math.max(0, 100 - size));
      slices.push({
        top,
        bottom: Math.max(0, Math.floor(100 - top - size)),
        x: (rng() - 0.5) * 2 * amp + (i - 1) * amp * 0.6,
        y: (rng() - 0.5) * amp * 0.4,
      });
    }
    return slices;
  });
}

/** The band of a slice as a clip-path. */
export function bandClip({ top, bottom }: GlitchSlice): string {
  return `inset(${top}% 0 ${bottom}% 0)`;
}

/** Everything outside the band (two rectangles in one polygon; empty for the full band). */
export function outsideClip({ top, bottom }: GlitchSlice): string {
  const a = `${top}%`;
  const b = `${100 - bottom}%`;
  return `polygon(0 0, 100% 0, 100% ${a}, 0 ${a}, 0 ${b}, 100% ${b}, 100% 100%, 0 100%)`;
}

/** layer (clipped, screen-blended) > shift (moves) > [image copy, channel tint] */
function channelLayer(img: HTMLImageElement, tint: string): { layer: HTMLElement; shift: HTMLElement } {
  const layer = document.createElement('div');
  layer.className = 'wall-glitch-layer';
  const shift = document.createElement('div');
  shift.className = 'wall-glitch-shift';
  const copy = img.cloneNode(false);
  if (copy instanceof HTMLImageElement) {
    copy.removeAttribute('class');
    copy.alt = '';
    shift.append(copy);
  }
  const color = document.createElement('div');
  color.className = 'wall-glitch-tint';
  color.style.backgroundColor = tint;
  shift.append(color);
  layer.append(shift);
  return { layer, shift };
}

/**
 * RGB split: per colour channel the new photo shows in a jumping, shifted band and the
 * old photo everywhere else, so the slices cut between the two photos (the first photo
 * of a wall cuts against black). The bands grow until the new photo fills the picture.
 */
export const glitch: Transition = (args) => {
  const { from, to, ms, signal, rng } = args;
  const pic = picOf(to);
  const img = imgOf(to);
  if (!img) return crossfade(args);
  const oldImg = from ? imgOf(from) : null;
  const box = document.createElement('div');
  box.className = 'wall-glitch';
  const animations: Animation[] = [];
  const step = { duration: ms, fill: 'both' } as const;
  const jump = 'steps(1, end)';
  glitchSlices(rng).forEach((slices, i) => {
    const tint = CHANNELS[i]!;
    if (oldImg) {
      const old = channelLayer(oldImg, tint);
      box.append(old.layer);
      animations.push(
        old.layer.animate(
          slices.map((s) => ({ clipPath: outsideClip(s), easing: jump })),
          step,
        ),
      );
    }
    const fresh = channelLayer(img, tint);
    box.append(fresh.layer);
    animations.push(
      fresh.layer.animate(
        slices.map((s) => ({ clipPath: bandClip(s), easing: jump })),
        step,
      ),
      fresh.shift.animate(
        slices.map((s) => ({
          transform: `translate(${s.x.toFixed(2)}%, ${s.y.toFixed(2)}%)`,
          easing: jump,
        })),
        step,
      ),
    );
  });
  pic.append(box);
  animations.push(
    to.animate(
      [
        { opacity: 0 },
        { opacity: 1, offset: 0.08 },
        { opacity: 0.7, offset: 0.3 },
        { opacity: 1, offset: 0.36 },
        { opacity: 1 },
      ],
      { duration: ms, easing: 'steps(6, end)', fill: 'backwards' },
    ),
    ...fadeOut(from, ms * 0.35),
  );
  if (from) {
    animations.push(
      cardOf(from).animate(
        [
          { transform: 'none' },
          { transform: 'translateX(-2%) skewX(4deg)' },
          { transform: 'translateX(3%) skewX(-6deg)' },
          { transform: 'none' },
        ],
        { duration: ms * 0.35, easing: 'steps(4, end)', fill: 'forwards' },
      ),
    );
  }
  return play(animations, signal).then(() => {
    for (const copy of box.querySelectorAll('img')) releaseImage(copy);
    box.remove();
  });
};

/** A white instant-photo frame drops in and settles with a tilt (and keeps it). */
export const polaroid: Transition = ({ from, to, ms, signal, rng }) => {
  to.classList.add('is-polaroid');
  const card = cardOf(to);
  const tilt = (rng() < 0.5 ? -1 : 1) * (1.5 + rng() * 2.5);
  return play(
    [
      // eased per segment: a soft start and a gliding fall onto the landing (one
      // ease-out over the whole timeline made the first half a jump), then the bounce
      card.animate(
        [
          {
            transform: `translateY(-115vh) rotate(${-tilt * 5}deg)`,
            easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
          },
          {
            transform: `translateY(2.5vh) rotate(${tilt * 1.8}deg)`,
            offset: 0.55,
            easing: 'cubic-bezier(0.45, 0, 0.55, 1)',
          },
          {
            transform: `translateY(-1vh) rotate(${-tilt * 0.6}deg)`,
            offset: 0.75,
            easing: 'cubic-bezier(0.33, 0, 0.3, 1)',
          },
          { transform: `rotate(${tilt}deg)` },
        ],
        { duration: ms, fill: 'both' },
      ),
      ...captionIn(to, ms * 0.4, ms * 0.6, true),
      ...(from
        ? [
            cardOf(from).animate([{ transform: 'none' }, { transform: 'translateY(4vh) scale(0.94)' }], {
              duration: ms * 0.6,
              delay: ms * 0.3,
              easing: 'ease-in',
              fill: 'forwards',
            }),
          ]
        : []),
      ...fadeOut(from, ms * 0.5, ms * 0.4),
    ],
    signal,
  );
};

/** A vertical slot-machine spin through copies of both photos, stopping on the new one. */
export const slot: Transition = (args) => {
  const { from, to, ms, signal } = args;
  const pic = picOf(to);
  const img = imgOf(to);
  const fromImg = from ? imgOf(from) : null;
  if (!img) return crossfade(args);
  const viewport = document.createElement('div');
  viewport.className = 'wall-slot';
  const strip = document.createElement('div');
  strip.className = 'wall-slot-strip';
  const sources = [img, fromImg ?? img];
  const cells = 7;
  for (let i = 0; i < cells; i++) {
    const cell = document.createElement('div');
    cell.className = 'wall-slot-cell';
    const copy = (i === 0 ? img : sources[i % 2]!).cloneNode(false);
    if (copy instanceof HTMLImageElement) {
      copy.removeAttribute('class');
      copy.alt = '';
      cell.append(copy);
    }
    strip.append(cell);
  }
  viewport.append(strip);
  pic.append(viewport);
  const end = -((cells - 1) / cells) * 100;
  return play(
    [
      to.animate([{ opacity: 0 }, { opacity: 1, offset: 0.12 }, { opacity: 1 }], {
        duration: ms,
        fill: 'backwards',
      }),
      strip.animate(
        [
          { transform: `translateY(${end}%)`, filter: 'blur(0px)' },
          { transform: `translateY(${end * 0.55}%)`, filter: 'blur(5px)', offset: 0.35 },
          { transform: 'translateY(1.6%)', filter: 'blur(1px)', offset: 0.82 },
          { transform: 'translateY(-0.6%)', filter: 'blur(0px)', offset: 0.92 },
          { transform: 'translateY(0)', filter: 'blur(0px)' },
        ],
        { duration: ms, easing: 'cubic-bezier(0.45, 0, 0.2, 1)', fill: 'both' },
      ),
      ...captionIn(to, ms * 0.3, ms * 0.7),
      ...fadeOut(from, ms * 0.25),
    ],
    signal,
  ).then(() => viewport.remove());
};

/** Squash and stretch wobble from the bottom edge. */
export const jelly: Transition = ({ from, to, ms, signal }) => {
  const card = cardOf(to);
  card.style.transformOrigin = '50% 100%';
  const animations = [
    card.animate(
      [
        { transform: 'scale(0.2, 0.2)', opacity: 0 },
        { transform: 'scale(1.22, 0.78)', opacity: 1, offset: 0.32 },
        { transform: 'scale(0.86, 1.14)', offset: 0.5 },
        { transform: 'scale(1.07, 0.94)', offset: 0.66 },
        { transform: 'scale(0.97, 1.03)', offset: 0.82 },
        { transform: 'scale(1, 1)', opacity: 1 },
      ],
      { duration: ms, easing: 'ease-out', fill: 'backwards' },
    ),
    ...captionIn(to, ms * 0.4, ms * 0.55),
    ...fadeOut(from, ms * 0.3),
  ];
  if (from) {
    const old = cardOf(from);
    old.style.transformOrigin = '50% 100%';
    animations.push(
      old.animate([{ transform: 'scale(1, 1)' }, { transform: 'scale(1.3, 0.1)' }], {
        duration: ms * 0.3,
        easing: 'ease-in',
        fill: 'forwards',
      }),
    );
  }
  return play(animations, signal).then(() => {
    card.style.transformOrigin = '';
  });
};

/** Slams down from 3× size, the stage shakes. */
export const stamp: Transition = ({ stage, from, to, ms, signal }) => {
  const card = cardOf(to);
  const hit = 0.38;
  const shake: Keyframe[] = [{ transform: 'none' }];
  const offsets = [
    [-1.2, 0.8],
    [1, -0.9],
    [-0.7, 0.5],
    [0.5, -0.3],
    [-0.2, 0.2],
  ] as const;
  offsets.forEach(([x, y], i) => {
    shake.push({ transform: `translate(${x}vmin, ${y}vmin)`, offset: hit + (i + 1) * 0.08 });
  });
  shake.push({ transform: 'none' });
  return play(
    [
      card.animate(
        [
          { transform: 'scale(3) rotate(-8deg)', opacity: 0 },
          { transform: 'scale(1) rotate(-2deg)', opacity: 1, offset: hit },
          { transform: 'scale(0.98) rotate(0deg)', offset: hit + 0.12 },
          { transform: 'none', opacity: 1 },
        ],
        { duration: ms, easing: 'ease-in', fill: 'backwards' },
      ),
      stage.animate(shake, { duration: ms, easing: 'linear' }),
      ...captionIn(to, ms * 0.35, ms * 0.6),
      ...fadeOut(from, ms * 0.25, ms * hit),
    ],
    signal,
  );
};
