import { cleanup } from '@testing-library/react';
import { afterAll, afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});

/*
 * Timers still pending when a test file ends would fire after Vitest tore down
 * happy-dom: no `document` any more, an unhandled ReferenceError that fails the whole
 * run. Components schedule such late work when the last test's cleanup unmounts them
 * (Button sweeps React Aria's announcements again after 250 ms, the dashboard hands
 * the focus on after 60 ms); on a slow CI runner the file ended first. Every timer a
 * file started is cleared once its tests are done.
 */
const started: unknown[] = [];
const track: ProxyHandler<typeof setTimeout> = {
  apply(target, self, args) {
    const id: unknown = Reflect.apply(target, self, args);
    started.push(id);
    return id;
  },
};
globalThis.setTimeout = new Proxy(globalThis.setTimeout, track);
globalThis.setInterval = new Proxy(globalThis.setInterval, track);

function isTimer(id: unknown): id is ReturnType<typeof setTimeout> | number {
  return typeof id === 'number' || (typeof id === 'object' && id !== null);
}

afterAll(() => {
  for (const id of started) if (isTimer(id)) clearTimeout(id);
  started.length = 0;
});
