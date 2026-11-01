"""Did increased density pay off? Infill wells against the wells already in each unit.

For every dated order that raised a spacing unit's well allowance, wells assigned to the
unit (largest share of lateral) split into parents, spudded before the order, and
children, spudded after it and before the next increase.

Completion design improved over time, so raw production favours later wells. Each well
is scored against its vintage: first-12-month oil per 1,000 ft of lateral, divided by the
median for first-in-unit wells (new wells in undrilled rock) in the same county that began
producing about the same year. 1.0 is what a new well in fresh rock made then.
An event's payoff ratio is the children's median score over the parents'. Below 1 means
the infill wells did worse, relative to fresh-rock wells of their vintage, than the parents.

Inputs: dsu-orders.json, dsu-well-membership.json, the NDIC Well Index, NDIC monthly well
production (Bakken pool). Requires numpy.
"""
from __future__ import annotations
import argparse
import collections
import datetime
import glob
import json
import pathlib
import re
import statistics
import time

from prepare_dsu_headroom import parse_spud, permit_key, read_well_index, unit_timeline, assign_exclusive, MIN_INSIDE_FT
from prepare_overlap_depletion import load_production, non_bakken_wells

FIRST_MONTHS = 12
MIN_PEERS = 10
MIN_FIRST = 8


def first_year_oil(months):
    """(first producing month, oil in the first FIRST_MONTHS calendar months) or None if not enough history."""
    producing = sorted(m for m, (oil, _) in months.items() if oil > 0)
    if not producing:
        return None
    start = producing[0]
    y, m = int(start[:4]), int(start[5:7])
    end_index = y * 12 + m - 1 + FIRST_MONTHS
    window = [mo for mo in months if start <= mo and int(mo[:4]) * 12 + int(mo[5:7]) - 1 < end_index]
    return start, sum(months[mo][0] for mo in window)


def increases(timeline):
    """Dated orders that raised the allowance: (date, before, after), in order."""
    out, prev = [], None
    for date, allowed in timeline['steps']:
        if allowed is not None and prev is not None and allowed > prev:
            out.append((date, prev, allowed))
        if allowed is not None:
            prev = allowed
    return out


def bucket(n):
    return '1-4' if n <= 4 else '5-8' if n <= 8 else '9-12' if n <= 12 else '13+'


def build(dsu_path, orders_path, membership_path, well_index_path, production_glob, output_path, last_month=None):
    started = time.perf_counter()
    read = lambda p: json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    acres = {f['properties']['id']: f['properties'].get('acres') for f in read(dsu_path)['features']}
    orders = read(orders_path)['units']
    membership = read(membership_path)['units']
    index_rows = read_well_index(well_index_path)
    index = {permit_key(r['FileNo']): r for r in index_rows}
    other = collections.Counter()
    production, months = load_production(sorted(glob.glob(production_glob)), other)
    skip = non_bakken_wells(index_rows, production, other)
    last_month = last_month or (months[-1] if months else None)
    stats = collections.Counter({'non_bakken_wells': len(skip)})

    # Wells per unit: each well to the unit holding most of its lateral (geometry only).
    candidates = collections.defaultdict(dict); lateral = {}
    for unit, rows in membership.items():
        for r in rows:
            if r['insideFt'] >= MIN_INSIDE_FT and r['permit'] not in skip:
                candidates[r['permit']][unit] = r; lateral[r['permit']] = r['totalFt']
    unit_wells = collections.defaultdict(list)
    for permit, cands in candidates.items():
        unit_wells[assign_exclusive(cands, acres)].append(permit)

    # Vintage-adjusted score per well.
    raw = {}
    for permit, ft in lateral.items():
        fy = first_year_oil(production.get(permit, {}))
        if not fy or ft <= 0:
            continue
        start, oil = fy
        # Need a full first year inside the data.
        y, m = int(start[:4]), int(start[5:7])
        if last_month and (y * 12 + m - 1 + FIRST_MONTHS - 1) > int(last_month[:4]) * 12 + int(last_month[5:7]) - 1:
            stats['wells_too_new'] += 1
            continue
        county = re.sub(r'\bMc([a-z])', lambda m: 'Mc' + m.group(1).upper(), ((index.get(permit) or {}).get('CountyName') or '').strip().title())
        raw[permit] = {'start': start, 'year': int(start[:4]), 'county': county, 'perKft': oil / (ft / 1000.0), 'oil12': oil, 'lateralFt': ft}
    # Two baselines. All peers: every well of that county and year. First-in-unit: only wells
    # that were the first spudded in their unit, i.e. new wells in undrilled rock. After 2012
    # most wells are infill, so the all-peers median is mostly infill wells; the first-in-unit
    # baseline is the primary score, pooled over a year either side to reach MIN_FIRST wells.
    first_in_unit = set()
    for unit, permits in unit_wells.items():
        dated = sorted(x for x in ((parse_spud((index.get(p) or {}).get('SpudDate')), p) for p in permits) if x[0])
        if dated:
            first_in_unit.add(dated[0][1])
    peers = collections.defaultdict(list); firsts = collections.defaultdict(list)
    for permit, w in raw.items():
        peers[(w['county'], w['year'])].append(w['perKft'])
        if permit in first_in_unit:
            firsts[(w['county'], w['year'])].append(w['perKft'])
    medians = {k: statistics.median(v) for k, v in peers.items() if len(v) >= MIN_PEERS}

    def first_baseline(county, year):
        for span in (0, 1, 2):
            pool = [v for y in range(year - span, year + span + 1) for v in firsts.get((county, y), [])]
            if len(pool) >= MIN_FIRST:
                return statistics.median(pool)
        return None
    first_medians = {k: first_baseline(*k) for k in peers}
    score, score_all = {}, {}
    for permit, w in raw.items():
        key = (w['county'], w['year'])
        if first_medians.get(key):
            score[permit] = w['perKft'] / first_medians[key]
        if medians.get(key):
            score_all[permit] = w['perKft'] / medians[key]
    stats['wells_scored'] = len(score)
    stats['first_in_unit_wells'] = len(first_in_unit & set(raw))

    events = []
    for unit, entry in orders.items():
        timeline = unit_timeline(entry)
        ups = increases(timeline)
        if not ups:
            continue
        wells = [(parse_spud((index.get(p) or {}).get('SpudDate')), p) for p in unit_wells.get(unit, [])]
        wells = [(d, p) for d, p in wells if d]
        pool = (entry.get('footprints') or [{}])[0].get('pool')
        for i, (date, before, after) in enumerate(ups):
            nxt = ups[i + 1][0] if i + 1 < len(ups) else '9999'
            parents = [p for d, p in wells if d < date and p in score]
            children = [p for d, p in wells if date <= d < nxt and p in score]
            stats['increases'] += 1
            if not parents or not children:
                stats['increases_without_both'] += 1
                continue
            ps = statistics.median(score[p] for p in parents); cs = statistics.median(score[p] for p in children)
            pa = [score_all[p] for p in parents if p in score_all]; ca = [score_all[p] for p in children if p in score_all]
            ratio_all = round(statistics.median(ca) / statistics.median(pa), 3) if pa and ca and statistics.median(pa) > 0 else None
            county = statistics.mode([raw[p]['county'] for p in parents + children])
            operator = statistics.mode([((index.get(p) or {}).get('CurrentOperator') or 'Unknown').strip().upper() for p in children])
            events.append({'unit': unit, 'date': date, 'year': int(date[:4]), 'from': before, 'to': after, 'bucket': bucket(after),
                           'pool': pool, 'county': county, 'operator': operator, 'parents': len(parents), 'children': len(children),
                           'parentScore': round(ps, 3), 'childScore': round(cs, 3), 'ratio': round(cs / ps, 3) if ps > 0 else None,
                           'ratioAllPeers': ratio_all,
                           'parentOil12': round(statistics.median(raw[p]['oil12'] for p in parents)),
                           'childOil12': round(statistics.median(raw[p]['oil12'] for p in children))})
    events = [e for e in events if e['ratio'] is not None]
    stats['events'] = len(events)

    def summarize(rows):
        r = [e['ratio'] for e in rows]
        ra = [e['ratioAllPeers'] for e in rows if e['ratioAllPeers'] is not None]
        return {'events': len(rows), 'medianRatio': round(statistics.median(r), 3) if r else None,
                'medianRatioAllPeers': round(statistics.median(ra), 3) if ra else None,
                'childVsFirstWell': round(statistics.median(e['childScore'] for e in rows), 3) if rows else None,
                'shareChildrenBetter': round(sum(x >= 1 for x in r) / len(r), 3) if r else None,
                'children': sum(e['children'] for e in rows), 'parents': sum(e['parents'] for e in rows)}

    def group(key, minimum=1):
        g = collections.defaultdict(list)
        for e in events:
            g[e[key]].append(e)
        return sorted(({'name': k, **summarize(v)} for k, v in g.items() if len(v) >= minimum and k is not None),
                      key=lambda x: (-x['events'], str(x['name'])))

    result = {'version': 1, 'createdAtUTC': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'method': {'score': f'First {FIRST_MONTHS} months of oil per 1,000 ft of lateral, over the median of first-in-unit wells (the first well spudded in their unit) in the same county and first-production year, widened by a year either side to reach {MIN_FIRST} wells. 1.0 is a typical new well in undrilled rock of its vintage.',
                         'scoreAllPeers': f'Secondary: over the median of all wells of that county and year ({MIN_PEERS}+). After 2012 most wells are infill, so this baseline understates infill effects.',
                         'wells': 'Bakken wells only: wells whose Well Index pools are all non-Bakken, or whose production is mostly from another pool, are left out.',
                         'events': 'Dated orders that raised a unit\'s stated allowance. Parents: wells assigned to the unit spudded before the order. Children: spudded after it and before the next increase.',
                         'ratio': 'Median child score over median parent score. Below 1, infill wells underperformed their vintage relative to the parents.',
                         'limitations': ['Oil only for the score; gas-weighted areas may differ.', 'Wells need a full first year of production in the data.',
                                         'Allowances are machine-extracted; a missing order can misplace the split date.',
                                         'Completion size beyond lateral length is not modelled; the vintage-and-county baseline absorbs only average design change.']},
              'summary': {**dict(stats), **summarize(events), 'productionLastMonth': last_month},
              'byBucket': sorted(group('bucket'), key=lambda x: ['1-4', '5-8', '9-12', '13+'].index(x['name'])),
              'byYear': sorted(group('year'), key=lambda x: x['name']),
              'byPool': group('pool', 5), 'byOperator': group('operator', 5), 'byCounty': group('county', 5),
              'events': sorted(events, key=lambda e: (e['date'], e['unit']))}
    pathlib.Path(output_path).write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
    print(json.dumps({**result['summary'], 'byBucket': result['byBucket'], 'seconds': round(time.perf_counter() - started, 1)}, indent=1))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dsus'); parser.add_argument('orders'); parser.add_argument('membership'); parser.add_argument('well_index')
    parser.add_argument('production_glob', help='quoted glob of NDIC monthly production CSVs'); parser.add_argument('output')
    a = parser.parse_args(); build(a.dsus, a.orders, a.membership, a.well_index, a.production_glob, a.output)
