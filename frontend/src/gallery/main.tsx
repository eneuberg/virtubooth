import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/styles/app.css';
import { UiProvider } from '@/ui/UiProvider';
import { Gallery } from './Gallery';

const root = document.getElementById('app');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <UiProvider>
        <Gallery />
      </UiProvider>
    </StrictMode>,
  );
}
window.__vbReady = true;
