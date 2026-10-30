"""Production already taken from part of an overlapping spacing unit before it was created.

An overlapping unit (say a 2560 over two 1280s) pools every interest in its land and
shares its wells' production by acreage. If one underlying unit had already produced
from its own wells and another had not, the overlap pools acreage that is partly
drained with acreage that is not. For every overlapping unit this measures:

- the underlying units it covers, chosen so they do not double-cover the same land;
- each one's Bakken-pool oil and gas (BOE, 6 mcf = 1 bbl) from wells spudded before the
  overlap's first dated order, against its share of the overlap's area;
- imbalance: half the summed gap between production share and area share (0 even, 1 all
  from one side); one-sided when some underlying unit had produced nothing;
- wells spudded after that date: line wells crossing underlying units (the overlap's own),
  and wells inside one underlying unit; production to the latest month.

Wells are placed by surveyed lateral share (dsu-well-membership.json); spud dates come
from the NDIC Well Index; production from the NDIC monthly well reports.
Requires numpy and shapely.
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime
import glob
import hashlib
import json
import pathlib
import time

import numpy as np
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from prepare_dsu_headroom import parse_spud, permit_key, read_well_index, county_lookup

BAKKEN_POOLS = {'BAKKEN', 'SANISH', 'THREE FORKS'}
MCF_PER_BOE = 6.0
INSIDE = 0.90          # an underlying unit lies at least this share inside the overlap
NO_DOUBLE_COVER = 0.10 # an underlying unit may share at most this share with ones already chosen
SINGLE_UNIT = 0.80     # a later well with this share of its lateral in one underlying unit is that unit's own well
MIN_ACRES = 1500


def load_production(paths):
    """permit -> {month: [oil, gas]} for Bakken-pool rows, summed across report lines."""
    out = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0]))
    months = set()
    for path in paths:
        with open(path, newline='', encoding='utf-8', errors='replace') as handle:
            for r in csv.DictReader(handle):
                if r['Pool Name'].strip().upper() not in BAKKEN_POOLS:
                    continue
                month = r['RPT_DATE'][:7]
                cell = out[permit_key(r['File No'])][month]
                cell[0] += float(r['BBLS_OIL_COND'] or 0); cell[1] += float(r['MCF_GAS'] or 0)
                months.add(month)
    return out, sorted(months)


def choose_parts(overlap, candidates, area):
    """Underlying units inside the overlap that do not double-cover land: largest first."""
    chosen, union = [], None
    for unit, geom in sorted(candidates, key=lambda c: -area(c[1])):
        if area(shapely.intersection(geom, overlap)) < INSIDE * area(geom):
            continue
        if union is not None and area(shapely.intersection(geom, union)) > NO_DOUBLE_COVER * area(geom):
            continue
        chosen.append((unit, geom)); union = geom if union is None else shapely.union(union, geom)
    return chosen


def imbalance(prod_shares, area_shares):
    """Half the summed gap between each part's share of earlier production and its share of area."""
    return 0.5 * sum(abs(p - a) for p, a in zip(prod_shares, area_shares))


def cumulative(production, permits, before=None, since=None):
    """Summed [oil, gas] for permits over months < before (and >= since)."""
    oil = gas = 0.0
    for p in permits:
        for month, (o, g) in production.get(p, {}).items():
            if (before is None or month < before) and (since is None or month >= since):
                oil += o; gas += g
    return oil, gas


def boe(oil, gas):
    return oil + gas / MCF_PER_BOE


def first_order(entry):
    rows = [h for h in (entry or {}).get('footprints', [{}])[0].get('history', []) if h.get('date')]
    if not rows:
        return None
    first = min(rows, key=lambda h: (h['date'], int(h['order']) if str(h['order']).isdigit() else 0))
    return {'date': first['date'], 'order': first['order'], 'event': first['event']}


def build(dsu_path, orders_path, membership_path, well_index_path, production_glob, output_path):
    started = time.perf_counter()
    read = lambda p: json.loads(pathlib.Path(p).read_text(encoding='utf-8'))
    features = read(dsu_path)['features']
    orders = read(orders_path)['units']
    membership = read(membership_path)['units']
    index_rows = read_well_index(well_index_path)
    spud = {permit_key(r['FileNo']): parse_spud(r.get('SpudDate')) for r in index_rows}
    county_of = county_lookup(index_rows)
    paths = sorted(glob.glob(production_glob))
    production, months = load_production(paths)
    ids = [f['properties']['id'] for f in features]
    geoms = [shapely.make_valid(shape(f['geometry'])) for f in features]
    acres = {f['properties']['id']: f['properties'].get('acres') or 0 for f in features}
    lat0 = np.mean([g.centroid.y for g in geoms[:200]])
    scale = np.cos(np.radians(lat0))
    area = lambda g: float(shapely.area(g)) * scale
    tree = STRtree(geoms)
    by_permit = collections.defaultdict(dict)   # permit -> {unit: fraction of lateral inside}
    for unit, rows in membership.items():
        for r in rows:
            by_permit[r['permit']][unit] = r['fraction']
    counters = collections.Counter(); rows_out = []
    for i, unit in enumerate(ids):
        if acres[unit] < MIN_ACRES:
            continue
        cands = [(ids[j], geoms[j]) for j in tree.query(geoms[i], predicate='intersects') if j != i and acres[ids[j]] < acres[unit]]
        parts = choose_parts(geoms[i], cands, area)
        if len(parts) < 2:
            continue
        counters['overlapping_units'] += 1
        start = first_order(orders.get(unit))
        if not start:
            counters['no_dated_order'] += 1
            continue
        date = start['date']; month = date[:7]
        part_ids = [p for p, _ in parts]
        total_area = sum(area(g) for _, g in parts)
        area_share = [area(g) / total_area for _, g in parts]
        # Wells by side: each surveyed well goes to the underlying unit holding most of its lateral.
        wells = {p: set() for p in part_ids}
        line_wells = set()
        nearby = {r['permit'] for u in [unit, *part_ids] for r in membership.get(u, [])}
        for permit in nearby:
            shares = by_permit[permit]
            inside = {p: shares.get(p, 0.0) for p in part_ids}
            best = max(inside, key=inside.get)
            if inside[best] <= 0 and shares.get(unit, 0.0) <= 0:
                continue
            spudded = spud.get(permit)
            if spudded and spudded >= date and shares.get(unit, 0.0) >= 0.5 and inside[best] < SINGLE_UNIT:
                line_wells.add(permit)
            elif inside[best] >= 0.5:
                wells[best].add(permit)
        sides = []
        for (p, _), share in zip(parts, area_share):
            before = {w for w in wells[p] if spud.get(w) and spud[w] < date}
            after = wells[p] - before
            oil, gas = cumulative(production, before, before=month)
            sides.append({'unit': p, 'acres': acres[p], 'areaShare': round(share, 4), 'wellsBefore': len(before),
                          'wellsAfter': len(after), 'priorOil': round(oil), 'priorGas': round(gas), 'priorBoe': round(boe(oil, gas)),
                          'firstSpud': min((spud[w] for w in wells[p] if spud.get(w)), default=None)})
        prior = sum(s['priorBoe'] for s in sides)
        dry = [s for s in sides if s['priorBoe'] == 0 and s['wellsBefore'] == 0]
        line_oil, line_gas = cumulative(production, line_wells, since=month)
        line_boe = boe(line_oil, line_gas)
        score = imbalance([s['priorBoe'] / prior for s in sides], area_share) if prior > 0 else 0.0
        dry_share = sum(s['areaShare'] for s in dry)
        lead = (orders.get(unit) or {}).get('footprints', [{}])[0]
        rows_out.append({'id': unit, 'acres': acres[unit], 'overlapDate': date, 'overlapOrder': start['order'], 'year': int(date[:4]),
                         'pool': lead.get('pool'), 'county': county_of(lead.get('land')), 'parts': len(sides),
                         # Share of the overlap's area its underlying units account for; the rest has no current DMR unit.
                         'coverage': round(min(1.0, total_area / area(geoms[i])), 3),
                         'producingParts': sum(1 for s in sides if s['priorBoe'] > 0), 'dryParts': len(dry), 'oneSided': bool(dry) and prior > 0,
                         'priorOil': sum(s['priorOil'] for s in sides), 'priorGas': sum(s['priorGas'] for s in sides), 'priorBoe': prior,
                         'imbalance': round(score, 4), 'dryAreaShare': round(dry_share, 4),
                         'lineWells': len(line_wells), 'lineBoe': round(line_boe), 'dryShareOfLineBoe': round(dry_share * line_boe),
                         'sides': sides})
        counters['dated'] += 1
        counters['one_sided'] += rows_out[-1]['oneSided']
    rows_out.sort(key=lambda r: (-r['oneSided'], -r['priorBoe']))
    one_sided = [r for r in rows_out if r['oneSided']]
    by_year = collections.defaultdict(lambda: collections.Counter())
    for r in rows_out:
        y = by_year[r['year']]
        y['overlaps'] += 1; y['oneSided'] += r['oneSided']; y['priorBoeOneSided'] += r['priorBoe'] if r['oneSided'] else 0
    summary = {**dict(counters), 'productionMonths': [months[0], months[-1]] if months else None,
               'oneSidedPriorBoe': sum(r['priorBoe'] for r in one_sided), 'oneSidedPriorOil': sum(r['priorOil'] for r in one_sided),
               'oneSidedLineBoe': sum(r['lineBoe'] for r in one_sided), 'oneSidedDryShareOfLineBoe': sum(r['dryShareOfLineBoe'] for r in one_sided),
               'medianImbalanceAll': float(np.median([r['imbalance'] for r in rows_out if r['priorBoe'] > 0])) if rows_out else None}
    result = {'version': 1, 'createdAtUTC': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'method': {'parts': f'Smaller DSUs at least {INSIDE:.0%} inside the overlap, largest first, none sharing more than {NO_DOUBLE_COVER:.0%} with those chosen.',
                         'date': 'The overlapping unit\'s first dated linked order; if an earlier order is missing, earlier production is overstated.',
                         'production': f'NDIC monthly reports, pools {sorted(BAKKEN_POOLS)}; BOE = oil + gas/{MCF_PER_BOE:.0f}.',
                         'sides': 'A well belongs to the underlying unit holding most of its surveyed lateral; earlier production counts wells spudded before the overlap date and months before it.',
                         'lineWells': f'Wells spudded on or after the overlap date with at least half their lateral in the overlap and less than {SINGLE_UNIT:.0%} in any one underlying unit.',
                         'imbalance': 'Half the summed |production share - area share| over underlying units; 0 even, 1 all from one side.',
                         'limitations': ['Production starts January 2000.', 'Only current DMR units: terminated overlapping units are absent.',
                                         'Ownership and actual pooling terms are not modelled; this measures land and production only.']},
              'sourceHashes': {pathlib.Path(p).name: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() for p in paths},
              'summary': summary, 'byYear': {str(y): dict(v) for y, v in sorted(by_year.items())}, 'overlaps': rows_out}
    pathlib.Path(output_path).write_text(json.dumps(result, separators=(',', ':')), encoding='utf-8')
    report = {**summary, 'seconds': round(time.perf_counter() - started, 1), 'top': [{k: r[k] for k in ('id', 'acres', 'overlapDate', 'priorBoe', 'imbalance', 'dryParts', 'lineBoe')} for r in one_sided[:5]]}
    print(json.dumps(report, indent=1))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dsus'); parser.add_argument('orders'); parser.add_argument('membership')
    parser.add_argument('well_index'); parser.add_argument('production_glob', help='quoted glob of NDIC monthly production CSVs')
    parser.add_argument('output')
    a = parser.parse_args(); build(a.dsus, a.orders, a.membership, a.well_index, a.production_glob, a.output)
