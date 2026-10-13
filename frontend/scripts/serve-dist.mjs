// Serves a build with the production security headers, for CSP checks without the backend.
// Same headers as virtubooth's SECURITY_HEADERS; routes the way the server does
// (stack.md "Hosting"), minus access control. Dev tool only, never deployed.
// usage: node scripts/serve-dist.mjs [dir=dist] [port=4310]
import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize, resolve } from 'node:path';

const root = resolve(process.argv[2] ?? 'dist');
const port = Number(process.argv[3] ?? 4310);

export const SECURITY_HEADERS = {
  'Content-Security-Policy':
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; " +
    "media-src 'self' blob:; connect-src 'self'; font-src 'self'; object-src 'none'; " +
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Frame-Options': 'DENY',
  'Permissions-Policy': 'camera=(self), microphone=(), geolocation=(), payment=(), usb=()',
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Resource-Policy': 'same-origin',
};

/** @type {Record<string, string>} */
const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
  '.json': 'application/json',
  '.jpg': 'image/jpeg',
  '.png': 'image/png',
};

/**
 * The HTML entry, status and gate mode the server answers for a page path.
 * @param {string} pathname
 * @returns {[string, number, string | null]}
 */
function page(pathname) {
  if (pathname === '/admin' || pathname.startsWith('/admin/')) return ['admin.html', 200, null];
  if (pathname === '/' || pathname.startsWith('/x/')) return ['index.html', 200, null];
  if (pathname === '/__ui' && existsSync(join(root, 'ui.html'))) return ['ui.html', 200, null];
  if (pathname === '/gate') return ['gate.html', 404, 'gate'];
  return ['gate.html', 404, 'notfound'];
}

createServer((req, res) => {
  const url = new URL(req.url ?? '/', 'http://localhost');
  /** @param {number} status @param {string} type @param {string | Buffer | import('node:stream').Readable} body @param {Record<string, string>} [extra] */
  const send = (status, type, body, extra = {}) => {
    res.writeHead(status, { ...SECURITY_HEADERS, 'Content-Type': type, ...extra });
    if (typeof body === 'string' || Buffer.isBuffer(body)) res.end(body);
    else body.pipe(res);
  };
  const file = normalize(join(root, decodeURIComponent(url.pathname)));
  const isAsset = url.pathname.startsWith('/assets/') || /^\/[\w.-]+\.(?:js|svg|woff2)$/.test(url.pathname);
  if (isAsset && file.startsWith(root) && existsSync(file) && statSync(file).isFile()) {
    const type = TYPES[extname(file)] ?? 'application/octet-stream';
    send(200, type, createReadStream(file), { 'Cache-Control': 'public, max-age=31536000, immutable' });
    return;
  }
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/media/')) {
    send(404, 'application/json', JSON.stringify({ error: 'http_404', message: 'Not Found' }));
    return;
  }
  const [name, status, mode] = page(url.pathname);
  let html = readFileSync(join(root, name), 'utf8');
  if (mode) html = html.replace(/(<html\b[^>]*\bdata-vb-mode=")[a-z]+(")/, `$1${mode}$2`);
  send(status, 'text/html; charset=utf-8', html, { 'Cache-Control': 'no-cache' });
}).listen(port, '127.0.0.1', () => {
  console.log(`serving ${root} on http://127.0.0.1:${port}`);
});
