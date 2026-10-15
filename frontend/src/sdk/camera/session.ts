/**
 * CameraSession owns the <video>, the stream, the renderer and the rAF loop
 * (stack.md "Camera, WebGL, IndexedDB, Share and SSE in React"). OWNER: wave 2 "AC".
 * Port of core/camera.js openCamera() plus the Fotobox render loop.
 *
 * React wires only the lifecycle: one effect creates the session and its cleanup calls
 * stop() (StrictMode runs effects twice in dev: a stopped session drops a stream that
 * arrives late). UI state via useSyncExternalStore(session.subscribe, session.getSnapshot).
 *
 * Kept from before, on purpose:
 * - exact getUserMedia constraints, the bare retry on OverconstrainedError (tests);
 * - iOS: playsinline + muted + autoplay, the video stays in the DOM (opacity 0.001),
 *   a play() nudge every second while it is paused, a restart when the tab comes back
 *   (iOS kills background streams), one reused capture canvas, toBlob only;
 * - facing read back from the track; a single camera is a webcam that faces the guest.
 * The preview canvas is created here (a fallback renderer may need a fresh canvas), so
 * React never owns it: the page passes a mount element.
 */
import {
  cameraConstraints,
  canSwitchCamera,
  fallbackConstraints,
  inferFacing,
  isMirrored,
  otherFacing,
  PHOTO_H,
  PHOTO_W,
  type Facing,
} from './capture';
import { CameraError, toCameraError, unsupportedError, CAMERA_TEXT } from './errors';
import { NORMAL, type FilterImpl } from './filters';
import { canvasToJpeg, createRenderer, type Look, type Renderer, type RendererKind } from './renderer';

export type { Facing } from './capture';

/** A Fotobox shot: the photo as shown, and the same frame without filter and overlay. */
export interface Shot {
  photo: Blob;
  /** null: the photo is its own original (the „Normal“ filter without an overlay) */
  raw: Blob | null;
}

/** Whether a look changes the picture at all (else the photo is its own original). */
export function changesPicture(look: Look): boolean {
  return look.filter.id !== NORMAL.id || look.overlay !== null;
}

/**
 * The last frame as the photo (through `look`, what the preview shows) and, when the
 * look changes the picture, as the unfiltered original: the same frame, crop, size and
 * mirroring, without shader and overlay, so object boxes found on it fit the photo.
 * Both canvases are drawn before the first await: the Canvas2D fallback reads the live
 * video, which must not move on between the two.
 */
export async function renderShot(renderer: Renderer, look: Look, quality = 0.9): Promise<Shot> {
  const shown = renderer.capture();
  const plain = changesPicture(look)
    ? renderer.snapshot(PHOTO_W, PHOTO_H, { filter: NORMAL, overlay: null })
    : null;
  try {
    const [photo, raw] = await Promise.all([
      canvasToJpeg(shown, quality),
      plain ? canvasToJpeg(plain, quality) : Promise.resolve(null),
    ]);
    return { photo, raw };
  } finally {
    // iOS caps the total canvas memory: free the original's canvas at once
    if (plain) {
      plain.width = 0;
      plain.height = 0;
    }
  }
}

export interface CameraSnapshot {
  status: 'idle' | 'starting' | 'live' | 'error' | 'stopped';
  /** a frame has been drawn since the last (re)start: the shutter may fire */
  ready: boolean;
  /** the loop is paused on the last frame (capture, result) */
  frozen: boolean;
  facing: Facing;
  /** the front camera's picture is mirrored, in the preview and the photo; overlays never */
  mirrored: boolean;
  /** false when the device is known to have one camera */
  canSwitch: boolean;
  renderer: RendererKind | null;
  error: CameraError | null;
}

export interface CameraSessionOptions {
  video: HTMLVideoElement;
  /** the preview canvas is appended here (and removed on stop) */
  mount: HTMLElement;
  facing: Facing;
  /** ideal stream size, 4:3 (capture.ts STREAM_SIZE) */
  width: number;
  height: number;
  prefer?: RendererKind | null;
  /** class names and test id of the preview canvas */
  canvasClassName?: string;
  canvasTestId?: string;
}

const READY_TIMEOUT_MS = 10_000;
const PLAY_NUDGE_MS = 1000;

function hasMediaDevices(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

/** Number of cameras, or null when the browser doesn't say (labels need a running stream). */
async function countCameras(): Promise<number | null> {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    return devices.filter((d) => d.kind === 'videoinput').length || null;
  } catch {
    return null;
  }
}

async function getStream(facing: Facing, width: number, height: number): Promise<MediaStream> {
  if (!hasMediaDevices()) throw unsupportedError();
  try {
    return await navigator.mediaDevices.getUserMedia(cameraConstraints(facing, width, height));
  } catch (err) {
    if (err instanceof Error && err.name === 'OverconstrainedError') {
      // some devices reject resolution hints: retry with the bare minimum
      try {
        return await navigator.mediaDevices.getUserMedia(fallbackConstraints(facing));
      } catch (err2) {
        throw toCameraError(err2);
      }
    }
    throw toCameraError(err);
  }
}

function stopTracks(stream: MediaStream | null): void {
  if (!stream) return;
  for (const track of stream.getTracks()) track.stop();
}

export class CameraSession {
  readonly options: CameraSessionOptions;
  private snapshot: CameraSnapshot;
  private readonly listeners = new Set<() => void>();
  private stream: MediaStream | null = null;
  private renderer: Renderer | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private cameras: number | null = null;
  private stopped = false;
  private running = false;
  private rafId = 0;
  private playTried = 0;
  private readonly t0 = performance.now();
  private startSeq = 0;
  private wakeLock: WakeLockSentinel | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private sizeFrame = 0;
  private filter: FilterImpl = NORMAL;
  private overlay: HTMLCanvasElement | null = null;

  constructor(options: CameraSessionOptions) {
    this.options = options;
    this.snapshot = {
      status: 'idle',
      ready: false,
      frozen: false,
      facing: options.facing,
      mirrored: isMirrored(options.facing),
      canSwitch: true,
      renderer: null,
      error: null,
    };
    const { video } = options;
    video.setAttribute('playsinline', '');
    video.setAttribute('autoplay', '');
    video.muted = true;
    document.addEventListener('visibilitychange', this.onVisibility);
  }

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  readonly getSnapshot = (): CameraSnapshot => this.snapshot;

  private set(patch: Partial<CameraSnapshot>): void {
    let changed = false;
    for (const [key, value] of Object.entries(patch)) {
      if (Reflect.get(this.snapshot, key) !== value) changed = true;
    }
    if (!changed) return;
    this.snapshot = { ...this.snapshot, ...patch };
    for (const listener of this.listeners) listener();
  }

  /** Some track of the stream is running. */
  get live(): boolean {
    return !!this.stream && this.stream.getVideoTracks().some((t) => t.readyState === 'live');
  }

  get rendererKind(): RendererKind | null {
    return this.renderer?.kind ?? null;
  }

  // ------------------------------------------------------------- stream

  /** Opens the camera (again) with the current facing and starts the preview loop. */
  async start(): Promise<void> {
    if (this.stopped) return;
    const seq = ++this.startSeq;
    this.pauseLoop();
    // iOS cannot hold two cameras at once: the old stream goes first
    stopTracks(this.stream);
    this.stream = null;
    this.set({ status: 'starting', ready: false, error: null });
    const { video, width, height } = this.options;
    try {
      const stream = await getStream(this.snapshot.facing, width, height);
      if (this.stopped || seq !== this.startSeq) {
        stopTracks(stream); // this session (or this attempt) is gone meanwhile
        return;
      }
      this.stream = stream;
      video.srcObject = stream;
      video.play().catch(() => undefined); // autoplay hiccup: waiting below still works
      await this.waitForVideo(seq);
      if (this.stopped || seq !== this.startSeq) return;
      const settings = stream.getVideoTracks()[0]?.getSettings?.() ?? {};
      this.cameras = await countCameras();
      if (this.stopped || seq !== this.startSeq) return;
      const facing = inferFacing(settings.facingMode, this.cameras, this.snapshot.facing);
      this.ensureRenderer();
      this.set({
        status: 'live',
        facing,
        mirrored: isMirrored(facing),
        canSwitch: canSwitchCamera(this.cameras),
        renderer: this.renderer?.kind ?? null,
      });
      if (!this.snapshot.frozen) this.startLoop();
    } catch (err) {
      if (this.stopped || seq !== this.startSeq) return;
      const error = toCameraError(err);
      this.set({ status: 'error', ready: false, error });
      throw error;
    }
  }

  private waitForVideo(seq: number): Promise<void> {
    const { video } = this.options;
    if (video.readyState >= 2 && video.videoWidth > 0) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const cleanup = () => {
        clearTimeout(timer);
        clearInterval(poll);
        video.removeEventListener('loadeddata', done);
        video.removeEventListener('resize', done);
      };
      const done = () => {
        if (this.stopped || seq !== this.startSeq) {
          cleanup();
          resolve();
        } else if (video.videoWidth > 0) {
          cleanup();
          resolve();
        }
      };
      const timer = setTimeout(() => {
        cleanup();
        reject(new CameraError('timeout', CAMERA_TEXT.timeout));
      }, READY_TIMEOUT_MS);
      // a stopped session must not wait the full timeout
      const poll = setInterval(done, 250);
      video.addEventListener('loadeddata', done);
      video.addEventListener('resize', done);
    });
  }

  private ensureRenderer(): void {
    if (this.renderer) return;
    const { mount, prefer, canvasClassName, canvasTestId } = this.options;
    const canvas = document.createElement('canvas');
    if (canvasClassName) canvas.className = canvasClassName;
    if (canvasTestId) canvas.dataset['testid'] = canvasTestId;
    canvas.setAttribute('aria-hidden', 'true');
    mount.append(canvas);
    const created = createRenderer(canvas, { prefer: prefer ?? null, baseFilter: NORMAL });
    this.renderer = created.renderer;
    this.canvas = created.canvas;
    try {
      this.renderer.setFilter(this.filter, this.overlay);
    } catch {
      this.filter = NORMAL;
      this.overlay = null;
      this.renderer.setFilter(NORMAL, null);
    }
    this.sizeCanvas();
    if (typeof ResizeObserver !== 'undefined') {
      // resize in the next frame, not inside the callback: the canvas' new size can
      // resize the mount again, which Safari reports as an error (ResizeObserver loop)
      this.resizeObserver = new ResizeObserver(() => {
        this.sizeFrame ||= requestAnimationFrame(() => {
          this.sizeFrame = 0;
          this.sizeCanvas();
        });
      });
      this.resizeObserver.observe(mount);
    }
  }

  private sizeCanvas(): void {
    if (!this.renderer) return;
    const width = this.options.mount.getBoundingClientRect().width;
    if (!width) return;
    // the renderer redraws the same frame at the new size (a frozen preview stays the photo)
    this.renderer.resize(width, window.devicePixelRatio || 1);
  }

  // --------------------------------------------------------------- loop

  private readonly frame = (now: number) => {
    this.rafId = 0;
    if (!this.running || !this.renderer) return;
    const { video } = this.options;
    // iOS can leave the camera video paused (power saving, after a call): nudge it
    if (video.paused && this.live && now - this.playTried > PLAY_NUDGE_MS) {
      this.playTried = now;
      video.play().catch(() => undefined);
    }
    const drawn = this.renderer.render(video, {
      mirror: this.snapshot.mirrored,
      time: ((now - this.t0) / 1000) % 1000,
    });
    if (drawn && !this.snapshot.ready) this.set({ ready: true });
    this.rafId = requestAnimationFrame(this.frame);
  };

  private startLoop(): void {
    if (this.running || this.stopped || !this.renderer || document.hidden) return;
    this.running = true;
    this.rafId = requestAnimationFrame(this.frame);
    void this.keepScreenOn();
  }

  private pauseLoop(): void {
    this.running = false;
    if (this.rafId) cancelAnimationFrame(this.rafId);
    this.rafId = 0;
  }

  /** A phone on a stand should not go dark mid-party (Android Chrome, iOS 16.4+). */
  private async keepScreenOn(): Promise<void> {
    if (!('wakeLock' in navigator) || (this.wakeLock && !this.wakeLock.released)) return;
    try {
      this.wakeLock = await navigator.wakeLock.request('screen');
      if (this.stopped) void this.wakeLock.release().catch(() => undefined);
    } catch {
      // not allowed (battery saver, background): fine
    }
  }

  private readonly onVisibility = () => {
    if (this.stopped) return;
    if (document.hidden) {
      this.pauseLoop();
      return;
    }
    // iOS kills the stream in background tabs: bring it back
    if (this.stream && !this.live && this.snapshot.status === 'live') {
      this.start().catch(() => undefined);
    } else if (!this.snapshot.frozen && this.snapshot.status === 'live') {
      this.startLoop();
    }
  };

  // ------------------------------------------------------------ actions

  /** Shows a filter (compiles now; throws when it can't run, the old one stays). */
  setFilter(filter: FilterImpl, overlay: HTMLCanvasElement | null): void {
    if (this.renderer) {
      this.renderer.setFilter(filter, overlay);
      if (this.snapshot.frozen) this.renderer.redraw();
    }
    this.filter = filter;
    this.overlay = overlay;
  }

  /** Flips front/back. On failure the previous camera comes back and the error is thrown. */
  async switchFacing(): Promise<void> {
    if (this.stopped || !this.snapshot.canSwitch) return;
    const before = this.snapshot.facing;
    this.set({ facing: otherFacing(before), mirrored: isMirrored(otherFacing(before)) });
    try {
      await this.start();
    } catch (err) {
      this.set({ facing: before, mirrored: isMirrored(before) });
      await this.start(); // throws (and shows the error state) when this fails too
      throw err;
    }
  }

  /** Pauses on the last frame: the frame on screen now is the photo. */
  freeze(): void {
    this.pauseLoop();
    this.set({ frozen: true });
  }

  /** Back to the live picture (reopens the camera when the stream died meanwhile). */
  async resume(): Promise<void> {
    this.set({ frozen: false });
    if (this.stopped) return;
    if (!this.live && this.snapshot.status !== 'starting') {
      await this.start();
      return;
    }
    this.startLoop();
  }

  /**
   * Freezes the preview and returns the frame on screen as a 1080×1440 JPEG, rendered
   * through the same pipeline (filter, mirror, overlay) at full size.
   */
  async capture(quality = 0.9): Promise<Blob> {
    const renderer = this.renderer;
    if (!renderer || !renderer.hasFrame) throw new CameraError('unknown', CAMERA_TEXT.unknown);
    this.freeze();
    return canvasToJpeg(renderer.capture(), quality);
  }

  /**
   * Like capture(), plus the unfiltered original of the same frame (Fotobox): see
   * renderShot. `raw` is null when the current filter doesn't change the picture.
   */
  async captureShot(quality = 0.9): Promise<Shot> {
    const renderer = this.renderer;
    if (!renderer || !renderer.hasFrame) throw new CameraError('unknown', CAMERA_TEXT.unknown);
    this.freeze();
    return renderShot(renderer, { filter: this.filter, overlay: this.overlay }, quality);
  }

  /** The last frame through `filter` at w×h (filter swatches); the current filter stays. */
  snapshotWith(
    filter: FilterImpl,
    overlay: HTMLCanvasElement | null,
    width: number,
    height: number,
  ): HTMLCanvasElement {
    const renderer = this.renderer;
    if (!renderer || !renderer.hasFrame) throw new Error('no frame yet');
    // the preview keeps its filter and overlay (no re-upload after every swatch)
    return renderer.snapshot(width, height, { filter, overlay });
  }

  /** Cancels rAF, stops the tracks, releases WebGL and the canvas. Safe to call twice. */
  stop(): void {
    if (this.stopped) return;
    this.stopped = true;
    this.startSeq += 1;
    this.pauseLoop();
    document.removeEventListener('visibilitychange', this.onVisibility);
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;
    cancelAnimationFrame(this.sizeFrame);
    this.sizeFrame = 0;
    stopTracks(this.stream);
    this.stream = null;
    const { video } = this.options;
    video.srcObject = null;
    this.renderer?.destroy();
    this.renderer = null;
    this.canvas?.remove();
    this.canvas = null;
    if (this.wakeLock && !this.wakeLock.released) void this.wakeLock.release().catch(() => undefined);
    this.wakeLock = null;
    this.set({ status: 'stopped', ready: false });
    this.listeners.clear();
  }
}
