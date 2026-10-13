import { useEffect, useState } from 'react';

/** The width the page gets: its container's, at most `max` CSS pixels (re-measured on resize). */
export function useContainerWidth(max: number): [(el: HTMLDivElement | null) => void, number] {
  const [width, setWidth] = useState(0);
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!el) return undefined;
    const measure = () => setWidth(Math.min(max, Math.floor(el.getBoundingClientRect().width)));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [el, max]);
  return [setEl, width];
}
