// Content-blocker guard for the build output (PLAN §1, stack.md "Content blockers").
// Fails when a served file name, the Vite manifest or a CSS class/id in the built CSS
// contains a word that ad/tracking/cookie-notice filter lists match.
// usage: node scripts/check-names.mjs [dist]
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const root = process.argv[2] ?? 'dist';

// served file names (test_core_blockers.py: SERVED_NAME)
export const FILE_NAME =
  /fingerprint|track|analytic|telemetry|beacon|pixel|advert|banner|consent|cookie|gdpr|ads?[-_./]/i;
// class names and ids generic cosmetic filters hide
export const SELECTOR_WORD =
  /consent|cookie|gdpr|banner|notice|modal|backdrop|privacy|popup|advert|fingerprint|track|beacon|(?:^|[-_])ads?(?:$|[-_])/i;

/** @param {string} dir @returns {string[]} */
function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

/** Class and id selectors written in a stylesheet. @param {string} css */
export function selectorsIn(css) {
  const names = new Set();
  const noStrings = css.replace(/url\([^)]*\)/g, '').replace(/"[^"]*"|'[^']*'/g, '');
  for (const m of noStrings.matchAll(/[.#](-?[_a-zA-Z][\w\\:/[\]%.-]*)/g)) {
    const name = m[1].replace(/\\(.)/g, '$1');
    if (/^\d/.test(name)) continue;
    names.add(name);
  }
  return [...names];
}

const problems = [];
const files = walk(root);
for (const file of files) {
  const rel = relative(root, file);
  if (FILE_NAME.test(`/${rel}`)) problems.push(`file name: ${rel}`);
  if (rel.endsWith('manifest.json')) {
    const text = readFileSync(file, 'utf8');
    for (const m of text.matchAll(/"(?:file|src|css|assets)"\s*:\s*"([^"]+)"/g)) {
      if (FILE_NAME.test(`/${m[1]}`)) problems.push(`manifest entry: ${m[1]}`);
    }
  }
  if (file.endsWith('.css')) {
    for (const name of selectorsIn(readFileSync(file, 'utf8'))) {
      if (SELECTOR_WORD.test(name)) problems.push(`css selector in ${rel}: ${name}`);
    }
  }
}

if (problems.length) {
  console.error(`check-names: ${problems.length} blocker-prone name(s) in ${root}:`);
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log(`check-names: ${files.length} files in ${root}, all names neutral`);
