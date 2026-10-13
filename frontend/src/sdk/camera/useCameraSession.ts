/**
 * React glue for CameraSession. OWNER: wave 2 "AC".
 * One effect owns the session: it is created when `enabled` turns true (after the guest
 * joined: the camera prompt never comes before the join sheet) and stopped in the
 * cleanup. The camera state comes through useSyncExternalStore.
 */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { isMirrored, type Facing } from './capture';
import type { RendererKind } from './renderer';
import { CameraSession, type CameraSnapshot } from './session';

export interface UseCameraOptions {
  /** open the camera (false while joining, banned, or on errors) */
  enabled: boolean;
  facing: Facing;
  width: number;
  height: number;
  prefer?: RendererKind | null;
  canvasClassName?: string;
  canvasTestId?: string;
}

const noop = () => () => undefined;

function idle(facing: Facing): CameraSnapshot {
  return {
    status: 'idle',
    ready: false,
    frozen: false,
    facing,
    mirrored: isMirrored(facing),
    canSwitch: true,
    renderer: null,
    error: null,
  };
}

export function useCameraSession(options: UseCameraOptions) {
  const { enabled, facing, width, height, prefer, canvasClassName, canvasTestId } = options;
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [session, setSession] = useState<CameraSession | null>(null);
  const [fallback] = useState(() => idle(facing));

  useEffect(() => {
    const video = videoRef.current;
    const mount = mountRef.current;
    if (!enabled || !video || !mount) return undefined;
    const created = new CameraSession({
      video,
      mount,
      facing,
      width,
      height,
      prefer: prefer ?? null,
      ...(canvasClassName ? { canvasClassName } : {}),
      ...(canvasTestId ? { canvasTestId } : {}),
    });
    setSession(created);
    created.start().catch(() => undefined); // the error shows in the snapshot
    return () => {
      created.stop();
      setSession(null);
    };
    // the facing is the start value; switching goes through session.switchFacing()
    // oxlint-disable-next-line react/exhaustive-deps
  }, [enabled, width, height, prefer, canvasClassName, canvasTestId]);

  const camera = useSyncExternalStore(
    session ? session.subscribe : noop,
    session ? session.getSnapshot : () => fallback,
    () => fallback,
  );

  return { videoRef, mountRef, session, camera };
}
