/// <reference types="vite/client" />

interface Window {
  /** set by every app once its module graph ran; public/boot-check.js waits for it */
  __vbReady?: boolean;
}
