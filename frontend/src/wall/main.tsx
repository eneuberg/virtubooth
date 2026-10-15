/**
 * Live-Wall entry (wall.html, served at /livewall): the party's photos on a TV.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './wall.css';
// after wall.css: the goofy layer (only under data-vb-style="goofy")
import './goofy.css';
import { installPreloadRecovery, markReady } from '@/lib/boot';
import { WallApp } from './App';

installPreloadRecovery();

const root = document.getElementById('app');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <WallApp />
    </StrictMode>,
  );
  markReady();
}
