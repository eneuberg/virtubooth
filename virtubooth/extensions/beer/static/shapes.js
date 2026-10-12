// Outline guides for the Beer Cam, drawn in the coordinate system of the saved
// photo (1080 x 1440), so the overlay lines up 1:1 with the captured frame.
//
// bottle: a German 0.5 l "Euroflasche" (body 68 mm wide, 253 mm tall incl. cap)
// cup:    a 0.5 l party/festival beer cup, roughly as tall as the bottle

export const VIEW_W = 1080;
export const VIEW_H = 1440;

const SVG_NS = 'http://www.w3.org/2000/svg';

export const SHAPES = {
  bottle: {
    label: 'Flasche',
    hint: 'Halte deine Flasche genau in den Umriss',
    // bounding box [x, y, w, h], used for the small toggle icon
    box: [364, 100, 352, 1240],
    outline: [
      'M540 1340 H679 Q707 1340 707 1312 V640',
      'C707 506 608 470 608 362', // right shoulder
      'V168 C608 160 616 158 616 150 V112 Q616 100 604 100', // neck, lip, crown cap
      'H476 Q464 100 464 112 V150 C464 158 472 160 472 168',
      'V362 C472 470 373 506 373 640', // left shoulder
      'V1312 Q373 1340 401 1340 Z',
    ].join(' '),
    details: [
      'M464 138 H616', // crown cap rim
      'M373 820 Q540 852 707 820', // body label
      'M373 1150 Q540 1182 707 1150',
    ],
    shine: ['M408 700 V1270'],
  },
  cup: {
    label: 'Becher',
    hint: 'Halte deinen Becher genau in den Umriss',
    box: [214, 220, 652, 1100],
    outline: [
      'M540 1320 H716 Q740 1320 742 1296', // bottom right corner
      'L834 266', // right wall
      'H846 Q866 266 866 246 Q866 226 846 226', // rolled rim, right end
      'H234 Q214 226 214 246 Q214 266 234 266', // rim, left end
      'H246 L338 1296 Q340 1320 364 1320 Z', // left wall
    ].join(' '),
    details: [
      // foam line
      'M256 372 q35.5 -32 71 0 t71 0 t71 0 t71 0 t71 0 t71 0 t71 0 t71 0',
      // the classic party-cup ridges
      'M280 640 Q540 668 800 640',
      'M308 960 Q540 986 772 960',
    ],
    shine: ['M309 470 L376 1220'],
  },
};

export const VESSELS = Object.keys(SHAPES);

function svgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value));
  return el;
}

/** The full-frame overlay: darkened surroundings + outline, one group per vessel. */
export function guideOverlay() {
  const svg = svgEl('svg', {
    class: 'beer-overlay',
    viewBox: `0 0 ${VIEW_W} ${VIEW_H}`,
    preserveAspectRatio: 'none',
    'aria-hidden': 'true',
    'data-testid': 'overlay',
  });
  for (const [vessel, shape] of Object.entries(SHAPES)) {
    const g = svgEl('g', { class: `beer-guide beer-guide--${vessel}`, 'data-testid': `overlay-${vessel}` });
    // even-odd: the frame rectangle minus the silhouette = everything around the drink
    g.append(
      svgEl('path', { class: 'beer-guide-shade', 'fill-rule': 'evenodd', d: `M0 0 H${VIEW_W} V${VIEW_H} H0 Z ${shape.outline}` }),
      svgEl('path', { class: 'beer-guide-halo', d: shape.outline }),
      svgEl('path', { class: 'beer-guide-detail', d: shape.details.join(' ') }),
      svgEl('path', { class: 'beer-guide-shine', d: shape.shine.join(' ') }),
      svgEl('path', { class: 'beer-guide-line', d: shape.outline }),
    );
    svg.append(g);
  }
  return svg;
}

/** A small filled silhouette for the vessel toggle. */
export function vesselIcon(vessel) {
  const [x, y, w, h] = SHAPES[vessel].box;
  const svg = svgEl('svg', {
    class: 'beer-vessel-icon',
    viewBox: `${x} ${y} ${w} ${h}`,
    preserveAspectRatio: 'xMidYMax meet',
    'aria-hidden': 'true',
  });
  svg.append(svgEl('path', { d: SHAPES[vessel].outline, fill: 'currentColor' }));
  return svg;
}
