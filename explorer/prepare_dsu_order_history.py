"""Per-DSU NDIC order history and latest well allowance from the land index.

Replaces the unit-atlas link (prepare_dsu_orders.py) with the order queue's
land index (local_order_queue/land_index), which resolves aliquot parts,
multi-township units, pooling and zone tables. Output keeps the dsu-orders.json
schema, so the viewer card, color modes and prepare_dsu_headroom.py read it
unchanged.

Events reach a DSU when an order's unit geometry overlaps it (intersection over
union >= LINK_IOU), or when a Bakken zone table lists land containing the DSU
and the zone's unit acreage matches. A zone header without a well count (e.g.
'1280H-STANDUP') states acreage only and never sets an allowance. Allowances
are machine-extracted and not human-reviewed. Requires shapely.
"""
from __future__ import annotations
import argparse
import collections
import datetime
import hashlib
import json
import math
import pathlib
import sqlite3
import time

import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from prepare_dsu_orders import EXACT_IOU, LINK_IOU, REVIEW_IOU, compare, iou, sha_file

ZONE_CONTAINED = 0.95       # share of the DSU's area inside the zone's listed land
ZONE_ACRES_TOLERANCE = 0.15
SPACING_VERBS = {'established', 'affirmed', 'designated', 'created', 'redefined', 'amended', 'enlarged', 'reduced', 'extended'}
ENDING_VERBS = {'terminated', 'rescinded', 'vacated', 'abolished'}
# Within one order, a count stated for the unit itself outranks one read from a zone table.
PRIORITY = {'unit_clause': 3, 'density_clause': 3, 'zone_table_same_order': 2, 'zone_table': 1}


def bakken_or_unnamed(pools):
    return not pools or any('bakken' in p.lower() or 'three forks' in p.lower() or 'sanish' in p.lower() for p in pools)


def event_key(e):
    return (int(e['order']) if str(e['order']).isdigit() else 0, e['date'] or '', e['event'])


def resolve_allowance(events):
    """Latest stated allowance over a DSU's events, oldest first by order number.

    A termination after the latest count ends it. Same-order conflicts keep
    the higher-priority source; equal-priority disagreement leaves no value.
    """
    counted = [e for e in events if e['wells'] is not None and e['event'] != 'termination']
    if not counted:
        last = max(events, key=event_key)
        return {'wells': None, 'order': last['order'], 'case': last['case'], 'date': last['date'], 'qualifier': None,
                'mixed': False, 'terminated': last['event'] == 'termination', 'method': None}
    latest_order = max(event_key(e)[0] for e in counted)
    same = [e for e in counted if event_key(e)[0] == latest_order]
    top = max(PRIORITY.get(e['method'], 0) for e in same)
    values = {e['wells'] for e in same if PRIORITY.get(e['method'], 0) == top}
    chosen = next(e for e in same if PRIORITY.get(e['method'], 0) == top)
    ended = any(e['event'] == 'termination' and event_key(e)[0] > latest_order for e in events)
    return {'wells': None if len(values) > 1 or ended else chosen['wells'], 'order': chosen['order'], 'case': chosen['case'],
            'date': chosen['date'], 'qualifier': 'stated', 'mixed': len(values) > 1, 'terminated': ended, 'method': chosen['method']}


def history_rows(events):
    rows = {}
    for e in sorted(events, key=event_key):
        k = (e['order'], e['event'], e['wells'])
        row = rows.setdefault(k, {'date': e['date'], 'order': e['order'], 'case': e['case'], 'event': e['event'], 'wells': e['wells'],
                                  'qualifier': 'stated' if e['wells'] is not None else None, 'method': e['method'], 'viaOrder': None,
                                  'documentId': e['document_id'], 'clauses': []})
        if e['clause'] and e['clause'] not in row['clauses']:
            row['clauses'].append(e['clause'])
    return list(rows.values())


def orientation(geometry):
    """standup (taller than wide), laydown, or square, from plan-view bounds."""
    x0, y0, x1, y1 = geometry.bounds
    width, height = (x1 - x0) * math.cos(math.radians((y0 + y1) / 2)), y1 - y0
    return 'standup' if height > 1.3 * width else 'laydown' if width > 1.3 * height else 'square'


def zone_fits(modifiers, dsu_orientation):
    """A STANDUP or LAYDOWN zone lists the union of its units' sections, so an
    other-orientation DSU on the same land must not inherit its count."""
    stated = {m for m in modifiers if m in ('standup', 'laydown')}
    return not stated or dsu_orientation in stated


def land_of(tracts):
    """Viewer/headroom land summary: the first township's whole sections."""
    if not tracts:
        return None
    t, r = tracts[0][0], tracts[0][1]
    return {'township': t, 'township_direction': 'N', 'range': r, 'range_direction': 'W',
            'sections': sorted({x[2] for x in tracts if (x[0], x[1]) == (t, r)})}


def build(index_path, dsu_path, output_path):
    started = time.perf_counter()
    index_path, dsu_path, output_path = map(pathlib.Path, (index_path, dsu_path, output_path))
    dsus = json.loads(dsu_path.read_text(encoding='utf-8'))
    features = dsus['features']; ids = [f['properties']['id'] for f in features]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate current DSU viewer IDs')
    acres = {f['properties']['id']: f['properties'].get('acres') for f in features}
    polygons = [shapely.make_valid(shape(f['geometry'])) for f in features]
    tree = STRtree(polygons)
    con = sqlite3.connect(f'file:{index_path.resolve().as_posix()}?mode=ro', uri=True)
    docs = {d: {'order': o, 'case': c, 'date': dt, 'applicant': a} for d, o, c, dt, a in
            con.execute('select document_id, order_no, case_no, date, applicant from documents')}
    zone_counts = {}   # (document_id, pool, zone) -> wells, for 'designated ... in Zone XVIII in the Ross-Bakken Pool'
    for d, pool, zone, wells in con.execute('select document_id, pool, zone, wells from zones'):
        if pool:
            zone_counts[(d, pool.lower(), zone.upper())] = wells
    events = collections.defaultdict(list); best = {}; review = []; counters = collections.Counter()

    def add(dsu_index, e, score=None, tracts=None):
        uid = ids[dsu_index]
        events[uid].append(e)
        if score is not None and score > best.get(uid, (0, None))[0]:
            best[uid] = (score, tracts)

    rows = con.execute('''select u.document_id, u.clause, u.kind, u.verb, u.wells, u.zone, u.pools, u.tracts, g.geojson
                          from units u join unit_geometry g using(document_id, clause, unit_index)
                          where g.missing_tracts = 0''')
    for doc, clause, kind, verb, wells, zone, pools, tracts, geojson in rows:
        pools = json.loads(pools)
        if kind == 'limits' or not bakken_or_unnamed(pools) or doc not in docs:
            continue
        if kind == 'other' and wells is None:
            continue
        if kind == 'unit' and verb in ENDING_VERBS:
            event, wells, method = 'termination', None, None
        elif kind == 'pooling':
            event, wells, method = 'pooling', None, None
        elif kind == 'unit':
            event, method = 'spacing', 'unit_clause'
            if wells is None and zone and len(pools) == 1:
                wells = zone_counts.get((doc, pools[0].lower(), zone.upper()))
                method = 'zone_table_same_order' if wells is not None else 'unit_clause'
        else:
            event, method = 'density', 'density_clause'
        geom = shapely.make_valid(shape(json.loads(geojson)))
        candidates = [(iou(geom, polygons[j]), j) for j in tree.query(geom, predicate='intersects')]
        linked = [(s, j) for s, j in candidates if s >= LINK_IOU]
        if not linked:
            near = max(candidates, default=(0, None))
            if near[0] >= REVIEW_IOU and kind == 'unit':
                review.append({'documentId': doc, 'order': docs[doc]['order'], 'clause': clause, 'bestDsu': ids[near[1]], 'iou': round(near[0], 4)})
            counters['unitsWithoutDsu_' + kind] += 1
            continue
        d = docs[doc]
        for s, j in linked:
            add(j, {'document_id': doc, 'order': d['order'], 'case': d['case'], 'date': d['date'], 'event': event, 'wells': wells,
                     'method': method, 'clause': clause, 'pool': pools[0] if len(pools) == 1 else None, 'zone': zone}, s, json.loads(tracts))
        counters['linkedUnits_' + kind] += 1

    orientations = [orientation(p) for p in polygons]
    for doc, pool, zone, wells, zacres, modifiers, geojson in con.execute('''select z.document_id, z.pool, z.zone, z.wells, z.acres, z.modifiers, g.geojson
            from zones z join zone_geometry g on g.document_id = z.document_id and g.ordinal = z.ordinal
            where z.kind = 'H' and z.pool is not null and g.missing_tracts = 0'''):
        if not bakken_or_unnamed([pool]) or doc not in docs:
            continue
        geom = shapely.make_valid(shape(json.loads(geojson)))
        modifiers = json.loads(modifiers)
        d = docs[doc]
        for j in tree.query(geom, predicate='intersects'):
            a = acres.get(ids[j])
            if not a or abs(a - zacres) > ZONE_ACRES_TOLERANCE * zacres:
                continue
            if not zone_fits(modifiers, orientations[j]):
                counters['zoneOrientationMismatches'] += 1
                continue
            if shapely.area(shapely.intersection(polygons[j], geom)) < ZONE_CONTAINED * polygons[j].area:
                continue
            add(j, {'document_id': doc, 'order': d['order'], 'case': d['case'], 'date': d['date'], 'event': 'zone', 'wells': wells,
                     'method': 'zone_table', 'clause': None, 'pool': pool, 'zone': zone})
            counters['zoneMemberships'] += 1
            counters['zoneMembershipsWithCount'] += wells is not None
    con.close()

    units = {}; comparison = collections.Counter()
    by_id = {f['properties']['id']: f['properties'] for f in features}
    for uid, evs in events.items():
        evs.sort(key=event_key)
        allowance = resolve_allowance(evs)
        last = evs[-1]; score, tracts = best.get(uid, (None, None))
        latest_pool = next((e['pool'] for e in reversed(evs) if e['pool']), None)
        latest_zone = next((e['zone'] for e in reversed(evs) if e['zone']), None)
        units[uid] = {'allowance': {**allowance, 'footprints': 1},
                      'footprints': [{'footprint': uid, 'pool': latest_pool, 'zone': f'Zone {latest_zone}' if latest_zone else None,
                                      'acres': acres.get(uid), 'land': land_of(tracts), 'iou': round(score, 4) if score else None,
                                      'match': 'exact' if score and score >= EXACT_IOU else 'close' if score else 'zone table',
                                      'latest': {'date': last['date'], 'order': last['order'], 'case': last['case'], 'wells': allowance['wells'],
                                                 'qualifier': allowance['qualifier'], 'event': last['event']},
                                      'history': history_rows(evs)}]}
        comparison[compare(units[uid]['allowance'], by_id[uid].get('inventory'))] += 1
    summary = {'dsuFeatures': len(features), 'dsusLinked': len(units),
               'dsusWithAllowance': sum(u['allowance']['wells'] is not None for u in units.values()),
               'dsusWithMixedAllowance': sum(u['allowance']['mixed'] for u in units.values()),
               'dsusTerminated': sum(u['allowance']['terminated'] for u in units.values()),
               'allowanceSource': dict(collections.Counter(u['allowance']['method'] for u in units.values() if u['allowance']['wells'] is not None)),
               'events': sum(map(len, events.values())), 'allowanceVsSavedModel': dict(comparison), 'counts': dict(counters),
               'footprints': len(units)}
    ids_hash = hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()
    result = {'version': 1, 'createdAtUTC': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'atlas': {'built': datetime.datetime.fromtimestamp(index_path.stat().st_mtime, datetime.timezone.utc).isoformat(),
                        'source': 'land index', 'fileSha256': sha_file(index_path)},
              'dsu': {'featureCount': len(features), 'idsSha256': ids_hash, 'fileSha256': sha_file(dsu_path),
                      'retrievedAtUTC': dsus['metadata'].get('retrievedAtUTC')},
              'method': {'purpose': 'Attach NDIC order history and stated well allowances to source DMR DSU footprints.',
                         'source': 'local_order_queue land index: operative clauses parsed into PLSS tracts (aliquot parts, multi-township units) with BLM CadNSDI section geometry.',
                         'match': f'Unit geometry to DSU intersection over union >= {LINK_IOU}; zone tables when >= {ZONE_CONTAINED:.0%} of the DSU lies in the listed land and acreage is within {ZONE_ACRES_TOLERANCE:.0%}.',
                         'latest': 'Events ordered by order number. The latest order stating a count sets the allowance; a later termination ends it. Unit clauses outrank zone tables within one order.',
                         'zones': 'A zone header without a count (e.g. 1280H-STANDUP) states acreage only and never sets an allowance.',
                         'limitations': ['Allowances are machine-extracted and not human-reviewed.',
                                         'A stated allowance is not proof that the order governs today, nor a drillable-location estimate.',
                                         'Orders not yet extracted (pending in the queue) are missing.']},
              'summary': summary, 'applicants': {d['order']: d['applicant'] for d in docs.values() if d['applicant'] and d['order']},
              'units': dict(sorted(units.items())), 'review': sorted(review, key=lambda r: -r['iou'])}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    report = {**summary, 'reviewCount': len(review), 'outputBytes': output_path.stat().st_size, 'totalSeconds': round(time.perf_counter() - started, 1)}
    output_path.with_suffix('.audit.json').write_text(json.dumps({**report, 'atlas': result['atlas'], 'dsu': result['dsu']}, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('index', help='local_order_queue/land_index/data/land_index.sqlite3')
    parser.add_argument('dsus', help='viewer/data/dsu/drilling-spacing-units.geojson')
    parser.add_argument('output', help='viewer/data/dsu/dsu-orders.json')
    args = parser.parse_args(); build(args.index, args.dsus, args.output)
