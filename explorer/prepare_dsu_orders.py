"""Link NDIC order footprints from the local order atlas to source DMR DSUs.

Reads the unit atlas data.json (produced by the local order queue) without
modifying it. Each atlas footprint is one land description + pool with a dated
history of order events and a resolved latest allowance. Footprints are linked
to DSU polygons by plan-view intersection over union. Allowances are stated in
the order text and extracted automatically; they are not human-reviewed or
proof of current legal effect.
Requires shapely (tested with Shapely 2.0.4).
"""
from __future__ import annotations
import argparse
import collections
import datetime
import hashlib
import json
import pathlib
import time

import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

EXACT_IOU=0.95
LINK_IOU=0.80
REVIEW_IOU=0.50


def sha_file(path):
    digest=hashlib.sha256()
    with pathlib.Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def order_number(value):
    text=str(value or '')
    return int(text) if text.isdigit() else 0


def event_sort_key(record):
    """Same ordering as the atlas latest_event(): date, numeric order, record id."""
    return (record.get('date') or '',order_number(record.get('order')),record.get('id',''))


def iou(a,b):
    inter=shapely.area(shapely.intersection(a,b))
    union=shapely.area(a)+shapely.area(b)-inter
    return float(inter/union) if union>0 else 0.0


def repaired(geometry,counters,name):
    geom=shape(geometry)
    if not shapely.is_valid(geom):
        geom=shapely.make_valid(geom); counters[name]+=1
    return geom


def history(records):
    """Collapse clause-level records to one row per order event, oldest first."""
    rows={}
    for r in sorted(records,key=event_sort_key):
        key=(r.get('date'),str(r.get('order')),r.get('allowance_event'),r.get('well_count'))
        row=rows.get(key)
        if row is None:
            source=r.get('allowance_source') or {}
            row=rows[key]={'date':r.get('date'),'order':str(r.get('order')),'case':str(r.get('case') or ''),
                           'event':r.get('allowance_event'),'wells':r.get('well_count'),'qualifier':r.get('qualifier'),
                           'method':source.get('method'),'viaOrder':source.get('via_order'),
                           'documentId':r.get('document_id'),'clauses':[]}
        if r.get('clause') and r['clause'] not in row['clauses']: row['clauses'].append(r['clause'])
    return list(rows.values())


def footprints(records,counters):
    grouped=collections.defaultdict(list)
    for r in records: grouped[r['unit_key']].append(r)
    result=[]
    for key in sorted(grouped):
        events=grouped[key]; first=events[0]
        if len({json.dumps(e['geometry'],sort_keys=True) for e in events})>1:
            raise ValueError('Atlas footprint has more than one geometry: '+key)
        latest=max(events,key=event_sort_key)
        result.append({'key':key,'pool':first.get('pool'),'zone':first.get('zone'),'acres':first.get('acres'),
                       'land':first.get('land'),'geometry':repaired(first['geometry'],counters,'repairedFootprintGeometries'),
                       'latest':{'date':latest.get('date'),'order':str(latest.get('order')),'case':str(latest.get('case') or ''),
                                 'wells':latest.get('well_count'),'qualifier':latest.get('qualifier'),'event':latest.get('allowance_event')},
                       'history':history(events)})
    return result


def summarize_unit(links):
    """DSU-level allowance from its linked footprints' latest events."""
    dated=[l for l in links if l['latest']['date']]
    if not dated: return None
    latest=max(dated,key=lambda l:(l['latest']['date'],order_number(l['latest']['order'])))['latest']
    values={l['latest']['wells'] for l in links if l['latest']['wells'] is not None}
    return {'wells':latest['wells'],'order':latest['order'],'case':latest['case'],'date':latest['date'],
            'qualifier':latest['qualifier'],'mixed':len(values)>1,'footprints':len(links)}


def compare(allowance,inventory):
    if not allowance or allowance['wells'] is None: return 'no_order_allowance'
    if not inventory or not inventory.get('matched') or inventory.get('estimatedCapacity') is None: return 'no_saved_model'
    capacity=inventory['estimatedCapacity']
    if abs(allowance['wells']-capacity)<0.5: return 'order_matches_model'
    return 'order_above_model' if allowance['wells']>capacity else 'order_below_model'


def build(atlas_path,dsu_path,output_path):
    started=time.perf_counter()
    atlas_path=pathlib.Path(atlas_path); dsu_path=pathlib.Path(dsu_path); output_path=pathlib.Path(output_path)
    atlas=json.loads(atlas_path.read_text(encoding='utf-8'))
    dsus=json.loads(dsu_path.read_text(encoding='utf-8'))
    if dsus['metadata']['sourceCRS']!='EPSG:4269': raise ValueError('Requires NAD83 source DSU geometry')
    features=dsus['features']; ids=[f['properties']['id'] for f in features]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate current DSU viewer IDs')
    counters=collections.Counter()
    polygons=[repaired(f['geometry'],counters,'repairedDSUGeometries') for f in features]
    prints=footprints(atlas['records'],counters)
    # Atlas geometry is EPSG:4326 and DSUs EPSG:4269; the datum difference is
    # sub-metre here. IoU is a ratio, so degree areas compare like-for-like.
    tree=STRtree(polygons)
    units=collections.defaultdict(list); review=[]; quality=collections.Counter()
    for fp in prints:
        candidates=[(iou(fp['geometry'],polygons[j]),j) for j in tree.query(fp['geometry'],predicate='intersects')]
        candidates=[c for c in candidates if c[0]>0]
        linked=[(score,j) for score,j in candidates if score>=LINK_IOU]
        if linked:
            for score,j in linked:
                units[ids[j]].append({'footprint':fp['key'],'pool':fp['pool'],'zone':fp['zone'],'acres':fp['acres'],'land':fp['land'],
                                      'iou':round(score,4),'match':'exact' if score>=EXACT_IOU else 'close',
                                      'latest':fp['latest'],'history':fp['history']})
            quality['exact' if max(linked)[0]>=EXACT_IOU else 'close']+=1
        elif candidates and max(candidates)[0]>=REVIEW_IOU:
            score,j=max(candidates)
            review.append({'footprint':fp['key'],'pool':fp['pool'],'land':fp['land'],'bestDsu':ids[j],'iou':round(score,4),'latest':fp['latest']})
            quality['review']+=1
        else:
            quality['unmatched']+=1
    summaries={}; comparison=collections.Counter()
    by_id={f['properties']['id']:f['properties'] for f in features}
    for unit_id,links in units.items():
        links.sort(key=lambda l:(-l['iou'],l['footprint']))
        summaries[unit_id]=summarize_unit(links)
        comparison[compare(summaries[unit_id],by_id[unit_id].get('inventory'))]+=1
    summary={'footprints':len(prints),'footprintMatch':dict(quality),'dsuFeatures':len(features),
             'dsusLinked':len(units),'dsusWithAllowance':sum(1 for s in summaries.values() if s and s['wells'] is not None),
             'dsusWithMixedAllowance':sum(1 for s in summaries.values() if s and s['mixed']),
             'allowanceVsSavedModel':dict(comparison),'counts':dict(counters)}
    dsu_ids_hash=hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()
    result={'version':1,'createdAtUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'atlas':{'built':atlas['summary'].get('built'),'sourceSnapshot':atlas['summary'].get('source_snapshot',{}).get('at'),
                     'fileSha256':sha_file(atlas_path),'records':len(atlas['records'])},
            'dsu':{'featureCount':len(features),'idsSha256':dsu_ids_hash,'fileSha256':sha_file(dsu_path),
                   'retrievedAtUTC':dsus['metadata'].get('retrievedAtUTC')},
            'method':{'purpose':'Attach NDIC order history and stated well allowances to source DMR DSU footprints.',
                      'footprint':'One atlas land description + pool; geometry built by the order atlas from PLSS sections.',
                      'match':f'Plan-view intersection over union with source DSU polygons; exact >= {EXACT_IOU}, close >= {LINK_IOU}. A footprint links to every DSU at or above {LINK_IOU}; {REVIEW_IOU}-{LINK_IOU} goes to review without a link.',
                      'latest':'Atlas latest event per footprint (date, then order number). Same-day conflicting allowances are left without a value by the atlas.',
                      'unitAllowance':'Most recent dated latest event across linked footprints; mixed=true when linked footprints state different values.',
                      'limitations':['Allowances are machine-extracted from order text and have not been human-reviewed.',
                                     'A stated allowance is not proof that the order governs today, nor a drillable-location estimate.',
                                     'Unlinked DSUs may still be governed by orders not yet processed or without explicit land references.']},
            'summary':summary,'units':{k:{'allowance':summaries[k],'footprints':v} for k,v in sorted(units.items())},
            'review':sorted(review,key=lambda r:-r['iou'])}
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    report={**summary,'outputBytes':output_path.stat().st_size,'reviewCount':len(review),'totalSeconds':round(time.perf_counter()-started,1)}
    output_path.with_suffix('.audit.json').write_text(json.dumps({**report,'atlas':result['atlas'],'dsu':result['dsu']},indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('atlas',help='unit_atlas/data.json from the local order queue')
    parser.add_argument('dsus',help='viewer/data/dsu/drilling-spacing-units.geojson')
    parser.add_argument('output',help='viewer/data/dsu/dsu-orders.json')
    args=parser.parse_args(); build(args.atlas,args.dsus,args.output)
