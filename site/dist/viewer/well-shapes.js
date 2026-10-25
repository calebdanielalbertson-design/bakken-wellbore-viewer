// Optional display refinements. Saved station sections, metrics and geometry
// are never changed. All supplied indexes are bound to one exact snapshot.
export const UTURN_COLOR = '#35d8ed';
const HASH = /^[a-f\d]{64}$/i;
const IDENTITY_FIELDS = ['id', 'permit', 'api', 'branch', 'tile', 'offset', 'count'];
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const integer = value => Number.isSafeInteger(value) && value >= 0;
const fail = message => { throw new Error(`Invalid well-shape overlay: ${message}`); };
const freezeRanges = ranges => Object.freeze(ranges.map(range => Object.freeze([...range])));

function sameHash(actual, expected, label) {
  if (typeof actual !== 'string' || typeof expected !== 'string' || !HASH.test(actual) || !HASH.test(expected) || actual.toLowerCase() !== expected.toLowerCase()) fail(`${label} fingerprint does not match.`);
}

function rangesFor(value, count, label) {
  if (!Array.isArray(value)) fail(`${label} ranges are required.`);
  let previousEnd = 1;
  return value.map(range => {
    if (!Array.isArray(range) || range.length !== 2) fail(`${label} range must have two endpoints.`);
    const [start, end] = range;
    // An incoming segment needs the station before its ending station. Thus
    // local endpoint zero is deliberately never an eligible segment.
    if (!integer(start) || !integer(end) || start < 1 || start >= end || end > count || start < previousEnd) fail(`${label} range is outside its branch, unsorted or overlapping.`);
    previousEnd = end;
    return [start, end];
  });
}

function inRanges(ranges, endpoint) {
  let low = 0, high = ranges.length;
  while (low < high) {
    const middle = (low + high) >>> 1, [start, end] = ranges[middle];
    if (endpoint < start) high = middle;
    else if (endpoint >= end) low = middle + 1;
    else return true;
  }
  return false;
}

/**
 * Validate an entire sidecar before exposing any overrides. Hash arguments must
 * be SHA-256 of the exact bytes already loaded by the viewer, before rescaling.
 * Overview records contain eight floats: endpoint XYZ pairs, section, branch ID.
 * Detail lookup rows are absolute incoming-station indexes within their tile;
 * overview lookup rows are absolute overview record indexes (tile=null).
 * metricsSHA256 records derivation provenance; it is compared when supplied.
 */
export function validateWellShapes(data, manifest, {manifestSHA256, overviewSHA256, metricsSHA256, overview, enabled = true} = {}) {
  if (data?.version !== 1 || !object(data.source) || !Array.isArray(data.branches)) fail('version, source and branches are required.');
  if (typeof enabled !== 'boolean') fail('enabled must be a boolean.');
  sameHash(data.source.manifestSHA256, manifestSHA256, 'manifest');
  sameHash(data.source.overviewSHA256, overviewSHA256, 'overview');
  if (typeof data.source.metricsSHA256 !== 'string' || !HASH.test(data.source.metricsSHA256)) fail('metrics fingerprint is required.');
  if (metricsSHA256 !== undefined) sameHash(data.source.metricsSHA256, metricsSHA256, 'metrics');
  if (!Array.isArray(manifest?.wells) || !Array.isArray(manifest.tiles) || !integer(manifest.stations) || !integer(manifest.overviewSegments)) fail('survey layout is missing.');
  if (data.source.branchCount !== manifest.wells.length || data.source.stations !== manifest.stations || data.source.overviewSegments !== manifest.overviewSegments) fail('source counts do not match the survey.');
  if (!(overview instanceof Float32Array) || overview.length !== manifest.overviewSegments * 8) fail('overview data has the wrong type or length.');

  const wells = new Map(), tiles = new Map();
  for (const tile of manifest.tiles) {
    if (!object(tile) || typeof tile.id !== 'string' || tiles.has(tile.id) || !integer(tile.stations)) fail('survey tile identity is invalid.');
    tiles.set(tile.id, tile.stations);
  }
  for (const well of manifest.wells) {
    if (!object(well) || !integer(well.id) || wells.has(well.id) || !integer(well.offset) || !integer(well.count) || well.count < 1 || !tiles.has(well.tile) || well.offset + well.count > tiles.get(well.tile)) fail('survey branch layout is invalid.');
    if (['permit', 'api', 'branch', 'tile'].some(key => typeof well[key] !== 'string' || !well[key])) fail('survey branch identity is invalid.');
    wells.set(well.id, well);
  }

  const byBranch = new Map(), usedRows = new Set();
  const totals = {branches: 0, drillbackBranches: 0, uturnBranches: 0, drillbackSegments: 0, uturnSegments: 0, drillbackOverviewSegments: 0, uturnOverviewSegments: 0};
  for (const supplied of data.branches) {
    if (!object(supplied) || !integer(supplied.id) || byBranch.has(supplied.id)) fail('duplicate or invalid overlay branch.');
    const well = wells.get(supplied.id);
    if (!well || IDENTITY_FIELDS.some(key => supplied[key] !== well[key])) fail(`branch ${supplied.id} identity does not match.`);
    const drillbackRanges = rangesFor(supplied.drillbackRanges, well.count, 'drillback');
    const uturnRanges = rangesFor(supplied.uturnRanges, well.count, 'U-turn');
    if (supplied.uturn !== undefined && (typeof supplied.uturn !== 'boolean' || supplied.uturn !== (uturnRanges.length > 0))) fail(`branch ${well.id} U-turn flag disagrees with its ranges.`);
    if (!drillbackRanges.length && !uturnRanges.length) fail(`branch ${well.id} has no refinement ranges.`);

    function rowsFor(rows, ranges, section, label) {
      if (!Array.isArray(rows) || (!ranges.length && rows.length)) fail(`${label} overview rows disagree with the ranges.`);
      let previous = -1;
      const result = new Set();
      for (const row of rows) {
        if (!integer(row) || row <= previous || row >= manifest.overviewSegments || usedRows.has(row)) fail(`${label} overview rows are invalid or duplicated.`);
        if (overview[row * 8 + 7] !== well.id || overview[row * 8 + 6] !== section) fail(`${label} overview row belongs to another branch or saved section.`);
        previous = row;
        usedRows.add(row);
        result.add(row);
      }
      return result;
    }
    const drillbackRows = rowsFor(supplied.drillbackRows, drillbackRanges, 0, 'drillback');
    const uturnRows = rowsFor(supplied.uturnRows, uturnRanges, 4, 'U-turn');
    const identity = Object.fromEntries(IDENTITY_FIELDS.map(key => [key, well[key]]));
    const descriptor = Object.freeze({...identity, drillbackRanges: freezeRanges(drillbackRanges), uturnRanges: freezeRanges(uturnRanges), drillbackRows: Object.freeze([...drillbackRows]), uturnRows: Object.freeze([...uturnRows]), uturn: uturnRanges.length > 0});
    byBranch.set(well.id, {offset: well.offset, count: well.count, tile: well.tile, drillbackRanges, uturnRanges, drillbackRows, uturnRows, descriptor});
    totals.branches++;
    totals.drillbackBranches += Number(drillbackRanges.length > 0);
    totals.uturnBranches += Number(uturnRanges.length > 0);
    totals.drillbackSegments += drillbackRanges.reduce((sum, [start, end]) => sum + end - start, 0);
    totals.uturnSegments += uturnRanges.reduce((sum, [start, end]) => sum + end - start, 0);
    totals.drillbackOverviewSegments += drillbackRows.size;
    totals.uturnOverviewSegments += uturnRows.size;
  }

  let isEnabled = enabled;
  return Object.freeze({
    summary: Object.freeze(totals),
    source: Object.freeze({manifestSHA256: data.source.manifestSHA256.toLowerCase(), overviewSHA256: data.source.overviewSHA256.toLowerCase(), metricsSHA256: data.source.metricsSHA256.toLowerCase(), branchCount: data.source.branchCount, stations: data.source.stations, overviewSegments: data.source.overviewSegments}),
    setEnabled(value) {
      if (typeof value !== 'boolean') throw new TypeError('Well-shape enabled must be a boolean.');
      isEnabled = value;
    },
    enabled: () => isEnabled,
    describe: id => byBranch.get(id)?.descriptor ?? null,
    shapeFor(section, branchID, row, tile = null, active = true) {
      const baseline = {section, uturn: false};
      if (!isEnabled || active !== true || !integer(row) || (section !== 0 && section !== 4)) return baseline;
      const branch = byBranch.get(branchID);
      if (!branch) return baseline;
      let contains;
      if (tile === null) contains = section === 0 ? branch.drillbackRows.has(row) : branch.uturnRows.has(row);
      else {
        if (tile !== branch.tile || row <= branch.offset || row >= branch.offset + branch.count) return baseline;
        contains = inRanges(section === 0 ? branch.drillbackRanges : branch.uturnRanges, row - branch.offset);
      }
      return contains ? {section: section === 0 ? 3 : 4, uturn: section === 4} : baseline;
    }
  });
}

/** Compute a fingerprint from an exact ArrayBuffer or view, not its unused backing bytes. */
export async function sha256Bytes(bytes) {
  if (!(bytes instanceof ArrayBuffer) && !ArrayBuffer.isView(bytes)) throw new TypeError('Expected an ArrayBuffer or byte view.');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, '0')).join('');
}
