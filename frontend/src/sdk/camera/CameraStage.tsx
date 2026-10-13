/**
 * The camera stage: the hidden <video> (iOS needs it in the DOM), the mount the
 * session's preview canvas goes into, overlays on top, and the "Kamera startet…"
 * state. OWNER: wave 2 "AC". Fills the 3:4 stage box of ActivityShell.
 */
import type { ReactNode, Ref } from 'react';
import { cx } from '@/ui/cx';
import { Spinner } from '@/ui/Spinner';

/** Classes of the preview canvas (created by CameraSession, so Tailwind sees them here). */
export const PREVIEW_CANVAS_CLASS = 'absolute inset-0 block size-full';

export interface CameraStageProps {
  videoRef: Ref<HTMLVideoElement>;
  mountRef: Ref<HTMLDivElement>;
  /** a frame is on screen */
  ready: boolean;
  /** what the stage says while there is no picture ("Kamera startet…") */
  waiting?: ReactNode;
  /** overlays: outline, countdown, the result print */
  children?: ReactNode;
  className?: string;
}

export function CameraStage({ videoRef, mountRef, ready, waiting, children, className }: CameraStageProps) {
  return (
    <div className={cx('absolute inset-0', className)}>
      {/* iOS only plays (and lets WebGL read) a video that is on the page: keep it, invisible */}
      <video
        ref={videoRef}
        playsInline
        muted
        autoPlay
        aria-hidden="true"
        tabIndex={-1}
        className="pointer-events-none absolute inset-0 size-full object-cover opacity-[0.001]"
      />
      <div ref={mountRef} data-testid="preview-mount" className="absolute inset-0" />
      {!ready ? (
        <output className="absolute inset-0 z-(--z-raised) grid place-content-center justify-items-center gap-3 bg-kamera text-sm text-papier-muted">
          {waiting ?? (
            <>
              <Spinner label="Kamera startet…" className="size-7 text-papier" />
              <span aria-hidden="true">Kamera startet…</span>
            </>
          )}
        </output>
      ) : null}
      {children}
    </div>
  );
}
