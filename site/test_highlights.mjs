// Run from site/: node test_highlights.mjs
// Checks the Highlights data and camera math without a browser.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {HIGHLIGHTS, TIMING, findHighlight, regionalBounds, easeInOut, interpolatePose, datasetCounts} from './dist/viewer/highlights-model.js';

const tours = JSON.parse(await fs.readFile('dist/tours/data/tours.json', 'utf8')).tours;
const tourById = Object.fromEntries(tours.map(t => [t.id, t]));
const close = (a, b, eps = 1e-6) => a.every((v, i) => Math.abs(v - b[i]) <= eps * Math.max(1, Math.abs(b[i])));

// Three highlights, unique ids, every stage has a caption and a known color mode.
assert.equal(HIGHLIGHTS.length, 3);
assert.equal(new Set(HIGHLIGHTS.map(h => h.id)).size, 3);
const modes = new Set(['section', 'operator', 'azimuth', 'inclination']);
for (const h of HIGHLIGHTS) {
  assert.deepEqual(h.stages.map(s => s.kind), ['establish', 'region', 'focus'], h.id);
  for (const s of h.stages) {
    assert.ok(modes.has(s.color), `${h.id} color ${s.color}`);
    const text = s.caption({wells: '22,498', operators: '177'});
    assert.ok(text.length > 20 && text.length < 220, `${h.id} caption length ${text.length}`);
    assert.ok(TIMING[s.kind] > 0);
  }
  assert.ok(h.note && h.title && h.teaser && h.place);
  assert.equal(findHighlight(h.id), h);
}
assert.equal(findHighlight('nope'), null);

// Same wells and frames as the reviewed featured tours.
const pairs = {uturn: 'owan', torpedo: 'torpedo', reach: 'nystuen'};
for (const [id, tourId] of Object.entries(pairs)) {
  const h = findHighlight(id), tour = tourById[tourId];
  assert.deepEqual(h.region, tour.bounds, `${id} region matches the ${tourId} tour`);
  if (h.focusWell != null) assert.equal(h.focusWell, tour.wells[0].mainBranchId, `${id} focus well`);
  assert.ok(h.tourLink.includes(`tour=${tourId}`));
}
// Caption numbers agree with the tour measurements they quote.
const ft = x => Math.round(x / 100) * 100;
assert.equal(ft(tourById.owan.wells[0].lateralLength.mdFt), 12900);
assert.equal(ft(tourById.nystuen.wells[0].lateralLength.mdFt), 20900);
const torpedoLengths = tourById.torpedo.wells.map(w => ft(w.lateralLength.mdFt));
assert.equal(Math.min(...torpedoLengths), 7200); assert.equal(Math.max(...torpedoLengths), 15300);
assert.equal(tourById.torpedo.wells.length, 10);
assert.equal(ft(tourById.owan.wells[0].medianLateralTVDFt), 10600);

// Regional framing: centred on the feature, wider, never smaller than the minimum.
const b = [0, -10000, 0, 2000, -2000, 1000], r = regionalBounds(b, 6, 15000);
assert.deepEqual([(r[0] + r[3]) / 2, (r[2] + r[5]) / 2], [1000, 500]);
assert.equal(r[3] - r[0], 30000); assert.equal(r[5] - r[2], 30000);
assert.equal(r[1], -10000); assert.equal(r[4], -2000);

// Easing: fixed ends, monotonic, clamped.
assert.equal(easeInOut(0), 0); assert.equal(easeInOut(1), 1); assert.equal(easeInOut(-1), 0); assert.equal(easeInOut(2), 1);
let last = -1; for (let i = 0; i <= 100; i++) { const v = easeInOut(i / 100); assert.ok(v >= last); last = v; }

// Camera interpolation: exact ends, geometric distance, smooth direction change.
const from = {target: [0, 0, 0], position: [0, 100000, 0]}, to = {target: [5000, -9000, 2000], position: [5000 + 600, -9000 + 600, 2000 + 600]};
assert.ok(close(interpolatePose(from, to, 0).position, from.position));
assert.ok(close(interpolatePose(from, to, 1).position, to.position));
assert.ok(close(interpolatePose(from, to, 1).target, to.target));
const dist = p => Math.hypot(...p.position.map((v, i) => v - p.target[i]));
const d0 = dist(from), d1 = dist(to), mid = interpolatePose(from, to, .5);
assert.ok(Math.abs(dist(mid) - Math.sqrt(d0 * d1)) < 1e-6 * d0, 'distance is the geometric mean halfway');
let prev = Infinity; for (let i = 0; i <= 20; i++) { const d = dist(interpolatePose(from, to, i / 20)); assert.ok(d <= prev + 1e-6); prev = d; }
// Identical direction and target: only the distance changes.
const same = interpolatePose({target: [0, 0, 0], position: [0, 0, 10]}, {target: [0, 0, 0], position: [0, 0, 1000]}, .5);
assert.ok(close(same.position, [0, 0, 100]));

// Counts: distinct permits, operator groups excluding "Unknown" and empty groups.
const counts = datasetCounts({wells: [{permit: '1'}, {permit: '1'}, {permit: '2'}]},
  {groups: [{key: 'a', wellCount: 3}, {key: 'b', wellCount: 0}, {key: 'unknown', wellCount: 0}, {key: 'c'}]});
assert.deepEqual(counts, {wells: '2', operators: '2'});

console.log('PASS highlights: 3 tours-aligned highlights, caption facts, regional framing, easing, geometric camera flight, counts.');
