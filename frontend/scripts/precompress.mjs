// Writes .br and .gz next to every compressible file in the build output, so the
// server can answer Accept-Encoding without compressing on the fly.
// usage: node scripts/precompress.mjs [dist]
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { brotliCompressSync, constants, gzipSync } from 'node:zlib';

const root = process.argv[2] ?? 'dist';
const COMPRESSIBLE = /\.(?:js|mjs|css|html|svg|json|txt|map)$/;
const MIN_BYTES = 512;

/** @param {string} dir @returns {string[]} */
function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

let count = 0;
for (const file of walk(root)) {
  if (!COMPRESSIBLE.test(file)) continue;
  const data = readFileSync(file);
  if (data.length < MIN_BYTES) continue;
  const br = brotliCompressSync(data, {
    params: {
      [constants.BROTLI_PARAM_QUALITY]: 11,
      [constants.BROTLI_PARAM_SIZE_HINT]: data.length,
    },
  });
  const gz = gzipSync(data, { level: 9 });
  // keep a variant only when it actually saves bytes
  if (br.length < data.length) writeFileSync(`${file}.br`, br);
  if (gz.length < data.length) writeFileSync(`${file}.gz`, gz);
  count += 1;
}
console.log(`precompress: ${count} files in ${root}`);
