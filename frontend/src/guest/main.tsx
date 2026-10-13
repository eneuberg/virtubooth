/**
 * Guest app entry (index.html): Start and the activities under /x/<id>/.
 * OWNER: wave 2 "GP". The server answers gate/notfound itself (gate.html, HTTP 404).
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/styles/app.css';
import { installPreloadRecovery, markReady } from '@/lib/boot';
import { GuestApp } from './routes';

installPreloadRecovery();

const root = document.getElementById('app');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <GuestApp />
    </StrictMode>,
  );
  markReady();
}
