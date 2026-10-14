import { useId, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';
import { cx } from '@/ui/cx';
import { describeRect, keyStep, moveRect, resizeFromCorner, type PageSize, type RelRect } from './geometry';

interface Drag {
  kind: 'move' | 'resize';
  pointer: number;
  x: number;
  y: number;
  start: RelRect;
  /** the latest rectangle, announced when the drag ends */
  last: RelRect;
}

/** The test print's code (the sample, or the code chosen) as an SVG path (modules as 1×1 squares, 2 modules of margin). */
function QrPreview({ matrix }: { matrix: boolean[][] | null }) {
  if (!matrix) return null;
  const size = matrix.length + 4;
  let d = '';
  matrix.forEach((row, y) => {
    row.forEach((dark, x) => {
      if (dark) d += `M${x + 2} ${y + 2}h1v1h-1z`;
    });
  });
  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
      shapeRendering="crispEdges"
      data-testid="qr-preview"
      className="pointer-events-none absolute inset-0 size-full bg-white/60"
    >
      <path d={d} className="fill-black/70" />
    </svg>
  );
}

/**
 * The green square over the page: where the QR code goes. Drag it (mouse, touch, pen),
 * resize it with the corner handle, or use the keyboard (arrows move, + and − resize).
 * Only the square and its handle take touches (`touch-action: none`); the page around
 * them still scrolls.
 */
export function QrFieldEditor({
  rect,
  size,
  matrix,
  onChange,
}: {
  rect: RelRect;
  size: PageSize;
  matrix: boolean[][] | null;
  onChange: (rect: RelRect) => void;
}) {
  const stage = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const [dragging, setDragging] = useState(false);
  // the live region speaks after a change ends (not on every pointer move)
  const [announced, setAnnounced] = useState('');
  const helpId = useId();

  const start = (kind: Drag['kind']) => (e: PointerEvent<HTMLDivElement>) => {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    try {
      // the moves keep coming here when the finger leaves the square
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // a pointer the browser no longer tracks: the moves still arrive while over it
    }
    field.current?.focus({ preventScroll: true });
    drag.current = { kind, pointer: e.pointerId, x: e.clientX, y: e.clientY, start: rect, last: rect };
    setDragging(true);
  };

  const move = (e: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    const box = stage.current?.getBoundingClientRect();
    if (!current || current.pointer !== e.pointerId || !box || box.width === 0) return;
    // the handle's events also bubble to the field: handle them once
    e.stopPropagation();
    e.preventDefault();
    const dx = (e.clientX - current.x) / box.width;
    const dy = (e.clientY - current.y) / box.height;
    current.last =
      current.kind === 'move'
        ? moveRect(current.start, dx, dy, size)
        : resizeFromCorner(current.start, dx, dy, size);
    onChange(current.last);
  };

  const end = (e: PointerEvent<HTMLDivElement>) => {
    const current = drag.current;
    if (current?.pointer !== e.pointerId) return;
    e.stopPropagation();
    drag.current = null;
    setDragging(false);
    setAnnounced(describeRect(current.last));
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    const next = keyStep(e.key, e.shiftKey, rect, size);
    if (!next) return;
    e.preventDefault();
    onChange(next);
    setAnnounced(describeRect(next));
  };

  const handlers = { onPointerMove: move, onPointerUp: end, onPointerCancel: end, onLostPointerCapture: end };

  /* oxlint-disable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex, jsx-a11y/prefer-tag-over-role -- a draggable field: a focusable group with its own keys and aria-roledescription (no native element fits) */
  return (
    <div ref={stage} className="pointer-events-none absolute inset-0">
      <div
        ref={field}
        role="group"
        tabIndex={0}
        aria-label="QR-Feld"
        aria-roledescription="verschiebbares Feld"
        aria-describedby={helpId}
        data-testid="qr-field"
        data-dragging={dragging ? 'true' : undefined}
        onKeyDown={onKeyDown}
        onPointerDown={start('move')}
        {...handlers}
        style={{
          left: `${rect.x * 100}%`,
          top: `${rect.y * 100}%`,
          width: `${rect.w * 100}%`,
          height: `${rect.h * 100}%`,
        }}
        className={cx(
          'pointer-events-auto absolute cursor-move touch-none border-2 border-gruen bg-gruen/25 outline-none select-none',
          'ring-1 ring-white/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus',
          dragging && 'cursor-grabbing',
        )}
      >
        <QrPreview matrix={matrix} />
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-gruen/20" />
        {/* the handle: 16 px to see, 44 px to hit, centred on the corner */}
        <div
          aria-hidden="true"
          data-testid="qr-field-handle"
          onPointerDown={start('resize')}
          {...handlers}
          className="absolute -right-5.5 -bottom-5.5 grid size-11 cursor-nwse-resize touch-none place-items-center"
        >
          <span className="shadow-sm size-4 rounded-[3px] border-2 border-gruen bg-white" />
        </div>
      </div>
      <p id={helpId} className="sr-only">
        Pfeiltasten verschieben, mit Umschalt in großen Schritten. Plus und Minus ändern die Größe.
      </p>
      <p aria-live="polite" className="sr-only" data-testid="qr-field-status">
        {announced}
      </p>
    </div>
  );
  /* oxlint-enable jsx-a11y/no-noninteractive-element-interactions, jsx-a11y/no-noninteractive-tabindex, jsx-a11y/prefer-tag-over-role */
}
