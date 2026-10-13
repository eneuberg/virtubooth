import { fileURLToPath, URL } from 'node:url';
import optimizeLocales from '@react-aria/optimize-locales-plugin';
import babel from '@rolldown/plugin-babel';
import tailwindcss from '@tailwindcss/vite';
import react, { reactCompilerPreset } from '@vitejs/plugin-react';
import { defineConfig, type Connect, type Plugin, type ProxyOptions } from 'vite';

// iOS 16.0–16.3 still shows up at parties; Vite 8's default floor is safari16.4.
const TARGETS = ['chrome111', 'edge111', 'firefox114', 'safari16', 'ios16'];

// The FastAPI backend in dev. NOT the string shorthand: that sets
// changeOrigin:true, the Host header no longer matches Origin and every
// POST fails the CSRF check with 403 bad_origin.
const API_URL = process.env['VB_API_URL'] ?? 'http://127.0.0.1:8000';
const api: ProxyOptions = { target: API_URL, changeOrigin: false, xfwd: true };

// Paths that never get an HTML entry (the proxy and Vite itself handle them).
const PASS_THROUGH = /^\/(?:api|media|healthz|assets|src|node_modules|@[a-z]+)(?:\/|$)/;

/** Which HTML entry the server would answer for a page path (dev only). */
export function entryFor(pathname: string): string | null {
  if (PASS_THROUGH.test(pathname)) return null;
  if (pathname === '/admin' || pathname.startsWith('/admin/')) return '/admin.html';
  if (/^\/livewall\/(?:api|media)(?:\/|$)/.test(pathname)) return null;
  if (pathname === '/livewall' || pathname.startsWith('/livewall/')) return '/wall.html';
  if (pathname === '/' || pathname === '/x' || pathname.startsWith('/x/')) return '/index.html';
  // dev previews of the static gate page (the server answers it with HTTP 404)
  if (pathname === '/gate' || pathname === '/404') return '/gate.html';
  if (pathname === '/__ui') return '/ui.html';
  return null;
}

/**
 * The server routes pages to the multi-page entries (stack.md, "Hosting");
 * in dev this middleware does the same so client-side routes survive a reload.
 */
const rewriteToEntry: Connect.NextHandleFunction = (req, _res, next) => {
  const accept = req.headers.accept ?? '';
  if ((req.method === 'GET' || req.method === 'HEAD') && accept.includes('text/html') && req.url) {
    const url = new URL(req.url, 'http://dev.local');
    // ?t= is the party token entry: the backend answers it (303 + cookie)
    const entry = url.searchParams.has('t') ? null : entryFor(url.pathname);
    if (entry) req.url = entry + url.search;
  }
  next();
};

function spaFallback(): Plugin {
  return {
    name: 'vb-spa-fallback',
    configureServer: (server) => void server.middlewares.use(rewriteToEntry),
    configurePreviewServer: (server) => void server.middlewares.use(rewriteToEntry),
  };
}

export default defineConfig(({ mode }) => {
  const gallery = mode === 'gallery';
  return {
    appType: 'mpa',
    plugins: [
      // German only: drop the other 33 React Aria locales before anything else sees them
      { ...optimizeLocales.vite({ locales: ['de-DE'] }), enforce: 'pre' as const },
      react(),
      babel({ presets: [reactCompilerPreset()] }),
      tailwindcss(),
      spaFallback(),
    ],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    build: {
      target: TARGETS,
      cssTarget: TARGETS,
      outDir: gallery ? 'dist-gallery' : 'dist',
      emptyOutDir: true,
      // fonts and icons stay files: CSP has no data: fonts, and blockers judge file names
      assetsInlineLimit: 0,
      manifest: true,
      sourcemap: false,
      rolldownOptions: {
        input: {
          guest: 'index.html',
          admin: 'admin.html',
          gate: 'gate.html',
          wall: 'wall.html',
          // the component gallery is a dev tool and never ships in dist/
          ...(gallery ? { ui: 'ui.html' } : {}),
        },
        output: {
          // Neutral, hex-only names. The trailing "0" keeps a hash that happens to
          // end in "ad" from forming "ad." (blocker regex `ads?[-_./]`).
          entryFileNames: 'assets/e-[hash]0.js',
          chunkFileNames: 'assets/c-[hash]0.js',
          assetFileNames: 'assets/a-[hash]0[extname]',
          hashCharacters: 'hex',
        },
      },
    },
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': api,
        '/media': api,
        '/healthz': api,
        '/livewall/api': api,
        '/livewall/media': api,
        // party-token entry on any page path: /x/beer/?t=…
        '^/[^?]*\\?(?:.*&)?t=': api,
      },
    },
    preview: { port: 4173, strictPort: true },
  };
});
