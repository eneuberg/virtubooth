import { useEffect, useState } from 'react';
import { isFullscreen, toggleFullscreen } from './screen';

/** true after `ms` without mouse, touch or key input */
export function useIdle(ms: number): boolean {
  const [idle, setIdle] = useState(false);
  useEffect(() => {
    let timer = setTimeout(() => setIdle(true), ms);
    const wake = (): void => {
      setIdle(false);
      clearTimeout(timer);
      timer = setTimeout(() => setIdle(true), ms);
    };
    const events = ['mousemove', 'pointerdown', 'keydown', 'wheel'] as const;
    for (const e of events) window.addEventListener(e, wake, { passive: true });
    return () => {
      clearTimeout(timer);
      for (const e of events) window.removeEventListener(e, wake);
    };
  }, [ms]);
  return idle;
}

/** Fullscreen state; the `F` key toggles it (Esc leaves natively). */
export function useFullscreen(): boolean {
  const [full, setFull] = useState(isFullscreen);
  useEffect(() => {
    const onChange = (): void => setFull(isFullscreen());
    const onKey = (e: KeyboardEvent): void => {
      if (e.key !== 'f' && e.key !== 'F') return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const target = e.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return;
      e.preventDefault();
      void toggleFullscreen();
    };
    document.addEventListener('fullscreenchange', onChange);
    window.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('fullscreenchange', onChange);
      window.removeEventListener('keydown', onKey);
    };
  }, []);
  return full;
}
