/**
 * Admin app entry (admin.html): /admin/login, /admin/live, /admin/manage, /admin/user.
 * OWNER: wave 2 "AD". React Query for server state, useAdminEvents() for SSE.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/styles/app.css';
import './grease-fix.css';
import { installPreloadRecovery, markReady } from '@/lib/boot';
import { AdminApp } from './routes';

installPreloadRecovery();

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: false, retry: 1 } },
});

const root = document.getElementById('app');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <AdminApp />
      </QueryClientProvider>
    </StrictMode>,
  );
  markReady();
}
