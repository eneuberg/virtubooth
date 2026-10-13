/**
 * Guest app entry (index.html): Start and the activities under /x/<id>/.
 * The server answers gate/notfound itself (gate.html, HTTP 404).
 *
 * Order matters: the session starts before the first render (identify runs while
 * React mounts); the debug panel is up before anything can fail; window.__vbReady
 * is set once the app rendered (routes.tsx), so public/boot-check.js stays quiet.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/styles/app.css';
import { isApiError } from '@/api/errors';
import { installPreloadRecovery } from '@/lib/boot';
import { installDebug } from '@/sdk/debug';
import { startPresence } from '@/sdk/presence';
import { startSession } from '@/sdk/session';
import { GuestApp } from './routes';

installDebug();
installPreloadRecovery();
void startSession();
startPresence();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // a 4xx will answer the same again; network trouble gets one more try
      retry: (count, err) => count < 1 && !(isApiError(err) && err.status >= 400 && err.status < 500),
    },
  },
});

const root = document.getElementById('app');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <GuestApp />
      </QueryClientProvider>
    </StrictMode>,
  );
}
