import assert from 'node:assert/strict';
import {createActivityModel, validateActivitySnapshot, NO_RECORDED_EVENT, UNKNOWN_EVENT_WATER} from './activity-model.js';

const sha = 'a'.repeat(64);
const branch = (id, permit, api = `330010000${permit}0000`) => ({id, permit, api});
const survey = [branch(0, '1'), branch(1, '1'), branch(2, '2'), branch(3, '3'), branch(4, '4')];
const record = (permit, overrides = {}) => ({permit, api: `330010000${permit}0000`, branch_count: permit === '1' ? 2 : 1, spud_date: '2020-01-15', spud_status: 'reported', events: [], monthly: [], ...overrides});
const monthly = (month, water_gallons, water_status = 'reported', event_count = 1) => ({month, event_count, water_gallons, water_status});
const raw = {schema_version: 1, provenance: {survey_manifest_sha256: sha, well_source_date: '2020-04-30', latest_job_end_month: '2020-03'}, wells: [
  record('1', {monthly: [monthly('2020-02', 1000, 'reported', 2), monthly('2020-03', 0)]}),
  record('2', {spud_date: '2020-02-29', monthly: [monthly('2020-02', null, 'missing')]}),
  record('3', {spud_date: '2020-02-30', monthly: [monthly('2020-03', null, 'review_required')]})
]};

await validateActivitySnapshot(raw, sha);
await assert.rejects(validateActivitySnapshot(raw, 'b'.repeat(64)), /do not match/);
assert.throws(() => createActivityModel(raw, survey, {manifestSHA256: 'b'.repeat(64)}), /do not match/);
const model = createActivityModel(raw, survey, {manifestSHA256: sha});
assert.deepEqual(model.metadata.months, ['2020-01', '2020-02', '2020-03']);
assert.equal(model.count, 4);
assert.deepEqual([...model.byBranch], [0, 0, 1, 2, 3]);
assert.equal(model.renderIndexOf(survey[4]), 3, 'A well missing activity still has a universal render index.');
assert.equal(model.visible(survey[2], '2020-01'), false);
assert.equal(model.visible(survey[2], '2020-02'), true, 'Spud month is inclusive, including leap-day spud.');
assert.equal(model.visible(survey[3], '2020-03'), false, 'Invalid calendar dates remain unknown.');
assert.equal(model.visible(survey[3], '2020-03', true), true);
assert.equal(model.visible(survey[4], '2020-03'), false);
assert.equal(model.status(1, 0).event_count, 2);
assert.equal(model.value(0, 0), NO_RECORDED_EVENT);
assert.equal(model.value(1, 1), UNKNOWN_EVENT_WATER);
assert.equal(model.value(2, 0), 0, 'Reported zero must remain distinct from no disclosure and unknown water.');
assert.equal(model.status(0, 3).water_status, 'unmatched_identity');
assert.deepEqual([...model.uploadMonth(1, new Float32Array(5))], [1000, -1, -2, -2, -2]);
assert.equal(model.summaries[1].knownGallons, 1000, 'Two geometry branches must not double count the well.');
assert.equal(model.summaries[1].fracEvents, 3, 'Multiple events are counted separately from wells.');
assert.equal(model.summaries[1].fracWells, 2);
assert.equal(model.summaries[1].missingWaterWells, 1);
assert.equal(model.summaries[1].visibleWells, 2);
assert.equal(model.summaries[2].hiddenFracWells, 1);
model.setIncludeUnknown(true);
assert.equal(model.summaries[2].visibleWells, 4);
assert.equal(model.summaries[2].reviewWaterWells, 1);
assert.equal(model.summaries[2].knownGallons, 0);
assert.equal(model.summaries[2].unmatchedActivityWells, 1);
model.setBranchScope([0, 1, 1]);
assert.deepEqual(model.scopeIndices, [0]);
assert.equal(model.summaries[1].fracEvents, 2);
assert.equal(model.summaries[1].knownGallons, 1000);
assert.equal(model.summaries[1].mappedWells, 1);
model.setBranchScope([]);
assert.equal(model.summaries[1].visibleWells, 0);
model.setBranchScope();
assert.equal(model.summaries[1].mappedWells, 4);

const duplicate = structuredClone(raw);
duplicate.wells[0].monthly.push({...duplicate.wells[0].monthly[0]});
assert.throws(() => createActivityModel(duplicate, survey), /duplicate activity well-month/);
const review = structuredClone(raw);
review.wells[0].spud_status = 'review_required';
assert.equal(createActivityModel(review, survey).visible(survey[0], '2020-03'), false);
const unknownWithNumber = structuredClone(raw);
unknownWithNumber.wells[1].monthly[0].water_gallons = 123;
assert.throws(() => createActivityModel(unknownWithNumber, survey), /must remain null/);
const incomplete = structuredClone(raw);
incomplete.wells[0].branch_count = 1;
assert.throws(() => createActivityModel(incomplete, survey), /branch counts/);
console.log('Activity model checks passed: identity binding, timeline, spud visibility, missing/zero/no-event values, and whole-well scoped counts.');
