/**
 * BRIEF invariant: the live screen can only hide photos, never delete (ported from the
 * pre-overhaul test_live_screen_cannot_delete). Deleting lives in the manage area on
 * purpose; nothing in this folder may reach it. The e2e test checks the running page.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const DIR = join(import.meta.dirname, '.');
const SOURCES = readdirSync(DIR)
  .filter((f) => /\.tsx?$/.test(f) && !f.endsWith('.test.ts'))
  .map((f) => ({ file: f, text: readFileSync(join(DIR, f), 'utf8') }));

const FORBIDDEN = [
  /DELETE/,
  /\bdelete\b/i,
  /Löschen/,
  /deletePhotos/,
  /DeletePhotosDialog/,
  /\/bulk/,
  /bulkSetHidden/,
  /store\/actions/,
  /ban(User|Sheet)/,
];

describe('live screen', () => {
  it('has sources', () => {
    expect(SOURCES.map((s) => s.file)).toContain('LivePage.tsx');
  });

  it.each(FORBIDDEN.map((re) => [re.source, re] as const))('never mentions %s', (_, re) => {
    for (const { file, text } of SOURCES) {
      // the module comment explains the rule; code may not
      const code = text.replace(/\/\*\*[\s\S]*?\*\//g, '');
      expect(re.test(code), `${file} matches ${re.source}`).toBe(false);
    }
  });

  it('hides through the shared toggle only', () => {
    const page = SOURCES.find((s) => s.file === 'LivePage.tsx')?.text ?? '';
    expect(page).toContain('useHideToggle');
    expect(page).toContain('HideToggle');
  });
});
