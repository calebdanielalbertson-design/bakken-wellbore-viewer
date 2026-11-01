"""Remaining permitted Bakken wells per DSU: latest order allowance minus surveyed laterals.

Combines the DSU order links (prepare_dsu_orders.py), the lateral membership index
(prepare_dsu_membership.py), the DMR operator join and the NDIC Well Index CSV.
Each unit lists every Bakken-pool well with at least MIN_INSIDE_FT of surveyed
lateral inside it. Because overlapping units share wells, rollups instead assign
each well to one unit: the largest share of its lateral, ties to the smaller unit.
Permitted wells without surveys (LOC, DRL, confidential) are counted separately by
surface location. Allowances are machine-extracted and not human-reviewed; the
balance is a regulatory comparison, not a verified drillable-location count.
Requires shapely (tested with Shapely 2.0.4).
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime
import hashlib
import io
import json
import pathlib
import re
import time
import zipfile

import shapely
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

MIN_INSIDE_FT=660.0
TIE_FRACTION=0.01
BAKKEN_POOLS=('BAKKEN','THREE FORKS','SANISH')
PENDING_STATUS=('LOC','DRL','Confidential')
SUFFIXES=re.compile(r'\b(INCORPORATED|INC|LLC|L L C|LP|L P|LTD|CORPORATION|CORP|COMPANY|CO|USA|U S A|NORTH AMERICA|THE)\b')


def sha_file(path):
    digest=hashlib.sha256()
    with pathlib.Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def permit_key(value):
    return ''.join(c for c in str(value or '') if c.isdigit()).lstrip('0')


def normalize_name(name):
    text=re.sub(r'[^A-Z0-9 ]',' ',str(name or '').upper().replace('&',' AND '))
    return ' '.join(SUFFIXES.sub(' ',text).split())


def read_well_index(path):
    path=pathlib.Path(path)
    if path.suffix.lower()=='.zip':
        with zipfile.ZipFile(path) as archive:
            member=next(n for n in archive.namelist() if n.lower().endswith('.csv'))
            text=archive.read(member).decode('utf-8',errors='replace')
    else:
        text=path.read_text(encoding='utf-8',errors='replace')
    return list(csv.DictReader(io.StringIO(text)))


def pool_class(produced):
    """bakken, other (a known non-Bakken pool) or unknown (blank or confidential)."""
    text=str(produced or '').upper()
    if any(p in text for p in BAKKEN_POOLS): return 'bakken'
    if not text.strip() or 'CONFIDENTIAL' in text: return 'unknown'
    return 'other'


def tr_number(value):
    m=re.match(r'\s*(\d+)',str(value or ''))
    return int(m.group(1)) if m else None


def county_lookup(index_rows):
    by_section=collections.defaultdict(collections.Counter); by_township=collections.defaultdict(collections.Counter)
    for r in index_rows:
        t,rg,s=tr_number(r['Township']),tr_number(r['Range']),tr_number(r['Section'])
        county=re.sub(r'\bMc([a-z])',lambda m:'Mc'+m.group(1).upper(),(r['CountyName'] or '').strip().title())
        if t and rg and county:
            by_township[(t,rg)][county]+=1
            if s: by_section[(t,rg,s)][county]+=1
    def county(land):
        if not land: return None
        votes=collections.Counter()
        for s in land.get('sections') or []: votes.update(by_section.get((land['township'],land['range'],s),{}))
        if not votes: votes=by_township.get((land['township'],land['range']),collections.Counter())
        return votes.most_common(1)[0][0] if votes else None
    return county


def operator_lookup(operators):
    groups={g['id']:g['label'] for g in operators['groups']}
    raw_to_group={normalize_name(n):g['label'] for g in operators['groups'] for n in g.get('rawNames',[])}
    names=operators['names']
    def for_branches(branch_ids):
        votes=collections.Counter()
        for b in branch_ids:
            g=operators['branchGroups'][b] if b<len(operators['branchGroups']) else None
            if g is not None and g in groups: votes[groups[g]]+=1
            elif b<len(operators['branchNames']) and operators['branchNames'][b] is not None: votes[names[operators['branchNames'][b]]]+=1
        return votes.most_common(1)[0][0] if votes else None
    def for_name(name):
        key=normalize_name(name)
        if not key: return None
        if key in raw_to_group: return raw_to_group[key]
        hit=next((label for raw,label in raw_to_group.items() if raw and (key.startswith(raw) or raw.startswith(key))),None)
        return hit or str(name).strip().upper()
    return for_branches,for_name


def assign_exclusive(candidates,acres):
    """candidates: unit id -> membership row. Largest lateral share wins; ties go to the smaller unit."""
    best=max(r['fraction'] for r in candidates.values())
    tied=[u for u,r in candidates.items() if r['fraction']>=best-TIE_FRACTION]
    return min(tied,key=lambda u:(acres.get(u) or 1e9,-candidates[u]['insideFt'],u))


def parse_spud(value):
    """Well Index SpudDate 'MM/DD/YYYY' -> ISO date, else None."""
    try: return datetime.datetime.strptime(str(value or '').strip(),'%m/%d/%Y').date().isoformat()
    except ValueError: return None


def order_number(value):
    return int(value) if str(value).isdigit() else 0


def unit_timeline(entry):
    """From a dsu-orders.json entry: the first dated linked order and the allowance over time.

    start is the earliest dated order on the unit's land. A later re-establishment of the
    same land does not start a new unit. steps lists (date, allowance in force after that
    order) in order-number order; a termination clears the allowance.
    """
    history=sorted((entry or {}).get('footprints',[{}])[0].get('history',[]),key=lambda h:order_number(h.get('order')))
    dated=[h for h in history if h.get('date')]
    start=min(h['date'] for h in dated) if dated else None
    steps=[]; current=None
    for h in history:
        if h.get('event')=='termination': current=None
        elif h.get('wells') is not None: current=h['wells']
        if h.get('date'): steps.append((h['date'],current))
    return {'start':start,'steps':steps}


def allowance_at(steps,date):
    """Allowance in force on a date: the last dated step on or before it."""
    value=None
    for d,a in steps:
        if d<=date: value=a
    return value


def review_tag(rec):
    """Why a unit holds more wells than its latest allowance, most specific first."""
    excess=-rec['assignedBalance']
    if excess<=0: return None
    if rec['wellsBeforeFirstOrder']>=excess: return 'wells_predate_linked_orders'
    if rec['wellsAfterLatestOrder']>rec['allowed']: return 'later_order_likely_missing'
    if (rec['acres'] or 0)>=2560 and rec['allowed']<=2: return 'overlapping_unit_small_allowance'
    return 'over_allowance'


def score_attribution(key,chosen,alternative):
    """How many answer-key wells (named with their unit in an order) the build's rule and an
    alternative (units with a stated allowance first) each assign to that unit."""
    by_permit=collections.defaultdict(set)
    for p in key: by_permit[str(p['permit'])].add(p['dsu'])
    result=collections.Counter()
    for well,unit in chosen.items():
        truth=by_permit.get(well.split('|')[0])
        if not truth: continue
        result['wells']+=1; result['geometry']+=unit in truth; result['allowanceFirst']+=alternative[well] in truth
    return dict(result)


def rollup(rows,key):
    groups=collections.defaultdict(lambda:collections.Counter())
    for r in rows:
        g=groups[r[key] or 'Unknown']
        g['units']+=1; g['allowed']+=r['allowed']; g['assignedWells']+=r['assignedWells']; g['pending']+=r['pending']
        g['remaining']+=max(0,r['assignedBalance']); g['remainingAfterPending']+=max(0,r['assignedBalance']-r['pending'])
        g['overAllowance']+=max(0,-r['assignedBalance']); g['unitsWithRoom']+=r['assignedBalance']>0
    return sorted(({'name':k,**dict(v)} for k,v in groups.items()),key=lambda g:(-g['remaining'],g['name']))


def build(orders_path,membership_path,dsu_path,dataset_path,well_index_path,atlas_path,output_path,key_path=None,production_glob=None):
    started=time.perf_counter()
    answer_key=json.loads(pathlib.Path(key_path).read_text(encoding='utf-8'))['pairs'] if key_path else None
    dataset_path=pathlib.Path(dataset_path)
    paths=[pathlib.Path(p) for p in (orders_path,membership_path,dsu_path,dataset_path/'manifest.json',dataset_path/'operators.json',well_index_path,atlas_path)]
    orders_path,membership_path,dsu_path,manifest_path,operators_path,well_index_path,atlas_path=paths; output_path=pathlib.Path(output_path)
    orders=json.loads(orders_path.read_text(encoding='utf-8'))
    membership=json.loads(membership_path.read_text(encoding='utf-8'))
    dsus=json.loads(dsu_path.read_text(encoding='utf-8'))
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    operators=json.loads(operators_path.read_text(encoding='utf-8'))
    atlas=json.loads(atlas_path.read_text(encoding='utf-8'))
    index_rows=read_well_index(well_index_path)
    features=dsus['features']; ids=[f['properties']['id'] for f in features]
    ids_hash=hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()
    if orders['dsu']['idsSha256']!=ids_hash or membership['dsu']['idsSha256']!=ids_hash:
        raise ValueError('Order links, membership and DSU file come from different DSU snapshots')
    if not (len(manifest['wells'])==membership['survey']['branchCount']==operators['survey']['branchCount']):
        raise ValueError('Survey manifest, operator join and membership use different survey snapshots')
    acres={f['properties']['id']:f['properties'].get('acres') for f in features}
    index_by_permit={}
    for r in index_rows: index_by_permit.setdefault(permit_key(r['FileNo']),r)
    county_of=county_lookup(index_rows); operator_of_branches,operator_of_name=operator_lookup(operators)
    applicant={}; case_op={c['c']:c.get('op') for c in atlas.get('cases',[])}
    for r in atlas['records']:
        name=r.get('applicant') or case_op.get(r.get('case'))
        if name: applicant.setdefault(str(r['order']),name)
    # Order links built from the land index carry applicants for orders the atlas never mapped.
    for order,name in (orders.get('applicants') or {}).items(): applicant.setdefault(str(order),name)
    counters=collections.Counter()
    # With monthly production, a well whose production is mostly from another pool (a Madison
    # horizontal or Birdbear re-entry with a little Bakken) is not a Bakken well either.
    mostly_other=set()
    if production_glob:
        import glob
        from prepare_overlap_depletion import load_production,non_bakken_wells
        other=collections.Counter()
        production,_=load_production(sorted(glob.glob(production_glob)),other)
        mostly_other=non_bakken_wells(index_rows,production,other)

    # Bakken-pool wells per unit (every unit, including overlapping ones).
    eligible_rows=collections.defaultdict(dict); well_pool={}
    for unit_id,rows in membership['units'].items():
        for row in rows:
            if row['insideFt']<MIN_INSIDE_FT: continue
            if row['key'] not in well_pool:
                well_pool[row['key']]='other' if row['permit'] in mostly_other else pool_class((index_by_permit.get(row['permit']) or {}).get('ProducedPools'))
                counters['wellsPool_'+well_pool[row['key']]]+=1
            if well_pool[row['key']]=='other': continue
            eligible_rows[unit_id][row['key']]=row
    # One unit per well for rollups, chosen among every DSU it lies in.
    by_well=collections.defaultdict(dict)
    for unit_id,rows in eligible_rows.items():
        for key,row in rows.items(): by_well[key][unit_id]=row
    # Geometry alone decides: on wells that orders name with their unit, it beat both
    # giving units with a stated allowance precedence and filtering units by spud date
    # (linked order histories often start late). Spud dates diagnose units below instead.
    has_allowance={u for u,e in orders['units'].items() if (e.get('allowance') or {}).get('wells') is not None and not e['allowance'].get('mixed')}
    timelines={u:unit_timeline(e) for u,e in orders['units'].items()}
    spud={key:parse_spud((index_by_permit.get(key.split('|')[0]) or {}).get('SpudDate')) for key in by_well}
    counters['wellsWithSpudDate']=sum(v is not None for v in spud.values())
    assigned=collections.defaultdict(list); chosen={}; allowance_first={}
    for key,candidates in by_well.items():
        chosen[key]=assign_exclusive(candidates,acres); assigned[chosen[key]].append(key)
        governed={u:r for u,r in candidates.items() if u in has_allowance}
        allowance_first[key]=assign_exclusive(governed or candidates,acres)
    counters['wellsAssignedDifferentlyThanAllowanceFirst']=sum(chosen[k]!=allowance_first[k] for k in chosen)
    score=score_attribution(answer_key,chosen,allowance_first) if answer_key else None

    # Permitted but unsurveyed wells by surface location; smallest containing unit.
    surveyed={permit_key(w['permit']) for w in manifest['wells']}
    polygons=[shape(f['geometry']).buffer(0) for f in features]; tree=STRtree(polygons)
    pending=collections.defaultdict(list)
    for r in index_rows:
        if r['WellStatus'] not in PENDING_STATUS or r['Wellbore'] not in ('HORIZONTAL','Confidential'): continue
        if permit_key(r['FileNo']) in surveyed: counters['pendingAlreadySurveyed']+=1; continue
        if pool_class(r['ProducedPools'])=='other' or permit_key(r['FileNo']) in mostly_other: continue
        try: point=Point(float(r['Longitude']),float(r['Latitude']))
        except ValueError: counters['pendingWithoutLocation']+=1; continue
        hits=[ids[j] for j in tree.query(point,predicate='within')]
        if not hits: counters['pendingOutsideDSUs']+=1; continue
        pending[min(hits,key=lambda u:(acres.get(u) or 1e9,u))].append(permit_key(r['FileNo'])); counters['pendingInDSUs']+=1

    units={}; table=[]
    for unit_id,entry in orders['units'].items():
        allowance=entry.get('allowance') or {}
        wells=allowance.get('wells')
        if wells is None or allowance.get('mixed'):
            counters['skippedNoSingleAllowance']+=1; continue
        rows=eligible_rows.get(unit_id,{})
        branch_ids=[b for row in rows.values() for b in row['branchIds']]
        holder=operator_of_branches(branch_ids); holder_source='wells'
        if not holder:
            holder=operator_of_name(applicant.get(allowance.get('order'))); holder_source='order applicant' if holder else None
        lead=entry['footprints'][0]
        rec={'allowed':wells,'order':allowance.get('order'),'date':allowance.get('date'),'qualifier':allowance.get('qualifier'),
             'wellsInside':len(rows),'assignedWells':len(assigned.get(unit_id,[])),'pending':len(pending.get(unit_id,[])),
             'pool':lead.get('pool'),'county':county_of(lead.get('land')),'holder':holder,'holderSource':holder_source,
             'acres':acres.get(unit_id)}
        rec['balance']=wells-rec['wellsInside']; rec['assignedBalance']=wells-rec['assignedWells']
        # Spud dates against the unit's orders: which wells predate its current
        # configuration, and which were drilled beyond the allowance then in force.
        timeline=timelines.get(unit_id) or {'start':None,'steps':[]}
        charged=sorted((spud[k] for k in assigned.get(unit_id,[]) if spud[k]))
        rec['firstOrderDate']=timeline['start']
        rec['wellsBeforeFirstOrder']=sum(1 for d in charged if timeline['start'] and d<timeline['start'])
        rec['wellsAfterLatestOrder']=sum(1 for d in charged if rec['date'] and d>rec['date'])
        beyond=0
        for i,d in enumerate(charged,1):
            in_force=allowance_at(timeline['steps'],d)
            beyond+=in_force is not None and i>in_force
        rec['drilledBeyondOrderInForce']=beyond
        rec['review']=review_tag(rec)
        units[unit_id]=rec; table.append(rec)
    total=collections.Counter()
    for r in table:
        total['units']+=1; total['allowed']+=r['allowed']; total['assignedWells']+=r['assignedWells']; total['pending']+=r['pending']
        total['remaining']+=max(0,r['assignedBalance']); total['remainingAfterPending']+=max(0,r['assignedBalance']-r['pending'])
        total['overAllowance']+=max(0,-r['assignedBalance']); total['unitsWithRoom']+=r['assignedBalance']>0
        total['remainingConservative']+=max(0,r['balance'])
        if r['review']: total['overUnits_'+r['review']]+=1
    total['wellsAssignedToUnitsWithoutAllowance']=sum(len(v) for k,v in assigned.items() if k not in units)
    result={'version':1,'createdAtUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'survey':membership['survey'],'dsu':{'featureCount':len(features),'idsSha256':ids_hash},
            'sourceHashes':{p.name:sha_file(p) for p in paths},
            'method':{'allowance':'Latest linked order allowance from dsu-orders.json; units with no single or mixed allowances are omitted.',
                      'wellsInside':f'Distinct permit + API10 wells with at least {MIN_INSIDE_FT:.0f} ft of classified surveyed lateral inside the unit (dsu-well-membership.json).',
                      'pool':'Wells whose Well Index ProducedPools names a pool and none of '+', '.join(BAKKEN_POOLS)+' are excluded; blank or confidential pools are kept.'+(' So are wells whose monthly production is mostly reported to another pool.' if production_glob else ''),
                      'assignedWells':f'Each counted well is assigned to one DSU by geometry alone: the largest share of its lateral; shares within {TIE_FRACTION:.0%} go to the smaller unit. A well in a unit with no stated allowance uses none. Rollups use these so overlapping units do not double count. attributionScore compares this rule with giving units that have an allowance precedence, on wells that orders name with their unit.',
                      'timing':'firstOrderDate (earliest dated linked order on the unit\'s land), wellsBeforeFirstOrder (charged wells spudded before it), wellsAfterLatestOrder (spudded after the allowance order) and drilledBeyondOrderInForce (wells whose spud-order count exceeds the allowance in force that day) compare Well Index spud dates with the unit\'s order dates. They tag why a unit is over its allowance; they do not change attribution.',
                      'conservative':'totals.remainingConservative uses each unit\'s own wellsInside, so shared wells reduce every unit they cross; it is a lower bound.',
                      'pending':'Well Index LOC, DRL and confidential horizontal permits not in the survey snapshot, placed by surface location in the smallest containing DSU.',
                      'holder':'Most common viewer operator group among the unit\'s counted wells, else the latest order applicant.',
                      'county':'Most common Well Index county in the unit\'s order sections (township fallback).',
                      'limitations':['Allowances are machine-extracted and not human-reviewed.',
                                     'A positive balance is regulatory room under the latest linked order, not a verified drillable location.',
                                     'Negative balances usually mean other governing orders, overlapping units or extraction gaps.',
                                     'Surveys end '+str(membership['survey'].get('sourceDate'))+'; wells drilled since are only in pending if still LOC/DRL/confidential.',
                                     'Holder is the operator of most wells, not legal unit operatorship or working interest.']},
            'totals':dict(total),'counts':dict(counters),'units':units,
            'rollups':{'county':rollup(table,'county'),'operator':rollup(table,'holder'),'pool':rollup(table,'pool')}}
    if score: result['attributionScore']=score
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    report={'totals':dict(total),'counts':dict(counters),'attributionScore':score,'topCounties':result['rollups']['county'][:5],'topOperators':result['rollups']['operator'][:5],
            'outputBytes':output_path.stat().st_size,'totalSeconds':round(time.perf_counter()-started,1)}
    output_path.with_suffix('.audit.json').write_text(json.dumps({**report,'sourceHashes':result['sourceHashes']},indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('orders',help='viewer/data/dsu/dsu-orders.json')
    parser.add_argument('membership',help='viewer/data/dsu/dsu-well-membership.json')
    parser.add_argument('dsus',help='viewer/data/dsu/drilling-spacing-units.geojson')
    parser.add_argument('dataset',help='full-dataset folder (manifest.json, operators.json)')
    parser.add_argument('well_index',help='NDIC Well Index ZIP or WellIndex.csv')
    parser.add_argument('atlas',help='local order queue unit_atlas/data.json (order applicants)')
    parser.add_argument('output',help='viewer/data/dsu/dsu-headroom.json')
    parser.add_argument('--answer-key',help='land_index/data/well_unit_key.json: wells named with their unit in orders, to score attribution')
    parser.add_argument('--production',help='quoted glob of NDIC monthly production CSVs: also leave out wells whose production is mostly from another pool')
    args=parser.parse_args(); build(args.orders,args.membership,args.dsus,args.dataset,args.well_index,args.atlas,args.output,args.answer_key,args.production)
