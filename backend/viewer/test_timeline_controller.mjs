// Execute the actual generated controller, replacing only browser/Three imports.
// These checks cover state transitions and displayed meaning, not GPU rendering.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash, webcrypto} from 'node:crypto';

class Node {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.attributes = new Map();
    this.style = {}; this.value = ''; this.checked = false; this.hidden = false; this.disabled = false;
    this._text = ''; this.classList = {add() {}, remove() {}, toggle() {}};
  }
  set textContent(value) {this._text = String(value); this.children = [];}
  get textContent() {return this._text + this.children.map(child => typeof child === 'string' ? child : child.textContent).join('');}
  setAttribute(name, value) {this.attributes.set(name, String(value));}
  getAttribute(name) {return this.attributes.get(name) ?? null;}
  append(...children) {this.children.push(...children);}
  replaceChildren(...children) {this._text = ''; this.children = [...children];}
  addEventListener() {}
}
class DataTexture {
  constructor(data, width, height) {this.image = {data, width, height}; this.disposed = false;}
  dispose() {this.disposed = true;}
}
class Vector2 {constructor(x, y) {this.set(x, y);} set(x, y) {this.x = x; this.y = y; return this;}}
class Color {constructor(value) {this.value = value;} }
globalThis.__timelineThree = {DataTexture, Vector2, Color};
if (!globalThis.crypto?.subtle) globalThis.crypto = webcrypto;
if (!globalThis.CustomEvent) globalThis.CustomEvent = class {constructor(type, options = {}) {this.type = type; this.detail = options.detail;}};

const encode = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const threeURL = encode('const t=globalThis.__timelineThree;export const DataTexture=t.DataTexture,Vector2=t.Vector2,Color=t.Color,RedFormat=1,FloatType=2,NearestFilter=3;');
const historyURL = encode('export function renderScopeHistory(host,history){host.textContent="Rendered oil history for "+history.matchedWells+" wells";}');
const productionModelURL = new URL('../../../sites/bakken-subsurface/dist/viewer/production-model.js', import.meta.url).href;
const activityModelURL = new URL('./activity-model.js', import.meta.url).href;
const controllerSource = (await readFile(new URL('./production.js', import.meta.url), 'utf8'))
  .replace("from 'three'", `from '${threeURL}'`)
  .replace("from './production-model.js'", `from '${productionModelURL}'`)
  .replace("from './activity-model.js'", `from '${activityModelURL}'`)
  .replace("from './production-history.js'", `from '${historyURL}'`);
const {createProductionController} = await import(encode(controllerSource));

const makeWell = (permit, id) => ({permit, api: `330010000${permit}0000`, id});
const survey = {wells: [makeWell('1', 0), makeWell('1', 1), makeWell('2', 2), makeWell('3', 3), makeWell('4', 4)]};
const manifestBytes = Buffer.from(JSON.stringify(survey));
const manifestSHA = createHash('sha256').update(manifestBytes).digest('hex');
const event = (id, month, water_gallons, water_status = 'reported', review_required = false) => ({id, start: `${month}-01`, end: `${month}-20`, month, water_gallons, water_status, review_required, review_reasons: review_required ? ['possible_duplicate_disclosure'] : []});
const well = (permit, spud_date, events) => ({permit, api: `330010000${permit}0000`, branch_count: permit === '1' ? 2 : 1, spud_date, spud_status: spud_date ? 'reported' : 'missing', events,
  monthly: events.map(row => ({month: row.month, event_count: 1, water_gallons: row.water_gallons, water_status: row.review_required ? 'review_required' : row.water_status}))});
const snapshot = {schema_version: 1, provenance: {survey_manifest_sha256: manifestSHA, well_source_date: '2020-04-30', latest_job_end: '2020-03-20', latest_job_end_month: '2020-03'}, wells: [
  well('1', '2020-01-15', [event('a', '2020-01', 1000), event('b', '2020-02', null, 'missing'), event('c', '2020-03', 0)]),
  well('2', null, [event('d', '2020-02', null, 'missing', true)]),
  well('3', '2020-03-01', [event('e', '2020-03', 2000)]),
  well('4', '2020-04-01', [])
]};
const oilMetadata = {version: 1, months: ['2020-01', '2020-02', '2020-03', '2020-04'], wells: ['1', '2', '3', '4'].map(permit => makeWell(permit)), displayNote: 'Fixture reported oil history.'};
const oilValues = new Float32Array([100, 0, NaN, 400, 200, 0, 300, 400, 300, 0, 400, 500, 400, 0, 500, 600]);

async function harness({oil = true, search = '?timeline=activity'} = {}) {
  const ids = ['productionPlay', 'productionEnabled', 'productionDetails', 'productionTimeline', 'productionStatus', 'dsuProduction', 'productionSizeValue', 'productionLegend', 'timelineWidthNote', 'productionMonth', 'productionDate', 'productionDateLabel', 'productionSummary', 'productionCoverage', 'productionPrevious', 'productionNext', 'productionPeriod', 'productionRangeStart', 'productionRangeEnd', 'timelineMode', 'activityOptions', 'productionSourceNote', 'activityUnknown', 'productionSize', 'productionSpeed', 'wellProduction'];
  const nodes = new Map(ids.map(id => [id, new Node()])), emitted = [];
  nodes.get('productionSpeed').value = '3'; nodes.get('productionSize').value = '10';
  globalThis.document = {hidden: false, getElementById: id => nodes.get(id) ?? null, createElement: tag => new Node(tag), createElementNS: (_namespace, tag) => new Node(tag), addEventListener() {}, dispatchEvent(event) {emitted.push(event);}};
  globalThis.location = {search};
  globalThis.fetch = async url => {
    assert.equal(url, './activity.json', 'The controller should fetch only the supplied local activity endpoint.');
    return {ok: true, json: async () => structuredClone(snapshot)};
  };
  const read = async name => {
    if (!oil) throw Error('Oil data intentionally unavailable.');
    if (name === 'production.json') return structuredClone(oilMetadata);
    if (name === 'oil.bin') return oilValues.buffer.slice(0);
    throw Error(`Unexpected read ${name}`);
  };
  const controller = createProductionController();
  await controller.load(read, survey, manifestBytes);
  return {controller, emitted, node: id => nodes.get(id), reload: () => controller.load(read, survey, manifestBytes),
    jump(month) {const input = nodes.get('productionDate'); input.value = month; input.onchange({target: input});},
    mode(mode) {const input = nodes.get('timelineMode'); input.value = mode; input.onchange({target: input});},
    unknown(checked) {const input = nodes.get('activityUnknown'); input.checked = checked; input.onchange({target: input});}};
}

const failures = [];
async function test(name, body) {
  try {await body(); console.log(`PASS ${name}`);} catch (error) {failures.push({name, error}); console.error(`FAIL ${name}: ${error.message}`);}
}

await test('Activity loads independently when oil is unavailable; default date is the disclosure cutoff', async () => {
  const h = await harness({oil: false});
  assert.equal(h.controller.ready(), true); assert.equal(h.controller.enabled(), true); assert.equal(h.controller.activityActive(), true);
  assert.equal(h.node('productionDate').value, '2020-03');
  assert.equal(h.node('productionTimeline').hidden, false);
  assert.match(h.node('productionSummary').textContent, /2,000 known gal/);
  assert.match(h.node('productionSourceNote').textContent, /2020-03-20/);
  h.mode('oil'); assert.equal(h.controller.ready(), false);
  h.mode('activity'); assert.equal(h.controller.ready(), true); assert.equal(h.controller.enabled(), true);
});

await test('Explicit month, spud boundary, pick radius, and disabling the overlay agree', async () => {
  const h = await harness({search: '?timeline=activity&month=2020-02'});
  assert.equal(h.node('productionDate').value, '2020-02');
  assert.equal(h.controller.visible(survey.wells[3]), false);
  assert.equal(h.controller.pickPixels(survey.wells[3]), -1);
  h.jump('2020-03'); assert.equal(h.controller.visible(survey.wells[3]), true);
  assert.ok(h.controller.pickPixels(survey.wells[3]) >= 5);
  h.jump('2020-02'); h.controller.setEnabled(false);
  assert.equal(h.controller.visible(survey.wells[3]), true, 'Turning activity off restores the regular mapped paths.');
  assert.equal(h.node('productionTimeline').hidden, true);
  h.controller.setEnabled(true); assert.equal(h.controller.visible(survey.wells[3]), false);
});

await test('Clearing scope while activity is inactive prevents stale scope on return', async () => {
  const h = await harness();
  h.controller.setBranchScope([0, 1], 'Selected DSU');
  assert.match(h.node('productionCoverage').textContent, /^1 wells shown/);
  h.mode('oil'); h.controller.setBranchScope(null); h.mode('activity');
  assert.match(h.node('productionCoverage').textContent, /^2 wells shown/);
  assert.match(h.node('productionSummary').textContent, /2,000 known gal/);
  assert.match(h.node('productionStatus').textContent, /4 mapped wells/, 'The status count must also reflect the restored full scope.');
});

await test('Unknown-spud checkbox persists through dataset reload and controls both paths and counts', async () => {
  const h = await harness();
  assert.equal(h.controller.visible(survey.wells[2]), false);
  h.unknown(true); assert.equal(h.controller.visible(survey.wells[2]), true);
  assert.match(h.node('productionCoverage').textContent, /^3 wells shown/);
  await h.reload();
  assert.equal(h.node('activityUnknown').checked, true); assert.equal(h.controller.visible(survey.wells[2]), true);
  assert.match(h.node('productionCoverage').textContent, /^3 wells shown/);
  h.unknown(false); assert.equal(h.controller.visible(survey.wells[2]), false);
  assert.match(h.node('productionCoverage').textContent, /^2 wells shown/);
});

await test('Switching oil to activity preserves the chosen month', async () => {
  const h = await harness({search: '?production=1'});
  assert.equal(h.node('timelineMode').value, 'oil'); h.jump('2020-02');
  h.mode('activity'); assert.equal(h.node('productionDate').value, '2020-02');
  assert.match(h.node('productionDateLabel').textContent, /Feb.*2020/);
  assert.equal(h.emitted.filter(event => event.type === 'viewer:timeline-changed').at(-1).detail.date, '2020-02');
});

await test('Selection distinguishes missing/review water, reported zero, and no recorded event', async () => {
  const h = await harness(); h.jump('2020-02'); h.controller.selection(survey.wells[0]);
  assert.match(h.node('wellProduction').textContent, /Frac event · water unavailable \/ review required/);
  assert.match(h.node('productionCoverage').textContent, /sum is partial/);
  h.unknown(true); h.controller.selection(survey.wells[2]);
  assert.match(h.node('wellProduction').textContent, /water unavailable \/ review/);
  h.jump('2020-03'); h.controller.selection(survey.wells[0]);
  assert.match(h.node('wellProduction').textContent, /0 gal reported water/);
  h.controller.selection(survey.wells[2]);
  assert.match(h.node('wellProduction').textContent, /No recorded frac event/);
});

await test('Months after the supplied FracFocus cutoff report unknown coverage, not zero frac activity', async () => {
  const h = await harness(); h.jump('2020-04');
  assert.match(h.node('productionSummary').textContent, /Frac coverage unavailable after 2020-03/);
  assert.match(h.node('productionCoverage').textContent, /later treatment activity is unknown/);
  assert.doesNotMatch(h.node('productionSummary').textContent, /0 known gal/);
  h.controller.selection(survey.wells[4]);
  assert.match(h.node('wellProduction').textContent, /Outside supplied FracFocus history; activity unknown/);
});

if (failures.length) {
  for (const failure of failures) console.error(failure.error.stack?.replace(/data:text\/javascript;base64,[A-Za-z0-9+/=]+/g, 'generated-production.js'));
  process.exitCode = 1;
} else console.log('All seven controller lifecycle checks passed against the generated production.js.');
