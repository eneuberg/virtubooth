// Camera access that behaves on iOS Safari and Android Chrome.
//
//   const cam = await openCamera(videoEl, { facing: 'environment' });
//   cam.facing            -> 'user' | 'environment'
//   cam.mirrored          -> true for the front camera (mirror the *preview*)
//   await cam.switchFacing();
//   cam.stop();
//
// Errors are CameraError with a German `.message` ready to show.

export class CameraError extends Error {
  constructor(code, message, cause) {
    super(message);
    this.name = 'CameraError';
    this.code = code;
    this.cause = cause;
  }
}

export function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

export function isInAppBrowser() {
  return /Instagram|FBAN|FBAV|FB_IAB|Line\/|Snapchat|TikTok|musical_ly|Twitter|LinkedInApp|GSA\//i
    .test(navigator.userAgent);
}

export function cameraErrorMessage(err) {
  const name = err && err.name;
  if (!window.isSecureContext) {
    return 'Die Kamera funktioniert nur über eine sichere Verbindung (https).';
  }
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return isIOS()
      ? 'Kamera-Zugriff wurde verweigert. Tippe in der Adressleiste auf „aA“ › Website-Einstellungen › Kamera › Erlauben und lade die Seite neu.'
      : 'Kamera-Zugriff wurde verweigert. Tippe auf das Schloss in der Adressleiste, erlaube die Kamera und lade die Seite neu.';
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') {
    return 'Keine passende Kamera gefunden.';
  }
  if (name === 'NotReadableError' || name === 'AbortError') {
    return 'Die Kamera wird gerade von einer anderen App benutzt. Schließ sie und versuch es nochmal.';
  }
  if (isInAppBrowser()) {
    return 'In dieser App geht die Kamera nicht. Öffne den Link bitte in Safari oder Chrome.';
  }
  return 'Die Kamera konnte nicht gestartet werden.';
}

function waitForVideo(video) {
  if (video.readyState >= 2 && video.videoWidth > 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new CameraError('timeout', 'Die Kamera startet nicht. Lade die Seite neu.')), 10000);
    const done = () => {
      if (video.videoWidth > 0) {
        clearTimeout(timer);
        video.removeEventListener('loadeddata', done);
        video.removeEventListener('resize', done);
        resolve();
      }
    };
    video.addEventListener('loadeddata', done);
    video.addEventListener('resize', done);
  });
}

async function getStream(facing, width, height) {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    throw new CameraError('unsupported', isInAppBrowser()
      ? 'In dieser App geht die Kamera nicht. Öffne den Link bitte in Safari oder Chrome.'
      : 'Dein Browser unterstützt keine Kamera. Nimm Safari oder Chrome.');
  }
  const video = { facingMode: { ideal: facing }, width: { ideal: width }, height: { ideal: height } };
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: false, video });
  } catch (err) {
    if (err && err.name === 'OverconstrainedError') {
      // some devices reject resolution hints; retry with the bare minimum
      try {
        return await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: facing } });
      } catch (err2) {
        throw new CameraError(err2.name || 'error', cameraErrorMessage(err2), err2);
      }
    }
    throw new CameraError((err && err.name) || 'error', cameraErrorMessage(err), err);
  }
}

export async function openCamera(video, { facing = 'environment', width = 1920, height = 1080 } = {}) {
  video.setAttribute('playsinline', '');
  video.setAttribute('autoplay', '');
  video.muted = true;

  const cam = {
    video,
    stream: null,
    facing,
    get mirrored() { return this.facing === 'user'; },
    get width() { return video.videoWidth; },
    get height() { return video.videoHeight; },

    async start() {
      this.stop();
      this.stream = await getStream(this.facing, width, height);
      video.srcObject = this.stream;
      try { await video.play(); } catch (_) { /* autoplay hiccup: the 'loadeddata' wait still works */ }
      await waitForVideo(video);
      // the browser may not honour facingMode; read back what we got
      const settings = this.stream.getVideoTracks()[0]?.getSettings?.() || {};
      if (settings.facingMode === 'user' || settings.facingMode === 'environment') {
        this.facing = settings.facingMode;
      }
      return this;
    },

    async switchFacing() {
      // iOS cannot hold two cameras at once, so start() stops the old stream first
      this.facing = this.facing === 'user' ? 'environment' : 'user';
      return this.start();
    },

    stop() {
      if (this.stream) {
        for (const track of this.stream.getTracks()) track.stop();
        this.stream = null;
      }
    },

    get live() {
      return !!this.stream && this.stream.getVideoTracks().some((t) => t.readyState === 'live');
    },
  };

  // iOS kills the stream when the tab goes to the background; bring it back
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && cam.stream && !cam.live) {
      cam.start().catch((err) => console.error('camera restart failed', err));
    }
  });

  return cam.start();
}

// Draw the video into a canvas cropped to `targetW` x `targetH` (cover fit,
// centred), optionally mirrored. Returns the canvas.
export function captureFrame(video, targetW, targetH, { mirror = false, canvas } = {}) {
  const c = canvas || document.createElement('canvas');
  c.width = targetW;
  c.height = targetH;
  const ctx = c.getContext('2d');
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  const scale = Math.max(targetW / vw, targetH / vh);
  const sw = targetW / scale;
  const sh = targetH / scale;
  const sx = (vw - sw) / 2;
  const sy = (vh - sh) / 2;
  ctx.save();
  if (mirror) {
    ctx.translate(targetW, 0);
    ctx.scale(-1, 1);
  }
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, targetW, targetH);
  ctx.restore();
  return c;
}
