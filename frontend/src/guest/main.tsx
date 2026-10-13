import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/styles/app.css';

declare global {
  interface Window {
    __vbReady?: boolean;
  }
}

createRoot(document.getElementById('app')!).render(
  <StrictMode>
    <p className="p-4 text-lg">Gast</p>
  </StrictMode>,
);
window.__vbReady = true;
