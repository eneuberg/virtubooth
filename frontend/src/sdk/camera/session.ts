/**
 * CameraSession owns the <video>, the stream, the renderer and the rAF loop
 * (stack.md "Camera, WebGL, IndexedDB, Share and SSE in React"). OWNER: wave 2 "AC".
 *
 * React wires only the lifecycle: one effect per facing whose cleanup calls stop()
 * (StrictMode runs effects twice); UI state via
 * useSyncExternalStore(session.subscribe, session.getSnapshot).
 * Keep today's iOS specifics: playsinline, muted, video kept in the DOM at opacity
 * 0.001, restart on visibilitychange, the play() nudge, one reused capture canvas,
 * toBlob only, exact constraints (tests assert them).
 */
import type { CameraError } from './errors';

export type Facing = 'user' | 'environment';

export interface CameraSnapshot {
  status: 'idle' | 'starting' | 'live' | 'error';
  facing: Facing;
  /** front camera preview is mirrored; the overlay never is */
  mirrored: boolean;
  /** true when the device has more than one camera */
  canSwitch: boolean;
  error: CameraError | null;
}

export interface CameraSessionOptions {
  video: HTMLVideoElement;
  canvas: HTMLCanvasElement;
  facing: Facing;
  filterId?: string;
}

export class CameraSession {
  readonly options: CameraSessionOptions;

  constructor(options: CameraSessionOptions) {
    this.options = options;
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    void listener;
    return () => undefined;
  };

  readonly getSnapshot = (): CameraSnapshot => {
    throw new Error('TODO(wave 2, AC): CameraSession.getSnapshot');
  };

  start(): Promise<void> {
    return Promise.reject(new Error('TODO(wave 2, AC): CameraSession.start'));
  }

  setFilter(filterId: string): void {
    void filterId;
    throw new Error('TODO(wave 2, AC): CameraSession.setFilter');
  }

  switchFacing(): Promise<void> {
    return Promise.reject(new Error('TODO(wave 2, AC): CameraSession.switchFacing'));
  }

  /** A 1080×1440 JPEG from the same pipeline as the preview (frozen preview first). */
  capture(): Promise<Blob> {
    return Promise.reject(new Error('TODO(wave 2, AC): CameraSession.capture'));
  }

  /** Cancels rAF, stops the tracks, releases WebGL. Safe to call twice. */
  stop(): void {
    // TODO(wave 2, AC)
  }
}
