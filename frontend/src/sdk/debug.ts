/**
 * The ?debug=1 panel (architecture.md §3.1): sessionStorage vb_debug=1 keeps it on for
 * the tab; a collapsible log at the top with pointer-events: none (vb_debug_folded),
 * logging window errors and unhandled rejections. OWNER: wave 2 "GP".
 * Test ids to keep: data-testid="debug" and "debug-toggle".
 */

/** True when ?debug=1 was opened in this tab. */
export function isDebug(): boolean {
  try {
    return new URLSearchParams(location.search).has('debug') || sessionStorage.getItem('vb_debug') === '1';
  } catch {
    return false;
  }
}

/** Appends a line to the panel (no-op unless debugging). */
export function debugLog(...args: unknown[]): void {
  // TODO(wave 2, GP): the panel
  void args;
}

/** Shows the panel and hooks window errors when debugging is on. Call once per app. */
export function installDebug(): void {
  // TODO(wave 2, GP)
}
