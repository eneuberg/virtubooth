/**
 * The ?debug=1 panel (architecture.md §3.1). `?debug` turns it on for the tab
 * (sessionStorage vb_debug=1). A log of the last lines sits at the very top with
 * pointer-events: none, so taps go through to the page underneath; a small toggle
 * (the only part that takes taps) folds it away, and the folded state is kept for the
 * tab (vb_debug_folded). It logs window errors and unhandled rejections.
 *
 * Plain DOM, no React: it must keep working when the app itself breaks. No innerHTML
 * (text only), classes from app.css (CSP style-src 'self').
 * Test ids: data-testid="debug" (the panel) and "debug-toggle".
 */

const ON_KEY = 'vb_debug';
const FOLD_KEY = 'vb_debug_folded';
const MAX_LINES = 40;

let panel: { log: HTMLElement; toggle: HTMLButtonElement } | null = null;
const early: string[] = [];

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** True when ?debug was opened in this tab. */
export function isDebug(): boolean {
  try {
    if (new URLSearchParams(location.search).has('debug')) {
      storage()?.setItem(ON_KEY, '1');
      return true;
    }
    return storage()?.getItem(ON_KEY) === '1';
  } catch {
    return false;
  }
}

function format(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value instanceof Error) return `${value.name}: ${value.message}`;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function append(line: string): void {
  if (!panel) {
    early.push(line);
    if (early.length > MAX_LINES) early.shift();
    return;
  }
  const row = document.createElement('div');
  row.textContent = line;
  panel.log.append(row);
  while (panel.log.childElementCount > MAX_LINES) panel.log.firstElementChild?.remove();
}

/** Appends a line to the panel (no-op unless debugging). */
export function debugLog(...args: unknown[]): void {
  if (!isDebug()) return;
  const time = new Date().toLocaleTimeString('de-DE', { hour12: false });
  append(`${time} ${args.map(format).join(' ')}`);
}

function setFolded(folded: boolean): void {
  if (!panel) return;
  panel.log.hidden = folded;
  panel.toggle.setAttribute('aria-expanded', String(!folded));
  panel.toggle.textContent = folded ? 'Log' : 'Log ausblenden';
  try {
    if (folded) storage()?.setItem(FOLD_KEY, '1');
    else storage()?.removeItem(FOLD_KEY);
  } catch {
    // storage full or blocked: folding still works for this page
  }
}

/** Shows the panel and hooks window errors when debugging is on. Call once per app. */
export function installDebug(): void {
  if (panel || !isDebug() || !document.body) return;
  const root = document.createElement('div');
  root.className = 'vb-debug pointer-events-none fixed inset-x-0 top-0 z-(--z-debug)';
  root.setAttribute('data-testid', 'debug');

  const log = document.createElement('div');
  log.className =
    'vb-debug-log max-h-[30dvh] overflow-hidden bg-black/75 px-2 pt-[max(0.25rem,env(safe-area-inset-top))] pb-1 text-xs break-words text-papier tabular';
  log.setAttribute('role', 'log');
  log.setAttribute('aria-label', 'Debug-Log');

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className =
    'vb-debug-toggle pointer-events-auto absolute top-[calc(env(safe-area-inset-top)+4rem)] right-2 h-11 cursor-pointer rounded-small bg-black/75 px-3 text-xs font-semibold text-papier';
  toggle.setAttribute('data-testid', 'debug-toggle');
  toggle.addEventListener('click', () => setFolded(!log.hidden));

  root.append(log, toggle);
  document.body.append(root);
  panel = { log, toggle };

  setFolded(storage()?.getItem(FOLD_KEY) === '1');
  append('debug on');
  for (const line of early.splice(0)) append(line);

  window.addEventListener('error', (event) => {
    debugLog('error', event.message || format(event.error), event.filename ? `@ ${event.filename}` : '');
  });
  window.addEventListener('unhandledrejection', (event) => {
    debugLog('unhandled', format(event.reason));
  });
}
