/**
 * Live-Wall entry (wall.html, served at /livewall): the party's photos on a TV.
 */
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './wall.css';
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
