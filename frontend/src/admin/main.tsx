import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/styles/app.css';

createRoot(document.getElementById('app')!).render(
  <StrictMode>
    <p className="p-4 text-lg">Admin</p>
  </StrictMode>,
);
window.__vbReady = true;
