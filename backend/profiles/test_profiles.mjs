// Offline regression checks for the actual frontend. No server or source data.
import assert from 'node:assert/strict';
import { normalizeProduction, productionSummary, chartSeries, safeViewerURL, fracFocusWater, fracFocusMatchesProfile } from './profiles.js';

const sample = normalizeProduction({ months: [
  { month: '2024-03', oil_bbl: 0 }, { month: '2024-01', oil_bbl: 12 },
] });
assert.deepEqual(sample.months, [
  { month: '2024-01', oil_bbl: 12 }, { month: '2024-02', oil_bbl: null }, { month: '2024-03', oil_bbl: 0 },
]);
assert.deepEqual(productionSummary(sample.months), { observed: 2, missing: 1, total: 12, peak: 12, first: '2024-01', last: '2024-03' });
assert.equal(chartSeries(sample.months).runs.length, 2, 'missing months split the actual chart paths');
assert.equal(chartSeries(sample.months).runs[1][0].y, chartSeries(sample.months).baseline, 'reported zero stays on the baseline');
assert.equal(productionSummary([{ month: '2024-01', oil_bbl: null }]).total, null, 'missing is not zero');
assert.equal(productionSummary([{ month: '2024-01', oil_bbl: 0 }]).total, 0, 'reported zero is an observation');
assert.equal(normalizeProduction({ months: [{ month: '2024-01', oil_bbl: -1 }, { month: '2024-02', oil_bbl: '15' }] }).invalid, 2);
assert.equal(normalizeProduction({ months: [{ month: '2024-01', oil_bbl: 1 }, { month: '2024-01', oil_bbl: 2 }] }).months[0].oil_bbl, null, 'conflicting duplicate months are withheld');
assert.deepEqual(normalizeProduction({ months: ['2024-01', '2024-02'], values: [4, null] }).months.map(row => row.oil_bbl), [4, null]);
assert.equal(normalizeProduction({ months: [{ month: '1000-01', oil_bbl: 1 }, { month: '2024-01', oil_bbl: 2 }] }).months.length, 0, 'malformed timespans stay bounded');
assert.equal(safeViewerURL('/viewer/?well=111', 'http://localhost:58519'), '/viewer/?well=111');
for (const url of ['https://evil.invalid/viewer/', 'javascript:alert(1)', '/backend.py', '//evil.invalid/viewer/']) assert.equal(safeViewerURL(url, 'http://localhost:58519'), null);
console.log('PASS production missingness, zero, chronology, path gaps, duplicate review and URL boundaries');
assert.deepEqual(fracFocusWater({water_gallons:0,water_status:'reported'}), {gallons:0,barrels:0,label:'0 gal'});
assert.equal(fracFocusWater({water_gallons:84,water_status:'reported'}).barrels, 2);
assert.equal(fracFocusWater({water_gallons:null,water_status:'missing'}).label, 'Not reported');
assert.equal(fracFocusWater({water_gallons:-1,water_status:'invalid'}).label, 'Needs review');
assert.equal(fracFocusWater({water_gallons:'84',water_status:'reported'}).gallons, null);
const boundProfile = {well:{file_number:'222',api:'33001000020000'},provenance:{release:{id:'frozen-release'}}};
const boundTreatments = {well:boundProfile.well,provenance:{release_id:'frozen-release'}};
assert.equal(fracFocusMatchesProfile(boundTreatments,boundProfile),true);
assert.equal(fracFocusMatchesProfile({...boundTreatments,well:{...boundProfile.well,api:'33001000020100'}},boundProfile),false);
assert.equal(fracFocusMatchesProfile({...boundTreatments,provenance:{release_id:'next-release'}},boundProfile),false);
assert.equal(fracFocusMatchesProfile({...boundTreatments,well:{...boundProfile.well,file_number:'111'}},boundProfile),false);
assert.equal(fracFocusMatchesProfile({},boundProfile),false);
const missingAPIProfile = {...boundProfile,well:{...boundProfile.well,api:null}};
const missingAPIReview = {...boundTreatments,well:missingAPIProfile.well,coverage:{status:'review_required'},events:[]};
assert.equal(fracFocusMatchesProfile(missingAPIReview,missingAPIProfile),true);
assert.equal(fracFocusMatchesProfile({...missingAPIReview,events:[{}]},missingAPIProfile),false,'a missing API cannot accept treatment events');

class Element {
  constructor(tag) { this.tagName = tag; this.children = []; this.attributes = {}; this.dataset = {}; this.className = ''; this.value = ''; this.hidden = false; this.disabled = false; this._text = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  append(...nodes) { for (const child of nodes) { child.parentElement = this; this.children.push(child); } }
  replaceChildren(...nodes) { this.children = []; this._text = ''; this.append(...nodes); }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key]; }
  querySelectorAll(selector) { const result = []; for (const child of this.children) { if (selector.startsWith('.') && child.className.split(' ').includes(selector.slice(1))) result.push(child); result.push(...child.querySelectorAll(selector)); } return result; }
  focus() { document.activeElement = this; }
  scrollIntoView() {}
}
const ids = ['releaseLabel', 'releaseDate', 'apiStatus', 'summaryWells', 'summaryBranches', 'summaryProduction', 'releaseDetailsBody', 'wellQuery', 'wellSearch', 'clearSearch', 'searchStatus', 'previousWells', 'nextWells', 'wellResults', 'wellPage', 'wellProfile'];
const elements = new Map(ids.map(id => [id, new Element('div')]));
globalThis.document = { getElementById: id => elements.get(id), createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag), createTextNode: text => { const element = new Element('#text'); element.textContent = text; return element; } };
globalThis.location = { href: 'http://localhost:58519/profiles/', origin: 'http://localhost:58519', search: '' };
globalThis.history = { replaceState: (_, __, url) => { location.href = String(url); } };
globalThis.matchMedia = () => ({ matches: false });
const calls = [];
let releaseFirst;
let mixedRelease = false;
let fracUnavailable = false;
let fracEmpty = false;
const delayedFirst = new Promise(resolve => { releaseFirst = resolve; });
const wells = [{ file_number: '111', api: '33001000010000', well_name: 'FIRST', operator: null, status: null }, { file_number: '222', api: '33001000020000', well_name: '<img src=x onerror=alert(1)>', operator: 'Saved operator', status: 'A' }];
globalThis.fetch = async path => {
  calls.push(String(path));
  let body;
  if (path === '/api/wells/meta') body = { release: { id: 'test-release', source_date: '2026-10-17' }, counts: { wells: 2, branches: 2, production_wells: 1 } };
  else if (String(path).startsWith('/api/wells?')) body = { rows: wells, total: 2, offset: 0 };
  else if (path === '/api/wells/111') body = await delayedFirst; // Intentionally ignore abort to exercise stale-result protection.
  else if (path === '/api/wells/222') body = { well: wells[1], viewer_url: 'https://evil.invalid/viewer/', branches: [{ branch: 'LAT', station_count: 2, max_md_ft: 0, max_tvd_ft: null }], provenance: { release: { id: 'frozen-release', source_date: '2026-10-17', sha256: 'a'.repeat(64) } } };
  else if (String(path).endsWith('/production')) body = { months: [{ month: '2024-01', oil_bbl: 0 }, { month: '2024-02', oil_bbl: null }], units: 'bbl', coverage: { invalid_months: 1 }, provenance: { release_id: mixedRelease ? 'next-release' : 'frozen-release' } };
  else if (String(path).endsWith('/dsus')) body = { rows: [{ dsu_id: 'dsu-source-1', formation: null, nominal_acres: 1280, relationship: 'Geometric lateral overlap', overlap_ft: null }], coverage: { total: 3, returned: 1, truncated: true }, caveat: 'Geometric membership only.', provenance: { release_id: mixedRelease ? 'next-release' : 'frozen-release' } };
  else if (String(path).endsWith('/fracfocus')) {
    if (fracUnavailable) throw Error('Snapshot unavailable');
    body = {well:wells[1],provenance:{release_id:mixedRelease?'next-release':'frozen-release',latest_job_end:'2026-02-15',source_file:'DisclosureList_1.csv',source_sha256:'b'.repeat(64),prepared_at:'2026-10-20'},coverage:{total:fracEmpty?0:2,status:fracEmpty?'no_disclosure':'matched'},events:fracEmpty?[]:[{disclosure_id:'test-zero',api:wells[1].api,job_start_date:'2020-01-01',job_end_date:'2020-01-02',water_gallons:0,water_status:'reported',operator_name:'<img src=x onerror=alert(1)>',well_name:'SECOND'},{disclosure_id:'test-missing',api:wells[1].api,job_end_date:'2019-01-02',water_gallons:null,water_status:'missing'}]};
  }
  else throw Error('Unexpected endpoint ' + path);
  return { ok: true, json: async () => body };
};
await import('./profiles.js?frontend-regression');
const settle = async predicate => { for (let i = 0; i < 100; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 1)); } throw Error('Frontend did not settle'); };
await settle(() => elements.get('wellResults').children.length === 2);
elements.get('wellResults').children[0].onclick();
elements.get('wellResults').children[1].onclick();
await settle(() => elements.get('wellProfile').textContent.includes('Oil across reported months'));
const profile = elements.get('wellProfile');
assert.ok(profile.textContent.includes('<img src=x onerror=alert(1)>'), 'hostile name is preserved as literal text');
assert.equal(profile.querySelectorAll('.viewer-action').length, 0, 'foreign viewer URL cannot become a profile action');
assert.ok(profile.textContent.includes('Unavailable'), 'unknown depth stays unavailable');
assert.ok(profile.textContent.includes('0 ft'), 'explicit numeric zero stays visible');
assert.ok(profile.textContent.includes('Geometric membership only.'));
assert.ok(profile.textContent.includes('1 of 3 relationships shown'), 'bounded DSU responses disclose omitted records');
assert.ok(profile.textContent.includes('marked invalid and withheld'), 'source-invalid production remains distinct from reported zero');
assert.ok(profile.textContent.includes('frozen-release') && profile.textContent.includes('a'.repeat(64)), 'nested API release provenance remains visible');
assert.equal(profile.getAttribute('aria-busy'), 'false');
assert.equal(profile.querySelectorAll('.fracfocus-event').length,2,'one treatment per disclosure, independent of branches');
assert.ok(profile.textContent.includes('0 gal') && profile.textContent.includes('Not reported'),'treatment water preserves zero versus unknown');
assert.ok(profile.textContent.includes('Treatment record'),'raw disclosure identity is available on demand');
assert.ok(profile.textContent.includes('Feb 15, 2026'),'snapshot coverage is labeled');
releaseFirst({ well: wells[0], branches: [] });
await new Promise(resolve => setTimeout(resolve, 5));
assert.ok(profile.textContent.includes('<img src=x onerror=alert(1)>'), 'a slower previous selection cannot replace the latest profile');
assert.ok(!profile.textContent.includes('WELL PROFILE / FILE 111'));
assert.ok(calls.every(path => path.startsWith('/api/wells')), 'frontend uses only the approved read-only endpoints');
assert.equal(elements.get('summaryProduction').textContent, '1');
console.log('PASS actual frontend loading, literal rendering, unknowns, endpoint boundary and stale-selection protection');
mixedRelease = true;
elements.get('wellResults').children[1].onclick();
await settle(() => profile.textContent.includes('source release changed'));
assert.ok(!profile.textContent.includes('Oil across reported months'), 'production from another release is withheld');
assert.ok(!profile.textContent.includes('dsu-source-1'), 'DSU relationships from another release are withheld');
assert.equal(profile.querySelectorAll('.fracfocus-event').length,0,'treatments from a different release are withheld');
assert.ok(profile.textContent.includes('Select this well again'), 'a concrete recovery action is provided');
mixedRelease = false;
elements.get('wellResults').children[1].onclick();
await settle(() => profile.textContent.includes('Oil across reported months'));
assert.ok(profile.textContent.includes('dsu-source-1'), 'reselecting restores a consistent related snapshot');
console.log('PASS mixed release production/DSU withholding and consistent reselect recovery');
fracUnavailable = true;
elements.get('wellResults').children[1].onclick();
await settle(() => profile.textContent.includes('Treatment coverage is unavailable'));
assert.ok(profile.textContent.includes('Oil across reported months'),'treatment failure does not block the rest of the profile');
fracUnavailable = false; fracEmpty = true;
elements.get('wellResults').children[1].onclick();
await settle(() => profile.textContent.includes('No exact-API disclosure'));
assert.ok(profile.textContent.includes('does not establish that the well was never fractured'));
assert.equal(profile.querySelectorAll('.fracfocus-event').length,0);
console.log('PASS FracFocus identity binding, literal text, separate disclosures, missingness and unavailable coverage');
