// Local, whole-well activity model. Geometry is a current survey snapshot, not
// dated drilling progress. Volumes are reported carrier-fluid water in gallons.
export const NO_RECORDED_EVENT = -2;
export const UNKNOWN_EVENT_WATER = -1;

const identity = well => `${String(well?.permit ?? '').trim()}|${String(well?.api ?? '').trim()}`;
const hashPattern = /^[a-f0-9]{64}$/;
const waterStatuses = new Set(['reported', 'missing', 'invalid', 'review_required']);
const spudStatuses = new Set(['reported', 'missing', 'invalid', 'review_required']);
const serialMonth = value => {
  if (typeof value !== 'string' || !/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return null;
  return Number(value.slice(0, 4)) * 12 + Number(value.slice(5)) - 1;
};
const monthString = value => `${String(Math.floor(value / 12)).padStart(4, '0')}-${String(value % 12 + 1).padStart(2, '0')}`;
function dateMonth(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(date.valueOf()) || date.toISOString().slice(0, 10) !== value) return null;
  return serialMonth(value.slice(0, 7));
}
function checkHeader(snapshot) {
  if (snapshot?.schema_version !== 1 || !Array.isArray(snapshot.wells) ||
      !hashPattern.test(snapshot.provenance?.survey_manifest_sha256 || '')) {
    throw Error('Invalid local activity snapshot.');
  }
}

// Pass the exact bytes read for the displayed manifest, or their verified SHA.
// A caller with a known digest can also supply it to createActivityModel below.
export async function validateActivitySnapshot(snapshot, manifestBytesOrSHA256) {
  checkHeader(snapshot);
  let digest = manifestBytesOrSHA256;
  if (typeof digest !== 'string') {
    if (!(digest instanceof ArrayBuffer) && !ArrayBuffer.isView(digest)) throw Error('Survey manifest bytes are required.');
    if (!globalThis.crypto?.subtle) throw Error('Web Crypto is required to validate activity geometry.');
    digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', digest)), value => value.toString(16).padStart(2, '0')).join('');
  }
  if (!hashPattern.test(digest) || digest !== snapshot.provenance.survey_manifest_sha256) {
    throw Error('Activity dates do not match the displayed survey snapshot.');
  }
  return snapshot;
}

export function createActivityModel(snapshot, surveyWells, {manifestSHA256, includeUnknown = false} = {}) {
  checkHeader(snapshot);
  if (manifestSHA256 !== undefined && manifestSHA256 !== snapshot.provenance.survey_manifest_sha256) {
    throw Error('Activity dates do not match the displayed survey snapshot.');
  }
  if (!Array.isArray(surveyWells) || !surveyWells.length) throw Error('Survey wells are required for activity.');
  const source = new Map();
  for (const well of snapshot.wells) {
    const key = identity(well);
    if (!/^[1-9][0-9]*\|33[0-9]{12}$/.test(key) || source.has(key)) throw Error('Invalid or duplicate activity well identity.');
    if (!spudStatuses.has(well.spud_status) || !Array.isArray(well.monthly) || !Array.isArray(well.events)) throw Error('Invalid activity well record.');
    source.set(key, well);
  }

  const index = new Map(), wells = [], monthRows = [], spudMonths = [], branchCounts = [];
  const maxBranch = surveyWells.reduce((maximum, well) => Math.max(maximum, well.id), -1);
  if (!Number.isSafeInteger(maxBranch) || maxBranch < 0 || maxBranch >= surveyWells.length) throw Error('Invalid survey branch indices.');
  const byBranch = new Int32Array(surveyWells.length).fill(-1), seenBranches = new Set();
  let first = Infinity, last = -Infinity;
  for (const branch of surveyWells) {
    const key = identity(branch);
    if (!Number.isSafeInteger(branch.id) || branch.id < 0 || branch.id >= surveyWells.length || seenBranches.has(branch.id) || !/^[1-9][0-9]*\|33[0-9]{12}$/.test(key)) throw Error('Invalid survey branch identity.');
    seenBranches.add(branch.id);
    let i = index.get(key);
    if (i === undefined) {
      i = wells.length; index.set(key, i);
      const record = source.get(key);
      const well = record ? {...record, matched: true} : {permit: String(branch.permit), api: String(branch.api), matched: false, spud_date: null, spud_status: 'missing', events: [], monthly: []};
      // Invalid, missing, or review-required dates are always unknown, even if
      // a raw source date remains available for inspection.
      const spud = well.spud_status === 'reported' ? dateMonth(well.spud_date) : null;
      if (spud !== null) {first = Math.min(first, spud); last = Math.max(last, spud);}
      const rows = new Map();
      for (const row of well.monthly) {
        const month = serialMonth(row.month);
        if (month === null || rows.has(month) || !Number.isSafeInteger(row.event_count) || row.event_count < 1 || !waterStatuses.has(row.water_status)) throw Error('Invalid or duplicate activity well-month.');
        if (row.water_status === 'reported' && (!Number.isFinite(row.water_gallons) || row.water_gallons < 0)) throw Error('Invalid reported treatment-water volume.');
        if (row.water_status !== 'reported' && row.water_gallons !== null) throw Error('Unknown treatment-water volume must remain null.');
        rows.set(month, row); first = Math.min(first, month); last = Math.max(last, month);
      }
      wells.push(well); monthRows.push(rows); spudMonths.push(spud); branchCounts.push(0);
    }
    byBranch[branch.id] = i; branchCounts[i]++;
  }
  for (let i = 0; i < wells.length; i++) {
    if (wells[i].matched && wells[i].branch_count !== branchCounts[i]) throw Error('Activity branch counts do not match the displayed survey.');
    wells[i].branch_count = branchCounts[i];
  }
  if (!Number.isFinite(first) || !Number.isFinite(last)) throw Error('No usable spud or treatment months are available.');
  if (last - first > 2400) throw Error('Activity date range requires review.');
  const months = Array.from({length: last - first + 1}, (_, i) => monthString(first + i));
  const count = wells.length, allScopeIndices = Array.from({length: count}, (_, i) => i), scopeIndices = [...allScopeIndices], summaries = [];
  let showUnknown = !!includeUnknown;
  const serialAt = month => typeof month === 'string' ? serialMonth(month) : Number.isInteger(month) && month >= 0 && month < months.length ? first + month : null;
  const indexOf = well => typeof well === 'number' ? well >= 0 && well < count ? well : -1 : well ? index.get(identity(well)) ?? -1 : -1;
  function visible(well, month, unknown = showUnknown) {
    const i = indexOf(well), serial = serialAt(month);
    if (i < 0 || serial === null) return false;
    return spudMonths[i] === null ? !!unknown : serial >= spudMonths[i];
  }
  function status(month, i) {
    const serial = serialAt(month);
    if (serial === null || !Number.isInteger(i) || i < 0 || i >= count) return {water_status: 'unavailable', water_gallons: null, event_count: 0};
    const row = monthRows[i].get(serial);
    if (row) return row;
    return {month: monthString(serial), water_status: wells[i].matched ? 'no_event' : 'unmatched_identity', water_gallons: null, event_count: 0};
  }
  function value(month, i) {
    const row = status(month, i);
    if (row.water_status === 'unavailable') return NaN;
    if (row.water_status === 'no_event' || row.water_status === 'unmatched_identity') return NO_RECORDED_EVENT;
    return row.water_status === 'reported' ? row.water_gallons : UNKNOWN_EVENT_WATER;
  }
  function summarize() {
    summaries.length = 0;
    for (const month of months) summaries.push({month, mappedWells: scopeIndices.length, visibleWells: 0, spudded: 0, unknownSpudWells: 0, unmatchedActivityWells: 0, fracEvents: 0, fracWells: 0, knownGallons: 0, reportedWaterWells: 0, missingWaterWells: 0, invalidWaterWells: 0, reviewWaterWells: 0, unavailableWaterWells: 0, noRecordedEventWells: 0, maximumWater: 0, hiddenFracWells: 0});
    let unknown = 0, unmatched = 0;
    for (const i of scopeIndices) {
      const spud = spudMonths[i];
      if (spud === null) unknown++; else summaries[spud - first].spudded++;
      if (!wells[i].matched) unmatched++;
      for (const [serial, row] of monthRows[i]) {
        const summary = summaries[serial - first];
        if (!visible(i, row.month)) {summary.hiddenFracWells++; continue;}
        summary.fracEvents += row.event_count; summary.fracWells++;
        if (row.water_status === 'reported') {
          summary.knownGallons += row.water_gallons; summary.reportedWaterWells++;
          summary.maximumWater = Math.max(summary.maximumWater, row.water_gallons);
        } else {
          summary.unavailableWaterWells++;
          summary[row.water_status === 'missing' ? 'missingWaterWells' : row.water_status === 'invalid' ? 'invalidWaterWells' : 'reviewWaterWells']++;
        }
      }
    }
    let knownVisible = 0;
    for (const summary of summaries) {
      knownVisible += summary.spudded;
      summary.unknownSpudWells = unknown; summary.unmatchedActivityWells = unmatched;
      summary.visibleWells = knownVisible + (showUnknown ? unknown : 0);
      // These are absence-of-record counts, never inferred zero activity.
      summary.noRecordedEventWells = summary.visibleWells - summary.fracWells - (showUnknown ? unmatched : 0);
    }
  }
  summarize();
  return {
    metadata: {version: 1, months, wells, provenance: snapshot.provenance, coverage: snapshot.coverage, sourceCutoffMonth: snapshot.provenance.latest_job_end_month ?? null, geometrySourceDate: snapshot.provenance.well_source_date ?? null},
    count, byBranch, renderByBranch: byBranch, scopeIndices, summaries,
    indexOf, renderIndexOf: indexOf, visible, status, value,
    includeUnknown: () => showUnknown,
    setIncludeUnknown(value) {showUnknown = !!value; summarize();},
    setBranchScope(ids = null) {
      const next = ids === null ? allScopeIndices : [...new Set(ids.map(id => byBranch[id]).filter(i => Number.isInteger(i) && i >= 0))];
      scopeIndices.length = 0; scopeIndices.push(...next); summarize();
    },
    uploadMonth(month, target) {
      if (!Number.isInteger(month) || month < 0 || month >= months.length || target.length < count) throw Error('Invalid activity texture upload.');
      target.fill(NO_RECORDED_EVENT);
      for (let i = 0; i < count; i++) target[i] = value(month, i);
      return target;
    }
  };
}
