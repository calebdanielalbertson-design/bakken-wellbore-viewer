"""Stream local monthly production exports into an audited local viewer matrix.

No source files are edited. Oil values are reported monthly barrels, not estimates.
Missing / negative / conflicting pool observations propagate to missing well-month.
"""
import argparse
import array
import collections
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import time

def identifier(value):
    if value is None:
        return ''
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
            return ''
        return str(int(value))
    text = str(value).strip()
    if re.fullmatch(r'\d+\.0+', text):
        text = text.split('.')[0]
    text = text.replace('-', '').replace(' ', '')
    return text.lstrip('0') or '0' if text.isdigit() else ''

def month(value):
    if isinstance(value, (dt.datetime, dt.date)):
        return value.year * 100 + value.month
    text = str(value or '').strip()
    try:
        date = dt.date.fromisoformat(text[:10])
        return date.year * 100 + date.month
    except ValueError:
        return None

def oil_value(value):
    if value is None or str(value).strip() == '':
        return None, 'missing'
    try:
        number = float(str(value).replace(',', ''))
    except ValueError:
        return None, 'invalid'
    if not math.isfinite(number):
        return None, 'invalid'
    if number < 0:
        return None, 'negative'
    return number, 'valid'

def rows_csv(path):
    with path.open('r', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        for line, row in enumerate(reader, 2):
            yield line, row, row.get('File No'), row.get('API_WELLNO'), row.get('PoolNo'), row.get('Pool Name'), row.get('RPT_DATE'), row.get('BBLS_OIL_COND')

def rows_xlsx(path):
    import openpyxl
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in book:
            iterator = sheet.iter_rows(values_only=True)
            headers = [str(x or '').strip() for x in next(iterator)]
            if not {'File No', 'API No', 'Pool', 'Date', 'BBLS Oil'} <= set(headers):
                continue
            for line, values in enumerate(iterator, 2):
                if not any(x is not None for x in values):
                    continue
                row = dict(zip(headers, values))
                yield line, row, row.get('File No'), row.get('API No'), None, row.get('Pool'), row.get('Date'), row.get('BBLS Oil')
    finally:
        book.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--xlsx', nargs='*', type=Path, default=[])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if (args.out/'production.json').exists():
        parser.error('Choose a new output folder so an existing production import is not overwritten.')
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text())
    manifest_pairs = sorted({(identifier(w['permit']), identifier(w['api'])) for w in manifest['wells']}, key=lambda w: (int(w[0]), w[1]))
    permit_apis = collections.defaultdict(set)
    api_permits = collections.defaultdict(set)
    for p, a in manifest_pairs:
        permit_apis[p].add(a)
        api_permits[a].add(p)
    # Only a 14-digit API ending in 0000 can equivalently be represented by
    # its 10-digit well base; require uniqueness and the same verified permit.
    base_permits = collections.defaultdict(set)
    for p, a in manifest_pairs:
        if len(a) == 14 and a.endswith('0000'):
            base_permits[a[:10]].add(p)
    lookup = {p: next(iter(v)) for p, v in permit_apis.items() if len(v) == 1}
    source_paths = [args.csv] + args.xlsx
    db_path = args.out / 'production-audit.sqlite'
    conn = sqlite3.connect(db_path)
    conn.executescript('''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE;
        PRAGMA cache_size=-65536;
        DROP TABLE IF EXISTS observations;
        CREATE TABLE observations(permit TEXT, api TEXT, pool TEXT, pool_name TEXT, month INTEGER,
          oil REAL, quality TEXT, matched INTEGER, source INTEGER, line INTEGER, row_hash BLOB);
    ''')
    source_audits = []
    all_api_by_permit = collections.defaultdict(set)
    matched_pairs = set()
    issue_examples = collections.defaultdict(list)
    all_start = time.time()
    for source_id, path in enumerate(source_paths):
        audit = {'name': path.name, 'path': str(path), 'bytes': path.stat().st_size, 'rows': 0, 'months': collections.Counter(), 'oilQuality': collections.Counter(), 'matching': collections.Counter()}
        batch = []
        file_permits, matched_permits = set(), set()
        print(f'Reading {path.name}', flush=True)
        iterator = rows_csv(path) if path.suffix.lower() == '.csv' else rows_xlsx(path)
        for line, raw, permit_raw, api_raw, pool_raw, pool_name_raw, date_raw, oil_raw in iterator:
            audit['rows'] += 1
            permit, api = identifier(permit_raw), identifier(api_raw)
            period = month(date_raw)
            pool_name = str(pool_name_raw or '').strip().upper()
            pool_number = identifier(pool_raw)
            pool = 'number:' + pool_number if pool_number else 'name:' + pool_name
            oil, quality = oil_value(oil_raw)
            audit['oilQuality'][quality] += 1
            file_permits.add(permit)
            all_api_by_permit[permit].add(api)
            if not period or not permit or not api:
                audit['matching']['invalid_identifiers_or_month'] += 1
                if len(issue_examples['invalid_identifiers_or_month']) < 12:
                    issue_examples['invalid_identifiers_or_month'].append({'source': path.name, 'line': line, 'permit': permit, 'api': api, 'date': str(date_raw), 'pool': pool_name})
                continue
            if not pool_name and not pool_number:
                # Retain a bad pool contribution so another valid pool cannot
                # turn an incomplete well-month into a misleading partial sum.
                pool = 'missing-pool-identity'
                oil, quality = None, 'missing_pool_identity'
            audit['months'][str(period)] += 1
            expected = lookup.get(permit)
            if expected == api:
                match = 'exact_permit_api'
            elif expected and len(api) == 10 and expected.endswith('0000') and expected[:10] == api and len(base_permits[api]) == 1:
                match = 'unique_10_digit_api_base_same_permit'
            elif expected:
                match = 'permit_api_mismatch'
            elif permit in permit_apis:
                match = 'ambiguous_manifest_permit'
            else:
                match = 'permit_not_in_viewer'
            matched = int(match in ('exact_permit_api', 'unique_10_digit_api_base_same_permit'))
            audit['matching'][match] += 1
            if matched:
                matched_pairs.add((permit, expected))
                matched_permits.add(permit)
            elif match == 'permit_api_mismatch' and len(issue_examples[match]) < 12:
                issue_examples[match].append({'source': path.name, 'line': line, 'permit': permit, 'sourceAPI': api, 'viewerAPI': expected})
            fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str, separators=(',', ':')).encode()).digest()
            batch.append((permit, api, pool, pool_name, period, oil, quality, matched, source_id, line, fingerprint))
            if len(batch) >= 20000:
                conn.executemany('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?)', batch)
                conn.commit()
                batch.clear()
            if audit['rows'] % 500000 == 0:
                print(json.dumps({'source': path.name, 'rows': audit['rows'], 'matchedPermitsSoFar': len(matched_permits), 'firstMonth': min(audit['months']), 'lastMonth': max(audit['months']), 'elapsedSeconds': round(time.time()-all_start)}), flush=True)
        if batch:
            conn.executemany('INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,?,?,?)', batch)
            conn.commit()
        audit['uniquePermits'] = len(file_permits)
        audit['matchedPermits'] = len(matched_permits)
        audit['months'] = dict(sorted(audit['months'].items()))
        source_audits.append(audit)
        print(json.dumps({k:v for k,v in audit.items() if k != 'months'}), flush=True)
        (args.out / 'source-audit-progress.json').write_text(json.dumps(source_audits, indent=2))
    # Reconcile a named spreadsheet pool with its uniquely identified CSV pool
    # in the same well-month before comparing overlapping exports.
    conn.execute('CREATE INDEX pool_name_lookup ON observations(permit,month,pool_name)')
    conn.executescript('''
        CREATE TEMP TABLE pool_alias AS
        SELECT permit,month,pool_name,MIN(pool) canonical,COUNT(DISTINCT pool) n
        FROM observations WHERE pool LIKE 'number:%' AND pool_name!=''
        GROUP BY permit,month,pool_name;
        CREATE INDEX pool_alias_key ON pool_alias(permit,month,pool_name);
        UPDATE observations AS o SET pool=(SELECT a.canonical FROM pool_alias a
          WHERE a.permit=o.permit AND a.month=o.month AND a.pool_name=o.pool_name AND a.n=1)
        WHERE o.pool LIKE 'name:%' AND EXISTS(SELECT 1 FROM pool_alias a
          WHERE a.permit=o.permit AND a.month=o.month AND a.pool_name=o.pool_name AND a.n=1);
        UPDATE observations AS o SET quality='ambiguous_pool_identity',oil=NULL
        WHERE o.pool LIKE 'name:%' AND EXISTS(SELECT 1 FROM pool_alias a
          WHERE a.permit=o.permit AND a.month=o.month AND a.pool_name=o.pool_name AND a.n>1);
    ''')
    print('Indexing and auditing duplicates', flush=True)
    conn.execute('CREATE INDEX observation_pool_key ON observations(permit,month,pool)')
    conn.execute('CREATE INDEX observation_matched ON observations(matched,permit,month,pool)')
    conn.commit()
    duplicate_metrics = conn.execute('''SELECT COUNT(*), COALESCE(SUM(n-1),0), COALESCE(SUM(n-hashes),0),
        COALESCE(SUM(CASE WHEN hashes>1 THEN 1 ELSE 0 END),0),
        COALESCE(SUM(CASE WHEN oils>1 THEN 1 ELSE 0 END),0)
        FROM (SELECT COUNT(*) n, COUNT(DISTINCT row_hash) hashes,
        COUNT(DISTINCT CASE WHEN quality='valid' THEN oil END) oils
        FROM observations GROUP BY permit,month,pool HAVING COUNT(*)>1)''').fetchone()
    pool_name_aliases = conn.execute('''SELECT COUNT(*) FROM (SELECT permit,month,pool_name
        FROM observations GROUP BY permit,month,pool_name HAVING COUNT(DISTINCT pool)>1)''').fetchone()[0]
    conflicting_examples = [dict(zip(['permit','month','pool','rows','distinctValidOil','minOil','maxOil'], row)) for row in conn.execute('''SELECT permit,month,pool,COUNT(*),COUNT(DISTINCT oil),MIN(oil),MAX(oil)
        FROM observations GROUP BY permit,month,pool HAVING COUNT(DISTINCT oil)>1 LIMIT 12''')]
    matched_wells = sorted(matched_pairs, key=lambda w:(int(w[0]),w[1]))
    well_indices = {p:i for i,(p,a) in enumerate(matched_wells)}
    available_months = [r[0] for r in conn.execute('SELECT DISTINCT month FROM observations WHERE matched=1 ORDER BY month')]
    if not matched_wells or not available_months:
        conn.close()
        raise SystemExit('No production records match both file number and API in the survey manifest.')
    modern_months = sorted({int(p) for a in source_audits for p in a['months'] if int(p)>=200001})
    last_month = max(modern_months, default=max(available_months))
    months = [p for p in available_months if p < 200001]
    first_modern = min(modern_months, default=last_month+1)
    yy, mm = first_modern//100, first_modern%100
    while modern_months and yy*100+mm <= last_month:
        months.append(yy*100+mm)
        yy, mm = (yy+1, 1) if mm == 12 else (yy, mm+1)
    month_indices = {m:i for i,m in enumerate(months)}
    values = array.array('f', [float('nan')]) * (len(months)*len(matched_wells))
    summaries = {m:{'month': f'{m//100:04d}-{m%100:02d}', 'totalOilBbl':0.0, 'reportedWellCount':0, 'positiveWellCount':0, 'zeroWellCount':0, 'invalidWellCount':0} for m in months}
    exclusions = collections.Counter()
    matched_pool_count = 0
    # Grouping ignores source/API formatting only after the pair was verified.
    pool_rows = conn.execute('''SELECT permit,month,pool,COUNT(*),COUNT(DISTINCT oil),MIN(oil),
        SUM(CASE WHEN quality!='valid' THEN 1 ELSE 0 END)
        FROM observations WHERE matched=1 GROUP BY permit,month,pool ORDER BY permit,month,pool''')
    active_key, total, invalid = None, 0.0, False
    def flush(key, total, invalid):
        if key is None:
            return
        permit, period = key
        if period not in month_indices:
            return
        summary = summaries[period]
        if invalid:
            summary['invalidWellCount'] += 1
            return
        values[month_indices[period]*len(matched_wells)+well_indices[permit]] = total
        summary['totalOilBbl'] += total
        summary['reportedWellCount'] += 1
        summary['positiveWellCount' if total>0 else 'zeroWellCount'] += 1
    for permit, period, pool, count, distinct, minimum, bad in pool_rows:
        key = permit, period
        if key != active_key:
            flush(active_key, total, invalid)
            active_key, total, invalid = key, 0.0, False
        matched_pool_count += 1
        if bad or distinct != 1:
            invalid = True
            exclusions['poolWithInvalidOil' if bad else 'poolWithConflictingOil'] += 1
        else:
            total += minimum
            exclusions['collapsedSameOilAdditionalRows'] += count-1
    flush(active_key, total, invalid)
    if sys.byteorder != 'little':
        values.byteswap()
    with (args.out/'oil.bin').open('wb') as stream:
        values.tofile(stream)
    api_inconsistent = {p:sorted(a) for p,a in all_api_by_permit.items() if len(a)>1}
    audit = {
        'sources': source_audits,
        'manifestBranches': len(manifest['wells']), 'manifestUniqueWells':len(manifest_pairs),
        'manifestPermitsWithMultipleAPIs':sum(len(a)>1 for a in permit_apis.values()),
        'manifestAPIsWithMultiplePermits':sum(len(a)>1 for a in api_permits.values()),
        'matchedUniqueWells':len(matched_wells), 'unmatchedViewerWells':len(manifest_pairs)-len(matched_wells),
        'sourcePermitsWithMultipleAPIs':len(api_inconsistent),
        'sourcePermitsWithMultipleAPIExamples':dict(list(api_inconsistent.items())[:12]),
        'duplicates':dict(zip(['duplicatePoolMonthKeys','additionalRowsAtDuplicateKeys','identicalFullRowAdditionalCopies','duplicateKeysWithDifferentFullRows','keysWithConflictingNonnegativeOil'],duplicate_metrics)),
        'wellMonthPoolNamesWithMultiplePoolIDs':pool_name_aliases,
        'conflictingOilExamples':conflicting_examples,
        'matchedPoolMonthKeys':matched_pool_count,
        'matchedAggregation':dict(exclusions),
        'issueExamples':dict(issue_examples),
    }
    historical_count = conn.execute('SELECT COUNT(DISTINCT permit) FROM observations WHERE matched=1 AND month<200001').fetchone()[0]
    modern_count = conn.execute('SELECT COUNT(DISTINCT permit) FROM observations WHERE matched=1 AND month>=200001').fetchone()[0]
    coverage = {
        'modern': ({'firstMonth':f'{first_modern//100:04d}-{first_modern%100:02d}','lastMonth':f'{last_month//100:04d}-{last_month%100:02d}','matchedWellCount':modern_count} if modern_months else None),
        'historical': ({'firstMonth':f'{months[0]//100:04d}-{months[0]%100:02d}','lastMonth':f'{max(m for m in months if m<200001)//100:04d}-{max(m for m in months if m<200001)%100:02d}','matchedWellCount':historical_count} if historical_count else None),
        'omittedSources': [],
        'gaps': [],
    }
    metadata = {
        'version':1, 'title':'Reported monthly oil production', 'units':'bbl',
        'valueKind':'Monthly oil / condensate reported in source exports',
        'valuesFile':'oil.bin', 'encoding':{'type':'float32','byteOrder':'little','layout':'month-major','missing':'NaN','index':'monthIndex * wellCount + wellIndex'},
        'months':[f'{m//100:04d}-{m%100:02d}' for m in months],
        'wells':[{'permit':p,'api':a} for p,a in matched_wells],
        'wellCount':len(matched_wells), 'monthCount':len(months),
        'coverage':coverage,
        'displayNote': ('Monthly oil barrels across distinct reported pools. Separate playback periods preserve gaps in supplied coverage. '
            'Production belongs to the whole well. Current survey geometry does not establish when a branch was drilled.'),
        'monthlySummary':[summaries[m] for m in months],
        'notes':[
            'Monthly reported oil barrels; a zero is a reported zero and NaN means no usable report.',
            'Joined using File No and API; ten-digit APIs can match only the same permit with a unique fourteen-digit API ending in 0000.',
            'CSV pool identity uses PoolNo. Spreadsheet pool names use the matching CSV identifier only when unique within the same well-month. Ambiguous overlaps invalidate that well-month. Distinct pools are added once.',
            'Repeated records with identical nonnegative oil collapse to one pool contribution, even if other attributes differ.',
            'Any conflicting, negative, malformed, or missing pool oil makes the entire well-month missing; no partial pool totals.',
            'No months are interpolated. Modern coverage uses a continuous calendar between its first and last supplied months; older matched months are also retained.',
            'Totals cover matched viewer wells only. Separate well branches share the same well production; do not sum branches.',
            'Older well history does not establish that a currently displayed horizontal branch existed during those years.',
        ],
        'auditFile':'production-audit.json', 'audit':audit,
    }
    (args.out/'production-audit.json').write_text(json.dumps(audit,indent=2))
    (args.out/'production.json').write_text(json.dumps(metadata,separators=(',',':')))
    conn.close()
    print(json.dumps({'complete':True,'seconds':round(time.time()-all_start),'wellCount':len(matched_wells),'monthCount':len(months),'firstMonth':metadata['months'][0],'lastMonth':metadata['months'][-1],'binaryBytes':(args.out/'oil.bin').stat().st_size,'duplicates':audit['duplicates'],'exclusions':dict(exclusions)}),flush=True)

if __name__ == '__main__':
    main()
