import type { Rng } from '../rng';

export interface TransitionArgs {
  /** the slide container (position: relative, overflow hidden) */
  stage: HTMLElement;
  /** the outgoing slide (the caller removes it afterwards), null for the first photo */
  from: HTMLElement | null;
  /** the incoming slide, already the stage's last child; it must end in its natural state */
  to: HTMLElement;
  ms: number;
  /** how long `to` stays after the transition (kenburns keeps moving that long) */
  hold: number;
  signal: AbortSignal;
  colors: { primary: string; secondary: string };
  rng: Rng;
}

export type Transition = (args: TransitionArgs) => Promise<void>;

/** The photo card inside a slide (what most transitions move). */
export function cardOf(slide: HTMLElement): HTMLElement {
  return slide.querySelector<HTMLElement>('.wall-card') ?? slide;
}

/** The clipped picture area inside the card (overlays go in here). */
export function picOf(slide: HTMLElement): HTMLElement {
  return slide.querySelector<HTMLElement>('.wall-pic') ?? cardOf(slide);
}

export function imgOf(slide: HTMLElement): HTMLImageElement | null {
  return slide.querySelector<HTMLImageElement>('.wall-pic img');
}

export function captionOf(slide: HTMLElement): HTMLElement | null {
  return slide.querySelector<HTMLElement>('.wall-caption');
}

/** Wait for all animations; an abort jumps them to their end. */
export function play(animations: readonly Animation[], signal: AbortSignal): Promise<void> {
  const finishAll = (): void => {
    for (const a of animations) {
      try {
        a.finish();
      } catch {
        a.cancel();
      }
    }
  };
  if (signal.aborted) finishAll();
  else signal.addEventListener('abort', finishAll, { once: true });
  return Promise.all(animations.map((a) => a.finished)).then(
    () => undefined,
    () => undefined,
  );
}

/** A promise that resolves after `ms` or at once on abort. */
export function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

/** The caption pops in during the last part of a transition (`plain`: a fade only). */
export function captionIn(to: HTMLElement, ms: number, delay: number, plain = false): Animation[] {
  const caption = captionOf(to);
  if (!caption) return [];
  if (plain) {
    return [caption.animate([{ opacity: 0 }, { opacity: 1 }], { duration: ms, delay, fill: 'backwards' })];
  }
  return [
    caption.animate(
      [
        { opacity: 0, transform: 'translateY(2vmin) rotate(-3deg) scale(0.9)' },
        { opacity: 1, transform: 'translateY(-0.5vmin) rotate(-3deg) scale(1.04)', offset: 0.7 },
        { opacity: 1, transform: 'rotate(-3deg)' },
      ],
      { duration: ms, delay, easing: 'ease-out', fill: 'backwards' },
    ),
  ];
}

/** The outgoing caption leaves quickly, before the new one comes in (the engine runs it
 *  next to every transition). */
export function captionOut(from: HTMLElement | null, ms: number): Animation[] {
  return fadeOut(from ? captionOf(from) : null, Math.min(400, ms * 0.3));
}

export function fadeOut(el: HTMLElement | null, ms: number, delay = 0): Animation[] {
  if (!el) return [];
  return [
    el.animate([{ opacity: 1 }, { opacity: 0 }], {
      duration: ms,
      delay,
      easing: 'ease-in',
      fill: 'forwards',
    }),
  ];
}
