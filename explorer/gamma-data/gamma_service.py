"""Read-only LAS gamma catalog and observed VERT-survey alignment, in viewer feet.

Run once: python gamma_service.py --build
HTTP callers: GammaStore().get_well('21994', source_id=None, step=10)
Original LAS and survey files are never changed. No calibration or SSTVD is applied.
"""
from pathlib import Path
import argparse, collections, io, json, math, os, re, struct, time
import numpy as np

BASE = Path(__file__).resolve().parent
WORK = BASE.parent
SETTINGS_PATH = WORK / 'local-settings.json'
LOCAL_SETTINGS = json.loads(SETTINGS_PATH.read_text(encoding='utf8')) if SETTINGS_PATH.exists() else {}
LAS = Path(os.environ.get('BAKKEN_LAS_DIR', LOCAL_SETTINGS.get('lasDir', str(WORK / 'local-data' / 'las'))))
MANIFEST = Path(os.environ.get('BAKKEN_MANIFEST', str(WORK / 'full-dataset' / 'manifest.json')))
DBF = Path(os.environ.get('BAKKEN_SURVEY_DBF', LOCAL_SETTINGS.get('surveyDbf', str(WORK / 'local-data' / 'OGD_Horizontals.dbf'))))
if not DBF.exists(): DBF = LAS / 'OGD_Horizontals' / 'OGD_Horizontals.dbf'
REFERENCE = 'Relative TVD in feet; original logged MD matched to observed survey MD; no elevation or datum correction applied'

def dump(path, data):
    path.write_text(json.dumps(data, separators=(',', ':'), allow_nan=False), encoding='utf8')

def number(value):
    try: return float(str(value).strip().split()[0])
    except (ValueError, IndexError, TypeError): return None

def dbf_rows():
    with DBF.open('rb') as f:
        head = f.read(32)
        count = struct.unpack_from('<I', head, 4)[0]
        start, size = struct.unpack_from('<HH', head, 8)
        fields = []
        for _ in range((start - 33) // 32):
            field = f.read(32)
            fields.append((field[:11].split(b'\0')[0].decode().lower(), 'S' + str(field[16])))
    dtype = np.dtype([('_deleted', 'S1')] + fields)
    if dtype.itemsize != size: raise ValueError('Unexpected DBF record layout')
    return np.memmap(DBF, dtype=dtype, mode='r', offset=start, shape=(count,))

def build_index():
    target = BASE / 'survey-index.npy'
    stat = DBF.stat()
    stamp = {'source': str(DBF), 'size': stat.st_size, 'mtimeNs': stat.st_mtime_ns}
    stamp_file = BASE / 'survey-index-meta.json'
    if target.exists() and stamp_file.exists() and json.loads(stamp_file.read_text()) == stamp: return
    rows = dbf_rows(); blocks = []
    # A sorted permit/record index allows each request to read only that well's DBF records.
    dtype = np.dtype([('permit', '<i4'), ('record', '<u4')])
    for start in range(0, len(rows), 100000):
        block = rows[start:start + 100000]
        permits = np.char.strip(block['wl_permit'])
        valid = np.char.isdigit(permits) & (block['_deleted'] != b'*')
        ii = np.flatnonzero(valid)
        arr = np.empty(len(ii), dtype=dtype)
        arr['permit'] = permits[valid].astype('i4'); arr['record'] = start + ii
        blocks.append(arr)
    data = np.concatenate(blocks)
    data = data[np.argsort(data['permit'], kind='stable')]
    np.save(target, data); dump(stamp_file, stamp)
    print('Indexed %s observed survey stations' % len(data), flush=True)

def build_catalog():
    manifest = json.loads(MANIFEST.read_text(encoding='utf8'))
    survey = collections.defaultdict(lambda: {'api10s': set(), 'verticalMaxMD': 0, 'hasVertical': False})
    for well in manifest['wells']:
        item = survey[well['permit']]; item['api10s'].add(well['api'][:10])
        if well['branch'].upper() == 'VERT':
            item['hasVertical'] = True; item['verticalMaxMD'] = max(item['verticalMaxMD'], well['maxMD'])
    wells = {}; files = 0; candidates = 0; errors = collections.Counter()
    for line in (WORK / 'las_header_records.jsonl').open(encoding='utf8'):
        record = json.loads(line); files += 1
        permit = record.get('file_no'); curves = record.get('gamma_curves', [])
        if not permit or not curves: continue
        geo = survey.get(permit, {'api10s': set(), 'verticalMaxMD': 0, 'hasVertical': False})
        item = wells.setdefault(permit, {'permit': permit, 'api10s': sorted(geo['api10s']), 'hasVertical': geo['hasVertical'], 'sources': []})
        meta = record.get('meta', {}); depth = record.get('depth_curve')
        api10s = sorted(set(v['digits'][:10] for v in record.get('identity_candidates', [])))
        identity = 'verified' if api10s and set(api10s).issubset(geo['api10s']) else 'mismatch' if api10s and geo['api10s'] else 'unverified'
        depth_range = [number(meta.get(k, {}).get('value')) for k in ('STRT', 'STOP')]
        depth_unit = depth.get('unit', '') if depth else ''
        factor = 1 / .3048 if depth_unit.upper() in ('M', 'METER', 'METRE', 'METERS', 'METRES') else 1
        for curve in curves:
            description = curve.get('description', ''); mnemonic = curve['mnemonic']; unit = curve.get('unit', '')
            source = {'id': record['file'] + '#' + str(curve['index']), 'file': record['file'], 'curveIndex': curve['index'], 'depthIndex': depth['index'] if depth else None,
                      'mnemonic': mnemonic, 'unit': unit, 'description': description, 'depthUnit': depth_unit, 'headerDepthRange': depth_range,
                      'identityStatus': identity, 'api10s': api10s, 'wellName': meta.get('WELL', {}).get('value', ''), 'service': meta.get('SRVC', {}).get('value', ''),
                      'curveCount': record.get('curve_count', 0), 'asciiLine': record.get('ascii_line'), 'wrap': meta.get('WRAP', {}).get('value', 'NO').upper(),
                      'null': number(meta.get('NULL', {}).get('value', '-999.25')), 'size': record['size'], 'errors': record.get('errors', [])}
            txt = (record['file'] + ' ' + mnemonic + ' ' + description).upper()
            score = 100 if 'API' in unit.upper() else 0
            if mnemonic.upper() in ('GR', 'GRGC', 'GAMMA', 'SGR', 'HSGR', 'GR_EDTC'): score += 40
            if 'CBL' in txt or 'CEMENT' in txt: score -= 110
            if 'DTSM' in txt or 'MUDLOG' in txt: score -= 35
            if any(x in txt for x in ('HCGR', 'CGR', 'URANIUM FREE', 'COMPUTED GAMMA')): score -= 40
            if all(v is not None for v in depth_range):
                lo, hi = sorted(v * factor for v in depth_range)
                score += min(150, max(0, min(hi, geo['verticalMaxMD']) - max(lo, 0)) / 60)
            if identity == 'verified': score += 30
            if identity == 'mismatch': source['errors'] = source['errors'] + ['API does not match viewer FileNo']
            if not depth: source['errors'] = source['errors'] + ['No recognized measured-depth curve']
            if depth_unit.upper() not in ('F', 'FT', 'FEET', 'FOOT', 'M', 'METER', 'METRE', 'METERS', 'METRES'): source['errors'] = source['errors'] + ['Unknown depth units']
            if source['errors']: score -= 10000
            source['score'] = round(score, 2)
            item['sources'].append(source); candidates += 1
            errors.update(source['errors'])
    for item in wells.values():
        item['sources'].sort(key=lambda source: (-source['score'], source['file'], source['curveIndex']))
        item['defaultSourceId'] = next((s['id'] for s in item['sources'] if not s['errors']), None)
    stats = {'lasFiles': files, 'gammaCandidateCurves': candidates, 'gammaFileNos': len(wells), 'matchedFileNos': sum(bool(w['api10s']) for w in wells.values()),
             'verticalFileNos': sum(w['hasVertical'] for w in wells.values()), 'loadableVerticalFileNos': sum(w['hasVertical'] and w['defaultSourceId'] is not None for w in wells.values()),
             'candidateErrors': dict(errors), 'qualification': 'Header candidates; numeric usability is verified when each curve is loaded.'}
    catalog = {'version': 1, 'origin': manifest['origin'], 'reference': REFERENCE, 'stats': stats, 'wells': wells}
    dump(BASE / 'catalog.json', catalog)
    public = {'version': 1, 'origin': manifest['origin'], 'reference': REFERENCE, 'stats': stats, 'wells': []}
    for w in wells.values():
        source = next((s for s in w['sources'] if s['id'] == w['defaultSourceId']), None)
        public['wells'].append({k: w[k] for k in ('permit', 'api10s', 'hasVertical', 'defaultSourceId')} | {'sourceCount': len(w['sources']), 'wellName': source['wellName'] if source else '', 'defaultUnit': source['unit'] if source else ''})
    dump(BASE / 'catalog-client.json', public)
    print(json.dumps(stats), flush=True)

class GammaStore:
    def __init__(self):
        self.catalog = json.loads((BASE / 'catalog.json').read_text(encoding='utf8'))
        self.index = np.load(BASE / 'survey-index.npy', mmap_mode='r')
        self.records = dbf_rows()
        self.cache = {}

    def get_sources(self, permit):
        return self.catalog['wells'].get(str(permit))

    def _survey(self, permit):
        key = int(permit); values = self.index['permit']
        a, b = np.searchsorted(values, [key, key + 1])
        records = self.records[self.index['record'][a:b]]
        groups = collections.defaultdict(list)
        for record in records:
            text = lambda k: record[k].decode('cp1252').strip()
            branch = text('well_sub').upper()
            if branch != 'VERT': continue
            api = re.sub(r'\D', '', text('api_wellno'))[:10]
            vals = [number(text(k)) for k in ('measdpth', 'tvd', 'long', 'lat')]
            if any(v is None or not math.isfinite(v) for v in vals): continue
            if vals[0] < 0 or vals[1] < 0 or not -180 <= vals[2] <= 180 or not -89 <= vals[3] <= 89: continue
            groups[(branch, api)].append(vals)
        result = []
        for (branch, api), vals in groups.items():
            # Mirror viewer: stable sort and keep last station at repeated MD.
            table = np.asarray(vals); table = table[np.argsort(table[:, 0], kind='stable')]
            table = table[np.r_[np.diff(table[:, 0]) != 0, True]]
            if len(table) > 1: result.append((branch, api, table))
        return result

    def _read_curve(self, source, *, mask_zero_flatlines=True):
        if source['errors']: raise ValueError('; '.join(source['errors']))
        path = LAS / source['file']
        # File names only come from the local catalog, never from arbitrary caller paths.
        if path.parent != LAS: raise ValueError('Invalid source filename')
        ci, di, count = source['curveIndex'], source['depthIndex'], source['curveCount']
        flags = ['Raw source gamma values; cross-tool calibration has not been established']; bad_rows = 0; result = []
        with path.open(encoding='cp1252', errors='replace') as src:
            # Inventory line numbers were counted with binary readline. Text mode
            # also splits bare CR characters, so a saved line number is not a safe
            # data offset. Locate the actual LAS ASCII section in this same stream.
            header = []; header_chars = 0
            for _ in range(20000):
                line = src.readline()
                if not line: raise ValueError('No ASCII data section in selected LAS')
                header.append(line); header_chars += len(line)
                if header_chars > 4 * 1024 * 1024: raise ValueError('LAS header exceeds 4 MB inspection limit')
                section_text = line.strip().upper()
                if re.match(r'^~\s*(?:A|ASCII)(?:\s|$)', section_text) or section_text.startswith('~LOG_DATA'): break
            else: raise ValueError('LAS header exceeds 20000-line inspection limit')
            # The earlier inventory deliberately ignored blank mnemonics. A few LAS
            # headers use a leading-dot CCL mnemonic, which adds a physical column.
            # Permit trailing additions only after checking the selected GR position.
            physical = []; section = ''
            for line in header:
                text = line.strip()
                if not text or text.startswith('#'): continue
                if text.startswith('~'):
                    sec = text[1:].strip().upper()
                    section = 'C' if sec.startswith('LOG_DEFINITION') else sec[:1]
                    continue
                if section == 'C' and '.' in text:
                    before = text.split(':', 1)[0]
                    mnemonic = before.split('.', 1)[0].strip()
                    physical.append(mnemonic)
            if len(physical) != count:
                if len(physical) < count or ci >= len(physical) or physical[ci].upper() != source['mnemonic'].upper():
                    raise ValueError('Physical LAS curve positions disagree with header inventory')
                if any(not name for name in physical[:max(di, ci) + 1]):
                    raise ValueError('Unrecognized physical curve before selected gamma/depth column')
                flags.append('%s additional trailing physical LAS columns; selected curve position verified against source header' % (len(physical) - count))
                count = len(physical)
            if source['wrap'].startswith('Y'):
                pending = []; numeric_started = False; heading_lines = 0
                # A common wrapped LAS layout puts the mnemonic table after ~A.
                # Only known curve-name tokens may be skipped, and only before
                # the very first numeric token. Afterwards any bad token is fatal.
                heading_tokens = {re.sub(r'[^A-Z0-9_]', '', name.upper()) for name in physical if name}
                heading_tokens.update(('DEPTH', 'DEPT', 'MD', 'MDEP', 'DEPTM', 'DEPTF'))
                for line in src:
                    text = line.split('#', 1)[0].strip()
                    if not text: continue
                    if text.startswith('~'): break
                    tokens = text.replace(',', ' ').replace('D', 'E').replace('d', 'e').split()
                    try: values = [float(v) for v in tokens]
                    except ValueError:
                        raw_tokens = text.replace(',', ' ').split()
                        labels = [re.sub(r'[^A-Z0-9_]', '', token.upper()) for token in raw_tokens]
                        if not numeric_started and heading_lines < 128 and labels and all(label and label in heading_tokens for label in labels):
                            heading_lines += 1; continue
                        raise ValueError('Non-numeric token in WRAP YES data; unsafe row alignment')
                    numeric_started = True; pending.extend(values)
                    complete = len(pending) // count
                    if complete:
                        arr = np.asarray(pending[:complete * count]).reshape(-1, count)
                        result.append(arr[:, [di, ci]])
                        pending = pending[complete * count:]
                if pending: flags.append('Incomplete final wrapped record omitted')
                if heading_lines: flags.append('%s pre-data wrapped curve-heading lines skipped after verifying mnemonic tokens' % heading_lines)
            else:
                for line in src:
                    text = line.split('#', 1)[0].strip()
                    if not text: continue
                    if text.startswith('~'): break
                    tokens = text.replace(',', ' ').replace('D', 'E').replace('d', 'e').split()
                    if len(tokens) != count:
                        bad_rows += 1; continue
                    try: result.append([float(tokens[di]), float(tokens[ci])])
                    except ValueError: bad_rows += 1
        if not result: raise ValueError('No readable numeric samples in selected curve')
        arr = np.concatenate(result, axis=0) if source['wrap'].startswith('Y') else np.asarray(result)
        if bad_rows: flags.append('%s malformed numeric rows omitted; missing sample gaps retained' % bad_rows)
        d, g = arr[:, 0].copy(), arr[:, 1].copy()
        null = source['null'] if source['null'] is not None else -999.25
        valid_depth = np.isfinite(d) & ~np.isclose(d, null, atol=1e-7, rtol=0) & (d >= 0)
        d, g = d[valid_depth], g[valid_depth]
        if source['depthUnit'].upper() in ('M', 'METER', 'METRE', 'METERS', 'METRES'): d /= .3048
        order = np.argsort(d, kind='stable'); d, g = d[order], g[order]
        duplicate_count = len(d) - len(np.unique(d))
        keep = np.r_[np.diff(d) != 0, True]; d, g = d[keep], g[keep]
        bad = ~np.isfinite(g) | np.isclose(g, null, atol=1e-7, rtol=0)
        null_count = int(bad.sum()); negative_count = int(((g < 0) & ~bad).sum())
        g[bad | (g < 0)] = np.nan
        if len(d) < 2: raise ValueError('Fewer than two usable depth samples')
        native_step = float(np.median(np.diff(d)))
        zeros = np.isfinite(g) & (g == 0)
        zero_flatline_count = 0; zero_intervals = []
        boundaries = np.flatnonzero(np.r_[True, np.diff(zeros.astype(int)) != 0, True])
        for a, b in zip(boundaries[:-1], boundaries[1:]):
            if mask_zero_flatlines and zeros[a] and d[b - 1] - d[a] >= 10:
                zero_flatline_count += b - a; zero_intervals.append([round(float(d[a]), 3), round(float(d[b - 1]), 3)])
                g[a:b] = np.nan
        if zero_flatline_count: flags.append('%s samples in zero flatlines >=10 ft are hidden as suspected fill' % zero_flatline_count)
        if negative_count: flags.append('%s negative gamma samples hidden' % negative_count)
        if duplicate_count: flags.append('%s repeated measured depths; last sample retained' % duplicate_count)
        if source['identityStatus'] != 'verified': flags.append('LAS API identity unavailable; FileNo join only')
        stats = {'rawSamples': int(len(arr)), 'depthSamples': int(len(d)), 'nullSamples': null_count, 'negativeSamples': negative_count, 'zeroFlatlineSamples': int(zero_flatline_count),
                 'zeroFlatlineIntervalsMD': zero_intervals, 'duplicateDepths': duplicate_count, 'nativeStepFt': round(native_step, 5), 'malformedRows': bad_rows}
        return d, g, stats, flags

    def _project(self, table):
        lon0, lat0 = self.catalog['origin']; lo, la = math.radians(lon0), math.radians(lat0)
        a = 6378137.; f = 1 / 298.257222101; e2 = f * (2 - f)
        nn = a / math.sqrt(1 - e2 * math.sin(la)**2)
        origin = np.array([nn * math.cos(la) * math.cos(lo), nn * math.cos(la) * math.sin(lo), nn * (1-e2) * math.sin(la)])
        east = np.array([-math.sin(lo), math.cos(lo), 0]); north = np.array([-math.sin(la)*math.cos(lo), -math.sin(la)*math.sin(lo), math.cos(la)])
        lon, lat = np.radians(table[:, 2]), np.radians(table[:, 3]); N = a / np.sqrt(1 - e2 * np.sin(lat)**2)
        xyz = np.stack([N*np.cos(lat)*np.cos(lon), N*np.cos(lat)*np.sin(lon), N*(1-e2)*np.sin(lat)], axis=1) - origin
        return np.stack([xyz @ east / .3048, -table[:, 1], -(xyz @ north) / .3048], axis=1)

    def get_well(self, permit, source_id=None, step=10):
        permit = str(permit); step = max(2.0, min(50.0, float(step)))
        well = self.get_sources(permit)
        if not well: raise ValueError('No cataloged gamma curves for FileNo ' + permit)
        source_id = source_id or well['defaultSourceId']
        source = next((s for s in well['sources'] if s['id'] == source_id or s['file'] == source_id), None)
        if source is None: raise ValueError('Selected LAS source is unavailable')
        key = (permit, source['id'], step)
        if key in self.cache: return self.cache[key]
        geometry = self._survey(permit)
        if not geometry: raise ValueError('No observed VERT survey branch for this FileNo')
        d, g, stats, flags = self._read_curve(source)
        paths = []; all_gamma = []; valid_count = 0; point_count = 0
        for branch, api, survey in geometry:
            if api not in well['api10s']: flags.append('Survey API does not match viewer; branch skipped'); continue
            if source['api10s'] and api not in source['api10s']: continue
            lo = max(d[0], survey[0, 0]); hi = min(d[-1], survey[-1, 0])
            if hi <= lo: continue
            grid = np.unique(np.r_[lo, np.arange(math.ceil(lo / step) * step, hi, step), hi])
            coords = self._project(survey)
            xyz = np.stack([np.interp(grid, survey[:, 0], coords[:, j]) for j in range(3)], axis=1)
            ii = np.searchsorted(d, grid, side='left'); ii = np.clip(ii, 0, len(d) - 1); prev = np.maximum(ii - 1, 0)
            exact = np.isclose(d[ii], grid, atol=1e-7, rtol=0)
            native_gap = max(1e-3, stats['nativeStepFt'] * 2.1)
            good = np.isfinite(g[ii]) & (exact | (np.isfinite(g[prev]) & ((d[ii] - d[prev]) <= native_gap)))
            values = np.interp(grid, d, np.nan_to_num(g, nan=0)); values[exact] = g[ii[exact]]; values[~good] = np.nan
            # Never hide a source null gap between adjacent display samples (e.g. a 2-ft gap on a 10-ft display grid).
            source_bad_cumsum = np.r_[0, np.cumsum(~np.isfinite(g))]
            source_gap_cumsum = np.r_[0, np.cumsum(np.r_[False, np.diff(d) > native_gap])]
            for j in range(1, len(grid)):
                ia = np.searchsorted(d, grid[j - 1], side='right'); ib = np.searchsorted(d, grid[j], side='left')
                if source_bad_cumsum[ib] > source_bad_cumsum[ia]: values[j] = np.nan
                if source_gap_cumsum[min(ib + 1, len(d))] > source_gap_cumsum[ia]: values[j] = np.nan
            jj = np.clip(np.searchsorted(survey[:, 0], grid), 1, len(survey) - 1)
            survey_gap = (survey[jj, 0] - survey[jj - 1, 0]) > 1000
            values[survey_gap] = np.nan
            if survey_gap.any(): flags.append('Gamma hidden across observed survey gaps >1000 ft')
            points = [[round(float(x), 3), round(float(y), 3), round(float(z), 3), round(float(md), 3), round(float(gr), 4) if math.isfinite(gr) else None] for (x,y,z), md, gr in zip(xyz, grid, values)]
            finite = values[np.isfinite(values)]; all_gamma.extend(finite.tolist()); valid_count += len(finite); point_count += len(values)
            paths.append({'branch': branch, 'api10': api, 'points': points, 'surveyMDRange': [float(survey[0,0]), float(survey[-1,0])], 'loggedMDRange': [float(lo), float(hi)], 'surveyStations': len(survey)})
        if not paths: raise ValueError('Selected gamma curve has no MD overlap with a matching observed VERT survey')
        stats.update({'displaySamples': point_count, 'validDisplaySamples': valid_count, 'displayStepFt': step, 'percentiles': {str(q): round(float(v), 4) for q,v in zip([0,2,5,50,95,98,100],np.percentile(all_gamma, [0,2,5,50,95,98,100]))} if all_gamma else {}})
        if not valid_count: flags.append('No usable gamma samples remain in the observed VERT interval')
        result = {'version': 1, 'permit': permit, 'api10': paths[0]['api10'], 'source': source, 'unit': source['unit'], 'depthUnit': 'ft', 'reference': REFERENCE, 'origin': self.catalog['origin'], 'paths': paths, 'stats': stats, 'flags': sorted(set(flags)),
                  'sampling': 'Raw gamma linearly interpolated at %.0f ft MD spacing; no averaging or cross-tool calibration; null intervals break the tube' % step,
                  'geometryScope': 'Observed VERT survey branch as stored; may include directional stations'}
        if len(self.cache) >= 128: self.cache.pop(next(iter(self.cache)))
        self.cache[key] = result
        return result

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--build', action='store_true'); parser.add_argument('--permit'); args = parser.parse_args()
    if args.build: build_catalog(); build_index()
    store = GammaStore()
    if args.permit:
        result = store.get_well(args.permit); dump(BASE / ('well-' + args.permit + '.json'), result); print(json.dumps(result['stats']))
    else:
        wells = [store.get_well(p) for p in ('21994', '21947', '22058', '21961')]
        dump(BASE / 'pilot-gamma.json', {'version': 1, 'origin': store.catalog['origin'], 'reference': REFERENCE, 'wells': wells})
        for well in wells: print(json.dumps({'permit': well['permit'], 'file': well['source']['file'], 'unit': well['unit'], 'stats': well['stats'], 'flags': well['flags']}), flush=True)

if __name__ == '__main__': main()
