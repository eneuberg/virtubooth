import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { checkBuild, FILE_NAME, selectorsIn, SELECTOR_WORD } from './check-names.mjs';

describe('check-names', () => {
  it('flags blocker-prone file names, including a hash that ends in "ad"', () => {
    expect(FILE_NAME.test('/assets/e-1f3aad.js')).toBe(true);
    expect(FILE_NAME.test('/assets/upload.js')).toBe(true);
    expect(FILE_NAME.test('/assets/e-1f3aad0.js')).toBe(false);
    expect(FILE_NAME.test('/assets/a-b2da776d0.woff2')).toBe(false);
  });

  it('reads class and id selectors from CSS', () => {
    const css = '.vb-screen{color:red}.a\\:b:hover{} #app > .x{} .w-\\[1px\\]{} .5{}';
    expect(selectorsIn(css)).toEqual(expect.arrayContaining(['vb-screen', 'a:b', 'app', 'x', 'w-[1px]']));
    expect(SELECTOR_WORD.test('cookie-bar')).toBe(true);
    expect(SELECTOR_WORD.test('vb-screen')).toBe(false);
    expect(SELECTOR_WORD.test('ad-slot')).toBe(true);
    expect(SELECTOR_WORD.test('shadow')).toBe(false);
  });

  it('checks a build directory', () => {
    const dir = mkdtempSync(join(tmpdir(), 'vb-names-'));
    mkdirSync(join(dir, 'assets'));
    writeFileSync(join(dir, 'assets', 'a-123.css'), '.vb-screen{}.modal-push{}');
    writeFileSync(join(dir, 'assets', 'banner.js'), '');
    const { problems } = checkBuild(dir);
    expect(problems.toSorted()).toEqual([
      'css selector in assets/a-123.css: modal-push',
      'file name: assets/banner.js',
    ]);
  });
});
