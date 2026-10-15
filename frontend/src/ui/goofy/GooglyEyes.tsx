/**
 * Wackelaugen: the running gag of the party and goofy styles. Two plastic googly eyes
 * whose pupils follow the finger or the mouse (and, on phones that tell without asking,
 * fall towards the low side when the phone tilts), overshoot and wobble (eyes.ts), blink
 * now and then, squint nervously during a countdown and squeeze shut when a photo is
 * taken. Without a pointer (the Live Wall) they look around the room.
 *
 * Renders nothing in the calm style; with reduced motion the pupils rest. Size: CSS
 * `--eye` on `.vb-googly` (styles/party.css, styles/goofy.css). Decorative: aria-hidden.
 */
import { useEffect, useRef, useState } from 'react';
import { cx } from '../cx';
import { aim, settled, SPRINGS, step, type Pupil, type Vec } from './eyes';
import { isPlayful, prefersReducedMotion, useThemeStyle } from './style';

export type EyeMood = 'look' | 'nervous' | 'shut';

// ------------------------------------------------- one pointer for every pair of eyes

type Listener = () => void;
const listeners = new Set<Listener>();
let pointer: Vec | null = null;
let pointerAt = 0;
/** gravity from the phone's tilt (−1…1 each), when the device reports it */
let tilt: Vec | null = null;

function notify(): void {
  for (const l of listeners) l();
}
function onPointer(e: PointerEvent): void {
  pointer = { x: e.clientX, y: e.clientY };
  pointerAt = performance.now();
  notify();
}
function onTilt(e: DeviceOrientationEvent): void {
  if (e.gamma === null || e.beta === null) return;
  // upright phone (beta ≈ 60°) looks straight; tipping it rolls the pupils that way
  tilt = { x: Math.max(-1, Math.min(1, e.gamma / 35)), y: Math.max(-1, Math.min(1, (e.beta - 60) / 35)) };
  notify();
}
function watch(listener: Listener): () => void {
  if (listeners.size === 0) {
    window.addEventListener('pointermove', onPointer, { passive: true });
    window.addEventListener('pointerdown', onPointer, { passive: true });
    window.addEventListener('deviceorientation', onTilt, { passive: true });
  }
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) {
      window.removeEventListener('pointermove', onPointer);
      window.removeEventListener('pointerdown', onPointer);
      window.removeEventListener('deviceorientation', onTilt);
    }
  };
}

const POINTER_FRESH_MS = 4000;

export function GooglyEyes({
  mood = 'look',
  gaze = 'pointer',
  className,
}: {
  mood?: EyeMood;
  /** pointer: follow the finger/mouse (looking around when it rests); room: look around */
  gaze?: 'pointer' | 'room';
  className?: string;
}) {
  const style = useThemeStyle();
  if (!isPlayful(style)) return null;
  return <Eyes mood={mood} gaze={gaze} className={className} />;
}

function Eyes({ mood, gaze, className }: { mood: EyeMood; gaze: 'pointer' | 'room'; className?: string }) {
  const rootRef = useRef<HTMLSpanElement>(null);
  const moodRef = useRef(mood);
  const kickRef = useRef<() => void>(() => undefined);
  const [blink, setBlink] = useState(false);

  useEffect(() => {
    moodRef.current = mood;
    kickRef.current();
  }, [mood]);

  // the physics loop: runs only while a pupil moves
  useEffect(() => {
    const root = rootRef.current;
    if (!root || prefersReducedMotion()) return undefined;
    const eyes = Array.from(root.querySelectorAll<HTMLElement>('.vb-googly-eye'));
    const pupils = eyes.map((eye) => eye.querySelector<HTMLElement>('.vb-googly-pupil'));
    const state: Pupil[] = eyes.map(() => ({ pos: { x: 0, y: 0.18 }, vel: { x: 0, y: 0 } }));
    let wander: Vec = { x: 0, y: 0 };
    let frame = 0;
    let last = 0;

    const goals = (): Vec[] => {
      const rects = eyes.map((eye) => eye.getBoundingClientRect());
      const current = moodRef.current;
      if (current === 'nervous') {
        // cross-eyed: each looks at the other one's nose side
        return rects.map((_, i) => ({ x: i === 0 ? 0.85 : -0.85, y: 0.25 }));
      }
      const fresh = gaze === 'pointer' && pointer && performance.now() - pointerAt < POINTER_FRESH_MS;
      return rects.map((r) => {
        const centre = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        if (fresh && pointer) return aim(centre, pointer, r.width);
        if (tilt) return { x: tilt.x * 0.9, y: Math.max(-1, Math.min(1, tilt.y * 0.9 + 0.18)) };
        return wander;
      });
    };

    const tick = (now: number): void => {
      const dt = last ? (now - last) / 1000 : 1 / 60;
      last = now;
      const g = goals();
      let moving = false;
      state.forEach((p, i) => {
        const next = step(p, g[i]!, SPRINGS[i % 2]!, dt);
        state[i] = next;
        const pupil = pupils[i];
        // in % of the pupil's own size: the free radius is half the pupil's diameter
        if (pupil)
          pupil.style.transform = `translate(${(next.pos.x * 50).toFixed(2)}%, ${(next.pos.y * 50).toFixed(2)}%)`;
        if (!settled(next, g[i]!)) moving = true;
      });
      frame = moving ? requestAnimationFrame(tick) : 0;
      if (!moving) last = 0;
    };
    const kick = (): void => {
      if (frame === 0) frame = requestAnimationFrame(tick);
    };
    kickRef.current = kick;
    const unwatch = watch(kick);

    // with nobody pointing: a glance somewhere every couple of seconds
    let glance: ReturnType<typeof setTimeout>;
    const lookAround = (): void => {
      const angle = Math.random() * Math.PI * 2;
      const reach = 0.35 + Math.random() * 0.65;
      wander = { x: Math.cos(angle) * reach, y: Math.min(1, Math.sin(angle) * reach * 0.7 + 0.18) };
      kick();
      glance = setTimeout(lookAround, 1400 + Math.random() * 2600);
    };
    glance = setTimeout(lookAround, 800 + Math.random() * 1200);
    kick();
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(glance);
      unwatch();
      kickRef.current = () => undefined;
    };
  }, [gaze]);

  // a blink now and then (both eyes, 140 ms)
  useEffect(() => {
    if (prefersReducedMotion()) return undefined;
    let timer: ReturnType<typeof setTimeout>;
    const next = (): void => {
      timer = setTimeout(
        () => {
          setBlink(true);
          timer = setTimeout(() => {
            setBlink(false);
            next();
          }, 140);
        },
        2500 + Math.random() * 4500,
      );
    };
    next();
    return () => clearTimeout(timer);
  }, []);

  return (
    <span
      ref={rootRef}
      aria-hidden="true"
      className={cx('vb-googly', className)}
      data-mood={mood}
      data-blink={blink || mood === 'shut' ? '' : undefined}
    >
      <span className="vb-googly-eye">
        <span className="vb-googly-pupil" />
      </span>
      <span className="vb-googly-eye">
        <span className="vb-googly-pupil" />
      </span>
    </span>
  );
}
