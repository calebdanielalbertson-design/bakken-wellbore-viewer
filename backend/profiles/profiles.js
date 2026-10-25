/* Local well profiles. All observations arrive through the read-only API.
   No data source, current status, or legal relationship is inferred here. */
const documentRef = globalThis.document;
const SVG_NS = 'http://www.w3.org/2000/svg';
const PAGE_SIZE = 20;
const state = { query: '', offset: 0, total: 0, selected: '', listToken: 0, profileToken: 0, listController: null, profileController: null };
const $ = id => documentRef.getElementById(id);
const node = (tag, text, className) => {
  const element = documentRef.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const finite = value => typeof value === 'number' && Number.isFinite(value);
const formatNumber = value => finite(value) ? value.toLocaleString('en-US', { maximumFractionDigits: 0 }) : 'Unavailable';
const valueText = value => value === null || value === undefined || value === '' ? 'Unavailable' : String(value);
const readable = value => valueText(value).replace(/_/g, ' ');
const array = value => Array.isArray(value) ? value : [];
const rows = data => Array.isArray(data) ? data : array(data?.rows ?? data?.dsus ?? data?.branches);
const wellObject = row => row?.well && typeof row.well === 'object' ? row.well : row ?? {};
const wellFile = row => String(wellObject(row).file_number ?? wellObject(row).permit ?? '');
const nameOf = well => well.well_name || well.wellName || (wellFile(well) ? 'Well ' + wellFile(well) : 'Unnamed well');
const monthlyIndex = value => {
  if (typeof value !== 'string' || !/^\d{4}-(0[1-9]|1[0-2])$/.test(value)) return null;
  const [year, month] = value.split('-').map(Number);
  return year * 12 + month - 1;
};
const monthString = index => `${Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, '0')}`;
const monthLabel = value => {
  if (monthlyIndex(value) === null) return valueText(value);
  return new Date(value + '-15T12:00:00Z').toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' });
};
function sourceDate(value) {
  if (!value) return 'Unavailable';
  const text = String(value).slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return String(value);
  const parsed = new Date(text + 'T12:00:00Z');
  return Number.isNaN(parsed.valueOf()) ? String(value) : parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}

export function safeViewerURL(value, origin = globalThis.location?.origin) {
  if (typeof value !== 'string' || !origin) return null;
  try {
    const url = new URL(value, origin);
    return url.origin === origin && !url.username && !url.password && /^\/viewer\/?$/.test(url.pathname)
      ? url.pathname + url.search + url.hash : null;
  } catch { return null; }
}

/** Keep null observations and insert omitted calendar months as explicit gaps.
 * A duplicated month with conflicting values is withheld, never summed. */
export function normalizeProduction(data) {
  const source = Array.isArray(data) ? data : data?.months ?? data?.monthly ?? data?.series ?? data?.rows ?? [];
  const values = array(data?.values ?? data?.oil_bbl);
  const observations = new Map();
  let invalid = 0, conflicts = 0;
  for (const [position, row] of array(source).entries()) {
    const month = typeof row === 'string' ? row : row?.month ?? row?.date;
    const index = monthlyIndex(month);
    if (index === null) { invalid++; continue; }
    const raw = typeof row === 'string' ? values[position] : row?.oil_bbl;
    const oil = finite(raw) && raw >= 0 ? raw : null;
    if (raw !== null && raw !== undefined && oil === null) invalid++;
    if (observations.has(index) && observations.get(index) !== oil) {
      observations.set(index, null); conflicts++;
    } else if (!observations.has(index)) observations.set(index, oil);
  }
  const keys = [...observations.keys()].sort((a, b) => a - b);
  if (!keys.length) return { months: [], invalid, conflicts };
  // Avoid allocating a fabricated millennium for malformed input.
  if (keys.at(-1) - keys[0] > 2400) return { months: [], invalid: invalid + 1, conflicts };
  const months = [];
  for (let index = keys[0]; index <= keys.at(-1); index++) {
    months.push({ month: monthString(index), oil_bbl: observations.get(index) ?? null });
  }
  return { months, invalid, conflicts };
}

export function productionSummary(months) {
  const observed = array(months).filter(row => finite(row?.oil_bbl) && row.oil_bbl >= 0);
  return {
    observed: observed.length, missing: array(months).length - observed.length,
    total: observed.length ? observed.reduce((sum, row) => sum + row.oil_bbl, 0) : null,
    peak: observed.length ? Math.max(...observed.map(row => row.oil_bbl)) : null,
    first: observed[0]?.month ?? null, last: observed.at(-1)?.month ?? null,
  };
}

/** One SVG path per uninterrupted observation run. Null gaps cannot be bridged. */
export function chartSeries(months, width = 640, height = 242) {
  const left = 54, right = 18, top = 17, bottom = 34;
  const summary = productionSummary(months);
  const maximum = Math.max(1, summary.peak ?? 0);
  const x = index => left + (months.length <= 1 ? .5 : index / (months.length - 1)) * (width - left - right);
  const y = value => top + (1 - value / maximum) * (height - top - bottom);
  const runs = []; let run = [];
  for (const [index, row] of months.entries()) {
    if (finite(row.oil_bbl) && row.oil_bbl >= 0) run.push({ x: x(index), y: y(row.oil_bbl), index, ...row });
    else if (run.length) { runs.push(run); run = []; }
  }
  if (run.length) runs.push(run);
  return { width, height, left, right, top, bottom, maximum, baseline: height - bottom, runs, x, y };
}

async function getJSON(path, signal) {
  const response = await fetch(path, { signal, cache: 'no-store' });
  let body;
  try { body = await response.json(); } catch { throw Error('The well API did not return a readable response.'); }
  if (!response.ok) throw Error(body?.error?.message || 'The saved well data is unavailable.');
  return body;
}
function fact(host, label, value) {
  const group = node('div'); group.append(node('dt', label), node('dd', valueText(value))); host.append(group);
}
function errorBox(message) { const box = node('p', message, 'profile-error'); box.setAttribute('role', 'alert'); return box; }
function section(title, caption) {
  const host = node('section', undefined, 'profile-section');
  const heading = node('div', undefined, 'profile-section-head');
  heading.append(node('h3', title)); if (caption) heading.append(node('span', caption));
  const body = node('div', undefined, 'section-content'); host.append(heading, body);
  return { host, body };
}
function provenanceNote(host, provenance) {
  if (!provenance || typeof provenance !== 'object') return;
  const release = provenance.release ?? {};
  const parts = [];
  const dated = provenance.source_date ?? provenance.sourceDate ?? release.source_date;
  if (dated) parts.push('Source: ' + sourceDate(dated));
  if (provenance.source_name ?? provenance.label) parts.push(String(provenance.source_name ?? provenance.label));
  if (provenance.release_id ?? release.id) parts.push('Release ' + (provenance.release_id ?? release.id));
  if (parts.length) host.append(node('p', parts.join(' · '), 'chart-note'));
  if (typeof provenance.note === 'string') host.append(node('p', provenance.note, 'subtle'));
}
function renderMeta(data) {
  const release = data?.release ?? data?.snapshot ?? {};
  const counts = data?.counts ?? {};
  $('releaseLabel').textContent = release.label || release.id || 'Saved local well release';
  const dated = release.source_date ?? release.sourceDate;
  $('releaseDate').textContent = dated ? 'Well-source date · ' + sourceDate(dated) : 'Source date unavailable. Import date is not the observation date.';
  $('apiStatus').textContent = data?.backend?.storage === 'sqlite'
    ? 'Local validated copy · read-only SQLite'
    : data?.backend?.storage === 'postgresql' ? 'Read-only PostgreSQL · saved records' : 'Read-only well API · saved records';
  $('summaryWells').textContent = formatNumber(counts.wells ?? counts.well_count);
  $('summaryBranches').textContent = formatNumber(counts.branches ?? counts.branch_count);
  $('summaryProduction').textContent = formatNumber(counts.production_wells ?? counts.productionWells);
  const host = $('releaseDetailsBody'), facts = node('dl', undefined, 'release-facts');
  fact(facts, 'Release', release.id ?? release.label);
  fact(facts, 'Well-source date', dated ? sourceDate(dated) : null);
  if (release.imported_at ?? release.prepared_at) fact(facts, 'Prepared / imported', sourceDate(release.imported_at ?? release.prepared_at));
  const hash = release.sha256 ?? release.manifest_sha256 ?? data?.provenance?.manifest_sha256;
  if (hash) fact(facts, 'Source fingerprint', hash);
  host.replaceChildren(facts);
  const limits = array(data?.limitations ?? release.limitations);
  if (limits.length) {
    const list = node('ul', undefined, 'release-limits');
    for (const limit of limits) if (typeof limit === 'string') list.append(node('li', limit));
    host.append(list);
  }
}

async function loadWells() {
  state.listController?.abort(); state.listController = new AbortController();
  const token = ++state.listToken;
  $('searchStatus').textContent = 'Searching…'; $('previousWells').disabled = true; $('nextWells').disabled = true;
  $('wellResults').setAttribute('aria-busy', 'true');
  try {
    const params = new URLSearchParams({ q: state.query, limit: String(PAGE_SIZE), offset: String(state.offset) });
    const data = await getJSON('/api/wells?' + params, state.listController.signal);
    if (token !== state.listToken) return;
    const records = rows(data);
    state.total = finite(data.total) && data.total >= 0 ? data.total : records.length;
    state.offset = finite(data.offset) && data.offset >= 0 ? data.offset : state.offset;
    $('searchStatus').textContent = formatNumber(state.total) + ' matching records';
    $('wellResults').replaceChildren();
    for (const raw of records) {
      const well = wellObject(raw), file = wellFile(well);
      if (!/^\d{1,8}$/.test(file)) continue;
      const button = node('button', undefined, 'well-result');
      button.type = 'button'; button.dataset.file = file; button.setAttribute('aria-pressed', String(state.selected === file));
      button.append(node('strong', nameOf(well)), node('span', well.operator || 'Reported operator unavailable'));
      const info = node('small'); info.append(node('span', 'File ' + file));
      if (well.api) info.append(node('span', 'API ' + well.api));
      button.append(info); button.onclick = () => selectWell(file); $('wellResults').append(button);
    }
    if (!records.length) $('wellResults').append(node('p', 'No saved wells match that search. Try part of the name, a file number, or API.', 'profile-message'));
    $('wellPage').textContent = state.total ? `${formatNumber(state.offset + 1)}–${formatNumber(Math.min(state.offset + records.length, state.total))} of ${formatNumber(state.total)}` : '0 records';
    $('previousWells').disabled = state.offset === 0; $('nextWells').disabled = state.offset + PAGE_SIZE >= state.total;
  } catch (error) {
    if (error.name === 'AbortError' || token !== state.listToken) return;
    $('searchStatus').textContent = 'Unavailable'; $('wellResults').replaceChildren(errorBox(error.message)); $('wellPage').textContent = '';
  } finally { if (token === state.listToken) $('wellResults').setAttribute('aria-busy', 'false'); }
}

function renderBranches(branches, provenance) {
  const records = rows(branches), { host, body } = section('Survey branches', records.length + ' saved branch' + (records.length === 1 ? '' : 'es'));
  if (!records.length) body.append(node('p', 'No branch geometry is available in this release. Absence here does not establish that the well was never drilled.', 'subtle'));
  else {
    const wrap = node('div', undefined, 'profile-table-wrap'), table = node('table', undefined, 'profile-table');
    table.setAttribute('aria-label', 'Saved survey branch measurements');
    const head = node('thead'), headings = node('tr');
    for (const label of ['Branch / API', 'Stations', 'Maximum MD', 'Maximum TVD']) { const cell = node('th', label); cell.scope = 'col'; headings.append(cell); }
    head.append(headings); const bodyRows = node('tbody');
    for (const branch of records) {
      const row = node('tr'), identity = node('td'); identity.append(node('strong', valueText(branch.branch ?? branch.name ?? branch.id)));
      if (branch.api) identity.append(node('div', String(branch.api), 'subtle'));
      row.append(identity, node('td', formatNumber(branch.station_count ?? branch.count)),
        node('td', finite(branch.max_md_ft ?? branch.maxMD) ? formatNumber(branch.max_md_ft ?? branch.maxMD) + ' ft' : 'Unavailable'),
        node('td', finite(branch.max_tvd_ft ?? branch.maxTVD) ? formatNumber(branch.max_tvd_ft ?? branch.maxTVD) + ' ft' : 'Unavailable'));
      bodyRows.append(row);
    }
    table.append(head, bodyRows); wrap.append(table); body.append(wrap);
  }
  body.append(node('p', 'Survey branches can share a physical well and trajectory. Branch counts are not producing-well counts. TVD and MD retain the source depth reference.', 'chart-note'));
  provenanceNote(body, provenance); return host;
}

function svgElement(tag, attributes = {}, text) {
  const element = documentRef.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, String(value));
  if (text !== undefined) element.textContent = text;
  return element;
}
function renderProduction(data, fallbackCoverage) {
  const normalized = normalizeProduction(data), allMonths = normalized.months, stats = productionSummary(allMonths);
  const { host, body } = section('Reported oil production', 'Historical monthly observations');
  const coverage = data?.coverage ?? fallbackCoverage ?? {};
  const units = typeof data?.units === 'string' ? data.units : 'bbl';
  const coverageText = coverage.label || coverage.status || (stats.observed ? `${formatNumber(stats.observed)} months with reported values` : 'No reported values in this release');
  body.append(node('span', readable(coverageText), 'coverage-label'));
  const metrics = node('dl', undefined, 'production-metrics');
  for (const [label, value, unit] of [
    ['Oil across reported months', stats.total, units], ['Peak reported month', stats.peak, units],
    ['Observed month range', stats.first ? monthLabel(stats.first) + ' – ' + monthLabel(stats.last) : null, null],
  ]) {
    const group = node('div'), result = node('dd', typeof value === 'string' ? value : formatNumber(value));
    if (unit && finite(value)) result.append(node('small', unit));
    group.append(node('dt', label), result); metrics.append(group);
  }
  body.append(metrics);
  if (!stats.observed) body.append(node('p', 'No monthly oil observations are available for this well in the saved production source. Missing coverage is not reported zero production.', 'subtle'));
  else {
    // Do not imply observations before the first month reported for this well.
    const firstObserved = allMonths.findIndex(row => row.oil_bbl !== null);
    const lifetime = allMonths.slice(firstObserved);
    const toolbar = node('div', undefined, 'chart-toolbar'), range = node('div', undefined, 'chart-range');
    toolbar.append(node('p', 'Monthly oil · ' + units));
    const allButton = node('button', 'Full record'), recentButton = node('button', 'Last 36 months');
    allButton.type = recentButton.type = 'button'; range.append(allButton, recentButton); toolbar.append(range); body.append(toolbar);
    const chartHost = node('div'), inspect = node('div', undefined, 'chart-inspection');
    const label = node('label', 'Inspect month'); label.htmlFor = 'profileMonth';
    const slider = node('input'); slider.type = 'range'; slider.id = 'profileMonth'; slider.min = '0'; slider.step = '1';
    const output = node('output'); output.htmlFor = 'profileMonth'; output.setAttribute('aria-live', 'polite');
    inspect.append(label, slider, output); body.append(chartHost, inspect);
    const legend = node('div', undefined, 'chart-legend');
    for (const text of ['Reported oil', 'Blank intervals = missing values']) { const entry = node('span'); entry.append(node('i'), documentRef.createTextNode(text)); legend.append(entry); }
    body.append(legend);
    let shown = lifetime, model, cursor, current, recentMode = false;
    function inspectMonth() {
      if (!shown.length || !model) return;
      const index = Math.max(0, Math.min(Number(slider.value), shown.length - 1)), row = shown[index];
      output.textContent = monthLabel(row.month) + ' · ' + (row.oil_bbl === null ? 'Missing' : formatNumber(row.oil_bbl) + ' ' + units);
      slider.setAttribute('aria-valuetext', output.textContent);
      cursor.setAttribute('x1', model.x(index)); cursor.setAttribute('x2', model.x(index));
      if (row.oil_bbl === null) current.setAttribute('visibility', 'hidden');
      else { current.setAttribute('visibility', 'visible'); current.setAttribute('cx', model.x(index)); current.setAttribute('cy', model.y(row.oil_bbl)); }
    }
    function draw(recent, preserveMonth = false) {
      const previousMonth = shown[Number(slider.value)]?.month;
      recentMode = recent; shown = recent ? lifetime.slice(-36) : lifetime;
      // Match SVG coordinates to the actual profile width so axis labels do
      // not shrink into unreadable text on a phone.
      const chartWidth = Math.max(270, Math.min(820, ($('wellProfile').clientWidth || 688) - 48));
      model = chartSeries(shown, chartWidth, 242);
      allButton.setAttribute('aria-pressed', String(!recent)); recentButton.setAttribute('aria-pressed', String(recent));
      const svg = svgElement('svg', { viewBox: `0 0 ${model.width} ${model.height}`, role: 'img', 'aria-labelledby': 'productionChartTitle productionChartDescription', class: 'production-chart' });
      svg.append(svgElement('title', { id: 'productionChartTitle' }, 'Reported monthly oil production'), svgElement('desc', { id: 'productionChartDescription' }, `Oil in ${units}. ${productionSummary(shown).observed} months with values. Lines stop at missing months; reported zero stays on the baseline.`));
      for (let tick = 0; tick <= 3; tick++) {
        const value = model.maximum * tick / 3, y = model.y(value);
        svg.append(svgElement('line', { x1: model.left, x2: model.width - model.right, y1: y, y2: y, class: 'chart-grid' }), svgElement('text', { x: model.left - 9, y: y + 4, 'text-anchor': 'end' }, value >= 1000 ? (value / 1000).toLocaleString('en-US', { maximumFractionDigits: 1 }) + 'k' : Math.round(value)));
      }
      for (const run of model.runs) {
        const points = run.map(point => `${point.x.toFixed(2)},${point.y.toFixed(2)}`);
        if (run.length > 1) {
          svg.append(svgElement('path', { d: `M${points[0]} L${points.slice(1).join(' L')} L${run.at(-1).x},${model.baseline} L${run[0].x},${model.baseline} Z`, class: 'chart-area' }), svgElement('path', { d: 'M' + points.join(' L'), class: 'chart-line' }));
        } else svg.append(svgElement('circle', { cx: run[0].x, cy: run[0].y, r: 2.6, class: 'chart-point' }));
      }
      const positions = [...new Set([0, Math.floor((shown.length - 1) / 2), shown.length - 1])];
      for (const index of positions) svg.append(svgElement('text', { x: model.x(index), y: model.height - 7, 'text-anchor': index === 0 ? 'start' : index === shown.length - 1 ? 'end' : 'middle' }, monthLabel(shown[index].month)));
      cursor = svgElement('line', { y1: model.top, y2: model.baseline, class: 'chart-cursor' });
      current = svgElement('circle', { r: 4.5, class: 'chart-current' }); svg.append(cursor, current); chartHost.replaceChildren(svg);
      const previousIndex = preserveMonth ? shown.findIndex(row => row.month === previousMonth) : -1;
      slider.max = String(shown.length - 1); slider.value = String(previousIndex >= 0 ? previousIndex : shown.length - 1); slider.disabled = shown.length <= 1; inspectMonth();
    }
    allButton.onclick = () => draw(false); recentButton.onclick = () => draw(true); slider.oninput = inspectMonth;
    state.resizeChart = () => draw(recentMode, true); draw(false);
  }
  body.append(node('p', 'The sum includes available observations only; it is not verified lifetime production. The chart starts at the first reported month. Missing calendar months stay blank, while a reported zero remains zero. Production is counted at well level, not repeated for each survey branch.', 'chart-note'));
  if (coverage.note ?? coverage.caveat) body.append(node('p', String(coverage.note ?? coverage.caveat), 'subtle'));
  if (finite(coverage.invalid_months) && coverage.invalid_months > 0) body.append(node('p', formatNumber(coverage.invalid_months) + ' saved well-month record(s) were marked invalid and withheld. These are not reported zeros.', 'context-warning'));
  if (normalized.invalid || normalized.conflicts) body.append(node('p', 'Some malformed or conflicting observations were withheld from this chart. Review the saved source before interpreting those intervals.', 'context-warning'));
  provenanceNote(body, data?.provenance); return host;
}

function renderDSUs(data) {
  const records = rows(data), total = data?.coverage?.total;
  const caption = data?.coverage?.truncated && finite(total) ? `${records.length} of ${formatNumber(total)} relationships shown` : records.length + ' saved relationship' + (records.length === 1 ? '' : 's');
  const { host, body } = section('DSU spatial relationships', caption);
  if (!records.length) body.append(node('p', 'No supported DSU relationship is available for this well in the prepared release. This is not evidence that the well has no spacing orders.', 'subtle'));
  else {
    const list = node('div', undefined, 'dsu-list');
    for (const record of records) {
      const item = node('article', undefined, 'dsu-record'); item.append(node('h4', record.label || record.dsu_id || 'Saved DSU relationship'));
      item.append(node('p', readable(record.relationship || 'Geometric relationship; legal assignment unresolved')));
      const facts = node('dl'); fact(facts, 'Formation (source)', record.formation);
      fact(facts, 'Nominal source acres', finite(record.nominal_acres) ? formatNumber(record.nominal_acres) : null);
      if (finite(record.overlap_ft)) fact(facts, 'Mapped overlap', formatNumber(record.overlap_ft) + ' ft');
      if (finite(record.overlap_share)) fact(facts, 'Whole-well mapped overlap', (record.overlap_share * 100).toLocaleString('en-US', { maximumFractionDigits: 1 }) + '%');
      if (record.source_date) fact(facts, 'Source date', sourceDate(record.source_date));
      item.append(facts); if (record.caveat) item.append(node('p', record.caveat)); list.append(item);
    }
    body.append(list);
  }
  body.append(node('p', data?.caveat || data?.coverage?.caveat || 'Relationships use deduplicated mapped lateral linework across the well’s survey branches and original polygon geometry. They do not establish legal well allocation, mineral ownership, current controlling authority, or remaining drilling locations. Overlapping DSUs are not additive.', 'context-warning'));
  if (data?.coverage?.truncated) body.append(node('p', 'This is a bounded relationship list. Additional source relationships are omitted from this response.', 'subtle'));
  provenanceNote(body, data?.provenance); return host;
}

export function fracFocusWater(event) {
  const value = event?.water_gallons;
  if (event?.water_status !== 'reported' || !finite(value) || value < 0) {
    return { gallons: null, barrels: null, label: event?.water_status === 'invalid' ? 'Needs review' : 'Not reported' };
  }
  return { gallons: value, barrels: value / 42, label: value.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' gal' };
}

/** A treatment belongs to an exact well identity in the profile's release.
 * A ten-digit API candidate cannot silently become a confirmed treatment. */
export function fracFocusMatchesProfile(data, detail) {
  const well = wellObject(detail), release = detail?.provenance?.release?.id ?? detail?.provenance?.release_id;
  if (!release || data?.provenance?.release_id !== release || !data?.well
      || String(data.well.file_number) !== wellFile(well) || data.well.api !== well.api) return false;
  if (well.api) return true;
  // A missing identity can describe unknown coverage, but cannot carry events.
  return data?.coverage?.status === 'review_required' && Array.isArray(data?.events) && !data.events.length;
}

function renderFracFocus(data) {
  const events = array(data?.events), coverage = data?.coverage ?? {}, provenance = data?.provenance ?? {};
  const count = finite(coverage.total) ? coverage.total : events.length;
  const caption = coverage.truncated ? `${events.length} of ${formatNumber(count)} disclosures` : `${formatNumber(count)} disclosure${count === 1 ? '' : 's'}`;
  const { host, body } = section('FracFocus treatments', caption);
  host.id = 'fracfocus'; host.className += ' fracfocus-section';
  body.append(node('p', 'Reported hydraulic-fracturing treatments for this well.', 'subtle'));
  if (!events.length) {
    body.append(node('p', coverage.status === 'review_required'
      ? 'Possible disclosures need source or identity review before they can be displayed for this well.'
      : 'No exact-API disclosure was found in this local snapshot. This does not establish that the well was never fractured.', 'fracfocus-empty'));
  }
  function eventCard(event) {
    const card = node('article', undefined, 'fracfocus-event');
    const header = node('div', undefined, 'fracfocus-event-heading');
    const date = event.job_end_date ? sourceDate(event.job_end_date) : 'End date not reported';
    header.append(node('h4', date), node('span', 'Treatment completed', 'subtle')); card.append(header);
    const water = fracFocusWater(event), facts = node('dl', undefined, 'fracfocus-facts');
    const quantity = node('div', undefined, 'fracfocus-water');
    quantity.append(node('dt', 'Reported carrier water'), node('dd', water.label));
    if (water.barrels !== null) quantity.append(node('span', water.barrels.toLocaleString('en-US', { maximumFractionDigits: 1 }) + ' bbl · 42 gal/bbl', 'subtle'));
    facts.append(quantity); fact(facts, 'Operator at disclosure', event.operator_name || 'Not reported'); card.append(facts);
    const details = node('details', undefined, 'fracfocus-details');
    details.append(node('summary', 'Treatment record'));
    const source = node('dl', undefined, 'release-facts');
    fact(source, 'Started', event.job_start_date ? sourceDate(event.job_start_date) : 'Not reported');
    fact(source, 'Completed', event.job_end_date ? sourceDate(event.job_end_date) : 'Not reported');
    fact(source, 'Reported well name', event.well_name || 'Not reported');
    fact(source, 'API', event.api); fact(source, 'Disclosure ID', event.disclosure_id); details.append(source); card.append(details);
    for (const note of array(event.quality_notes)) {
      if (typeof note === 'string' && note !== 'Reported treatment-water volume is missing; it is not zero.') card.append(node('p', note, 'context-warning'));
    }
    return card;
  }
  const list = node('div', undefined, 'fracfocus-events');
  for (const event of events.slice(0, 3)) list.append(eventCard(event)); body.append(list);
  if (events.length > 3) {
    const more = node('details', undefined, 'fracfocus-more');
    more.append(node('summary', `Show ${events.length - 3} older disclosure${events.length - 3 === 1 ? '' : 's'}`));
    const older = node('div', undefined, 'fracfocus-events');
    for (const event of events.slice(3)) older.append(eventCard(event)); more.append(older); body.append(more);
  }
  if (events.length && coverage.api10_review_count > 0) body.append(node('p', `${formatNumber(coverage.api10_review_count)} additional disclosure(s) have a different API suffix and are not included.`, 'context-warning'));
  if (coverage.quarantined_count > 0) body.append(node('p', `${formatNumber(coverage.quarantined_count)} source record(s) are withheld for review.`, 'context-warning'));
  if (coverage.truncated) body.append(node('p', 'Additional disclosures are omitted from this bounded response.', 'subtle'));
  const latest = provenance.latest_job_end ? ` Latest North Dakota job date in the snapshot: ${sourceDate(provenance.latest_job_end)}.` : '';
  body.append(node('p', 'Saved FracFocus snapshot.' + latest + ' More recent treatments or corrections may be missing.', 'chart-note'));
  const about = node('details', undefined, 'fracfocus-details fracfocus-source');
  about.append(node('summary', 'Source & interpretation'));
  if (typeof coverage.note === 'string') about.append(node('p', coverage.note, 'subtle'));
  about.append(node('p', 'Water is the reported carrier-fluid volume for each treatment, not a monthly injection rate. Disclosures are shown separately and are not repeated for survey branches. Their exact completed intervals have not been established.', 'subtle'));
  about.append(node('p', 'Proppant totals are not included yet; ingredient records need validation. Unreported quantities stay unknown, while a reported zero remains zero.', 'subtle'));
  const link = node('a', 'About the FracFocus source ↗'); link.href = 'https://www.fracfocus.org/data-download'; link.target = '_blank'; link.rel = 'noopener noreferrer'; about.append(link);
  const source = node('dl', undefined, 'release-facts');
  const prepared = new Date(provenance.prepared_at);
  const preparedLabel = Number.isNaN(prepared.valueOf()) ? 'Unavailable' : prepared.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/Chicago' });
  fact(source, 'Source file', provenance.source_file); fact(source, 'Prepared (Central)', preparedLabel);
  fact(source, 'Source fingerprint', provenance.source_sha256); about.append(source); body.append(about);
  return host;
}

function renderProfile(detail, productionResult, dsuResult, fracFocusResult) {
  const well = wellObject(detail), host = $('wellProfile'), file = wellFile(well) || state.selected;
  const heading = node('div', undefined, 'profile-heading'), identity = node('div');
  identity.append(node('p', 'WELL PROFILE / FILE ' + file, 'eyebrow'));
  const title = node('h2', nameOf(well)); title.tabIndex = -1; identity.append(title, node('p', well.operator || 'Reported operator unavailable')); heading.append(identity);
  const viewer = safeViewerURL(detail.viewer_url);
  if (viewer) { const link = node('a', 'View mapped well ↗', 'viewer-action'); link.href = viewer; heading.append(link); }
  const facts = node('dl', undefined, 'identity-grid');
  fact(facts, 'File number', file); fact(facts, 'API identity', well.api || array(well.apis ?? detail.apis).join(' · ') || null);
  fact(facts, 'Reported operator', well.operator); fact(facts, 'Status (source)', well.status);
  if (well.county) fact(facts, 'County', well.county);
  host.replaceChildren(heading, facts);
  if (!viewer) host.append(node('p', 'A verified viewer link is not available for this profile. No branch identity has been inferred.', 'subtle'));
  const release = detail.provenance?.release?.id ?? detail.provenance?.release_id;
  const changedRelease = result => result.status === 'fulfilled' && release && result.value?.provenance?.release_id && release !== result.value.provenance.release_id;
  const productionChanged = changedRelease(productionResult), dsuChanged = changedRelease(dsuResult);
  if (fracFocusResult?.status === 'fulfilled' && fracFocusMatchesProfile(fracFocusResult.value, detail)) host.append(renderFracFocus(fracFocusResult.value));
  else {
    const block = section('FracFocus treatments');
    block.body.append(errorBox(fracFocusResult?.status === 'fulfilled'
      ? 'The well identity or source release changed while treatments were loading. Select this well again to load matching records.'
      : 'The local FracFocus snapshot could not be loaded. Treatment coverage is unavailable.'));
    host.append(block.host);
  }
  if (productionResult.status === 'fulfilled' && !productionChanged) host.append(renderProduction(productionResult.value, detail.production_coverage));
  else if (productionChanged) { const block = section('Reported oil production'); block.body.append(errorBox('The source release changed while this profile was loading. Select this well again to load production from the same release.')); host.append(block.host); }
  else { const block = section('Reported oil production'); block.body.append(errorBox('Production history could not be loaded. Missing coverage has not been replaced with zero.')); host.append(block.host); }
  host.append(renderBranches(detail.branches, detail.provenance));
  if (dsuResult.status === 'fulfilled' && !dsuChanged) host.append(renderDSUs(dsuResult.value));
  else if (dsuChanged) { const block = section('DSU spatial relationships'); block.body.append(errorBox('The source release changed while this profile was loading. Select this well again to load spatial relationships from the same release.')); host.append(block.host); }
  else { const block = section('DSU spatial relationships'); block.body.append(errorBox('Spatial relationships could not be loaded. No legal or geometric assignment has been inferred.')); host.append(block.host); }
  if (detail.provenance) { const block = section('Profile provenance'); provenanceNote(block.body, detail.provenance); const hash = detail.provenance.manifest_sha256 ?? detail.provenance.sha256 ?? detail.provenance.release?.sha256; if (hash) { const dl = node('dl', undefined, 'release-facts'); fact(dl, 'Source fingerprint', hash); block.body.append(dl); } if (!block.body.children.length) block.body.append(node('p', 'The source release is described below. Field-specific dates may be unavailable.', 'subtle')); host.append(block.host); }
  const editing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(String(documentRef.activeElement?.tagName).toUpperCase());
  if (globalThis.matchMedia?.('(max-width:900px)').matches && !editing) { title.focus({ preventScroll: true }); heading.scrollIntoView({ block: 'start' }); }
}

async function selectWell(file) {
  if (!/^\d{1,8}$/.test(file)) return;
  state.profileController?.abort(); state.profileController = new AbortController(); const token = ++state.profileToken;
  state.selected = file; state.resizeChart = null;
  for (const button of $('wellResults').querySelectorAll('.well-result')) button.setAttribute('aria-pressed', String(button.dataset.file === file));
  const host = $('wellProfile'); host.setAttribute('aria-busy', 'true'); host.replaceChildren(node('p', 'Loading saved well profile…', 'profile-loading'));
  const url = new URL(globalThis.location.href); url.searchParams.set('well', file); globalThis.history.replaceState(null, '', url);
  const base = '/api/wells/' + encodeURIComponent(file), signal = state.profileController.signal;
  const results = await Promise.allSettled([getJSON(base, signal), getJSON(base + '/production', signal), getJSON(base + '/dsus', signal), getJSON(base + '/fracfocus', signal)]);
  if (token !== state.profileToken) return;
  host.setAttribute('aria-busy', 'false');
  if (results[0].status === 'rejected') { if (results[0].reason.name !== 'AbortError') host.replaceChildren(errorBox(results[0].reason.message)); return; }
  renderProfile(results[0].value, results[1], results[2], results[3]);
}

async function initialize() {
  let timer, resizeTimer;
  globalThis.addEventListener?.('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => state.resizeChart?.(), 120); });
  function search() { state.query = $('wellQuery').value.trim(); state.offset = 0; $('clearSearch').hidden = !state.query; loadWells(); }
  $('wellQuery').oninput = () => { clearTimeout(timer); $('clearSearch').hidden = !$('wellQuery').value; timer = setTimeout(search, 220); };
  $('wellSearch').onsubmit = event => { event.preventDefault(); clearTimeout(timer); search(); };
  $('clearSearch').onclick = () => { clearTimeout(timer); $('wellQuery').value = ''; search(); $('wellQuery').focus(); };
  $('previousWells').onclick = () => { state.offset = Math.max(0, state.offset - PAGE_SIZE); loadWells(); };
  $('nextWells').onclick = () => { state.offset += PAGE_SIZE; loadWells(); };
  const query = new URLSearchParams(globalThis.location.search);
  if (query.get('q')) { $('wellQuery').value = query.get('q').slice(0, 150); state.query = $('wellQuery').value; $('clearSearch').hidden = false; }
  loadWells();
  if (/^\d{1,8}$/.test(query.get('well') || '')) selectWell(query.get('well'));
  try { renderMeta(await getJSON('/api/wells/meta')); }
  catch (error) { $('releaseLabel').textContent = 'Well release unavailable'; $('apiStatus').textContent = 'The local well API is not ready.'; $('releaseDetailsBody').replaceChildren(errorBox(error.message)); }
}
if (documentRef) initialize();
