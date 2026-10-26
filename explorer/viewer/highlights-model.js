// Highlights: short guided camera flights through the main viewer.
// Pure data and math (no DOM, no Three.js) so it can be tested in Node.
//
// Facts in captions come from the reviewed featured-tour data
// (tours/data/tours.json): same wells, same branch ids, same measurements.
// Captions describe mapped geometry only; they make no drilling-event,
// completion, performance or ownership claims.

export const HIGHLIGHTS = [
  {
    id: 'uturn',
    title: 'The U-turn lateral',
    teaser: 'A mapped lateral that heads out, then turns back.',
    place: 'Williams County',
    tourLink: '../tours/?tour=owan&step=2',
    region: [-186938.312, -10648.2, -88999.844, -185110.109, -2114.894, -78718.18],
    focusWell: 47165,
    stages: [
      { kind: 'establish', color: 'operator',
        caption: ({wells}) => `Every line is a mapped wellbore: ${wells} wells across North Dakota. Colors show each well's operator of record.` },
      { kind: 'region', color: 'operator',
        caption: () => 'Heading to Williams County. These laterals run about 10,600 ft (two miles) below the surface.' },
      { kind: 'focus', color: 'azimuth',
        caption: () => 'Owan 5402 43-26 3BU. Colors now show compass direction: watch them flip where the 12,900 ft mapped lateral turns back on itself.' },
    ],
    note: 'Mapped geometry only. No claim about why the path turns or how the well performs.',
  },
  {
    id: 'torpedo',
    title: "Who's who by the lake",
    teaser: 'Ten wells beside Lake Sakakawea, colored by operator.',
    place: 'Mountrail County',
    tourLink: '../tours/?tour=torpedo&step=2',
    region: [145263.219, -9915.873, -14949.79, 154830.953, -1781.9, 1309.818],
    focusWell: null,
    // Look straight down at a wider neighborhood: the operator patchwork reads best from above.
    focusView: 'top',
    focusWiden: 3,
    stages: [
      { kind: 'establish', color: 'operator',
        caption: ({operators}) => `Each color is an operator of record: ${operators} operator groups statewide. Neighboring areas are often operated by different companies.` },
      { kind: 'region', color: 'operator',
        caption: () => 'Heading to Mountrail County, beside Lake Sakakawea.' },
      { kind: 'focus', color: 'operator',
        caption: () => 'Looking down on the Torpedo Federal wells and their neighbors. Ten wells fan out from a compact surface area, with mapped laterals of about 7,200 to 15,300 ft. Tap any well to see its operator.' },
    ],
    note: 'Colors show the operator of record in public well data, not mineral ownership or working interest.',
  },
  {
    id: 'reach',
    title: 'How far a well reaches',
    teaser: 'About four miles sideways, nearly two miles down.',
    place: 'Williams County',
    tourLink: '../tours/?tour=nystuen',
    region: [-93006.047, -9640.248, -263484.781, -90121.031, -2088.679, -242119.734],
    focusWell: 47891,
    stages: [
      { kind: 'establish', color: 'section',
        caption: () => 'Most Bakken wells go straight down about two miles, curve, then run horizontally through the rock.' },
      { kind: 'region', color: 'section',
        caption: () => 'Heading to northern Williams County.' },
      { kind: 'focus', color: 'inclination',
        caption: () => 'Nystuen 20-17-8-5 1H. Colors show inclination from vertical to horizontal. Its mapped lateral runs about 20,900 ft, roughly four miles.' },
    ],
    note: 'Lateral footage is measured along the mapped path, separately from total measured depth.',
  },
];

// Seconds for each stage: hold on the state, fly to the region, settle on the wells.
export const TIMING = { establish: 4.5, region: 6.5, focus: 6.5, reducedMotionHold: 5 };

export function findHighlight(id) {
  return HIGHLIGHTS.find(h => h.id === id) || null;
}

// Expand bounds [minX,minY,minZ,maxX,maxY,maxZ] horizontally around their center,
// keeping at least `minHalf` on each side, so the flight passes through a regional view.
export function regionalBounds(b, factor = 6, minHalf = 15000) {
  const cx = (b[0] + b[3]) / 2, cz = (b[2] + b[5]) / 2;
  const hx = Math.max((b[3] - b[0]) / 2 * factor, minHalf), hz = Math.max((b[5] - b[2]) / 2 * factor, minHalf);
  return [cx - hx, b[1], cz - hz, cx + hx, b[4], cz + hz];
}

export const clamp01 = t => Math.min(1, Math.max(0, t));
export const easeInOut = t => { t = clamp01(t); return t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };

const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const length = a => Math.hypot(a[0], a[1], a[2]);
const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

function slerpUnit(a, b, t) {
  const dot = Math.min(1, Math.max(-1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  const angle = Math.acos(dot);
  if (angle < 1e-4) return lerp(a, b, t);
  const s = Math.sin(angle);
  return add(scale(a, Math.sin((1 - t) * angle) / s), scale(b, Math.sin(t * angle) / s));
}

// Camera pose between `from` and `to` ({position:[x,y,z], target:[x,y,z]}) at eased progress t.
// Viewing distance changes geometrically so a 100x zoom feels steady instead of
// rushing through the last few percent, and the view direction turns smoothly.
export function interpolatePose(from, to, t) {
  t = clamp01(t);
  const target = lerp(from.target, to.target, t);
  const fromOffset = sub(from.position, from.target), toOffset = sub(to.position, to.target);
  const d0 = Math.max(length(fromOffset), 1e-6), d1 = Math.max(length(toOffset), 1e-6);
  const direction = slerpUnit(scale(fromOffset, 1 / d0), scale(toOffset, 1 / d1), t);
  const distance = d0 * Math.pow(d1 / d0, t);
  return { target, position: add(target, scale(direction, distance)) };
}

export function datasetCounts(manifest, operatorModel) {
  const wells = new Set((manifest?.wells || []).map(w => w.permit)).size;
  const operators = (operatorModel?.groups || []).filter(g => g.key !== 'unknown' && (g.wellCount ?? 1) > 0).length;
  return { wells: wells.toLocaleString('en-US'), operators: operators.toLocaleString('en-US') };
}
