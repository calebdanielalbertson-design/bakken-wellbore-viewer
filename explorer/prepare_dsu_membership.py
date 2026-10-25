"""Exact XY intersection of current surveyed lateral linework with source DSUs.

This is geometric overlap for highlighting and whole-well production lookup. It
is not a legal/regulatory DSU assignment and does not allocate well production.
Requires numpy and shapely (tested with Shapely 2.0.4).
"""
from __future__ import annotations
import argparse
import collections
import datetime
import hashlib
import json
import math
import pathlib
import time

import numpy as np
import shapely
from shapely.geometry import LineString, MultiLineString, shape
from shapely.strtree import STRtree

MAX_MD_GAP_FT=1000.0
MIN_OVERLAP_FT=1e-6


def sha_file(path):
    digest=hashlib.sha256()
    with pathlib.Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def well_identity(branch):
    permit=''.join(c for c in str(branch['permit']) if c.isdigit()).lstrip('0')
    api=''.join(c for c in str(branch['api']) if c.isdigit())
    if not permit or len(api)<10: raise ValueError('Missing permit or API10')
    api10=api[:10]
    return permit+'|'+api10,permit,api10


def source_projection(origin):
    """Same NAD83 ellipsoid and east/south feet as viewer projectReference."""
    lon0,lat0=np.deg2rad(origin)
    flattening=1/298.257222101
    eccentricity2=flattening*(2-flattening)
    a=6378137.0
    def ecef(lon,lat):
        n=a/np.sqrt(1-eccentricity2*np.sin(lat)**2)
        return np.column_stack((n*np.cos(lat)*np.cos(lon),n*np.cos(lat)*np.sin(lon),n*(1-eccentricity2)*np.sin(lat)))
    center=ecef(np.asarray([lon0]),np.asarray([lat0]))[0]
    def project(coords):
        lon,lat=np.deg2rad(coords[:,0]),np.deg2rad(coords[:,1])
        delta=ecef(lon,lat)-center
        east=-math.sin(lon0)*delta[:,0]+math.cos(lon0)*delta[:,1]
        north=-math.sin(lat0)*math.cos(lon0)*delta[:,0]-math.sin(lat0)*math.sin(lon0)*delta[:,1]+math.cos(lat0)*delta[:,2]
        return np.column_stack((east/.3048,-north/.3048))
    return project


def lateral_geometry(stations,md,counters=None):
    """Keep segments ending in section 4, split at excluded survey intervals."""
    if len(stations)!=len(md): raise ValueError('Station/MD alignment mismatch')
    if len(stations)<2: return None
    xy=np.asarray(stations[:,[0,2]],dtype=np.float64)
    delta=np.diff(md.astype(np.float64))
    section4=stations[1:,3]==4
    finite=np.isfinite(stations[:,:3]).all(axis=1)
    finite_md=np.isfinite(md)
    coordinates=finite[1:] & finite[:-1]
    measured=finite_md[1:] & finite_md[:-1]
    increasing=delta>0
    close=delta<=MAX_MD_GAP_FT
    steps=np.linalg.norm(np.diff(xy,axis=0),axis=1)
    nonzero=steps>0
    valid=section4 & coordinates & measured & increasing & close & nonzero
    if counters is not None:
        counters['candidateLateralSegments']+=int(section4.sum())
        counters['excludedNonfiniteCoordinates']+=int((section4 & ~coordinates).sum())
        counters['excludedMissingMD']+=int((section4 & coordinates & ~measured).sum())
        counters['excludedNonincreasingMD']+=int((section4 & coordinates & measured & ~increasing).sum())
        counters['excludedMDGapsOver1000Ft']+=int((section4 & coordinates & measured & increasing & ~close).sum())
        counters['excludedZeroHorizontalLength']+=int((section4 & coordinates & measured & increasing & close & ~nonzero).sum())
        counters['includedLateralSegments']+=int(valid.sum())
        counters['includedRawHorizontalFt']+=float(steps[valid].sum())
    # Runs of adjacent accepted segments preserve source bends without bridging
    # classified sections or missing/non-increasing/large-MD-gap intervals.
    starts=np.flatnonzero(valid & ~np.r_[False,valid[:-1]])
    stops=np.flatnonzero(valid & ~np.r_[valid[1:],False])+1
    lines=[xy[start:stop+1] for start,stop in zip(starts,stops)]
    if not lines: return None
    return LineString(lines[0]) if len(lines)==1 else MultiLineString(lines)


def merged_well_geometry(branch_geometries):
    if not branch_geometries: return None
    # Unary union also collapses retraced sections inside one branch. Returning
    # a single raw LineString would count its exact self-overlap twice.
    return shapely.union_all(branch_geometries)


def exact_positive_length(line,polygon):
    length=float(shapely.intersection(line,polygon).length)
    return length if length>MIN_OVERLAP_FT else 0.0


def build(dsu_path,dataset_path,output_path):
    started=time.perf_counter(); phases={}
    dsu_path=pathlib.Path(dsu_path); dataset_path=pathlib.Path(dataset_path); output_path=pathlib.Path(output_path)
    dsus=json.loads(dsu_path.read_text(encoding='utf-8'))
    manifest=json.loads((dataset_path/'manifest.json').read_text(encoding='utf-8'))
    metrics=json.loads((dataset_path/'metrics.json').read_text(encoding='utf-8'))
    if manifest['sourceCRS']!='NAD83' or dsus['metadata']['sourceCRS']!='EPSG:4269':
        raise ValueError('Requires matching NAD83 dataset and DSU source geometry')
    if not (metrics['stride']==8 and metrics['stations']==manifest['stations'] and metrics['branchCount']==len(manifest['wells'])
            and metrics['source']['sourceCRS']==manifest['sourceCRS'] and metrics['source']['origin']==manifest['origin']):
        raise ValueError('Survey MD metrics do not match current station dataset')
    if next(f['name'] for f in metrics['fields'] if f['index']==0)!='mdFt':
        raise ValueError('Expected source measured depth at metrics field zero')
    features=dsus['features']; ids=[f['id'] for f in features]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate current DSU viewer IDs')
    project=source_projection(manifest['origin'])
    polygons=np.asarray([shapely.transform(shape(f['geometry']),project) for f in features],dtype=object)
    if not shapely.is_valid(polygons).all() or (shapely.area(polygons)<=0).any():
        raise ValueError('Invalid projected source DSU polygon')
    phases['readAndProjectDSUsSeconds']=time.perf_counter()-started
    counters=collections.Counter()
    by_tile=collections.defaultdict(list); well_meta={}; permit_apis=collections.defaultdict(set)
    for index,branch in enumerate(manifest['wells']):
        if branch['id']!=index: raise ValueError('Branch ID is not aligned to manifest index')
        key,permit,api10=well_identity(branch)
        permit_apis[permit].add(api10)
        well_meta.setdefault(key,{'key':key,'permit':permit,'api10':api10,'branchIds':[]})['branchIds'].append(branch['id'])
        by_tile[branch['tile']].append(branch)
    for permit,apis in permit_apis.items():
        if len(apis)>1: raise ValueError('One permit maps to multiple API10 identities; resolve before production aggregation')
    geometry_list=[]; geometry_branch_ids=[]; geometry_well_keys=[]; per_well=collections.defaultdict(list)
    chunk_hashes=[]; phase=time.perf_counter()
    metric_by_tile={tile['id']:tile for tile in metrics['tiles']}
    for tile in manifest['tiles']:
        geometry_path=dataset_path/tile['file']; md_path=dataset_path/metric_by_tile[tile['id']]['file']
        stations=np.fromfile(geometry_path,dtype='<f4').reshape((-1,4))
        measurements=np.fromfile(md_path,dtype='<f4').reshape((-1,8))
        if len(stations)!=tile['stations'] or len(measurements)!=len(stations):
            raise ValueError('Incomplete or misaligned tile '+tile['id'])
        expected_offset=0
        for branch in sorted(by_tile[tile['id']],key=lambda w:w['offset']):
            first=branch['offset']; last=first+branch['count']
            if first!=expected_offset or last>len(stations): raise ValueError('Branch bounds do not cover tile exactly')
            expected_offset=last
            line=lateral_geometry(stations[first:last],measurements[first:last,0],counters)
            if line is not None and line.length>0:
                key=well_identity(branch)[0]
                index=len(geometry_list)
                geometry_list.append(line); geometry_branch_ids.append(branch['id']); geometry_well_keys.append(key)
                per_well[key].append(index)
        if expected_offset!=len(stations): raise ValueError('Station tile has unindexed records')
        chunk_hashes.append({'id':tile['id'],'geometrySha256':sha_file(geometry_path),'metricsSha256':sha_file(md_path)})
    phases['buildBranchLineworkAndHashSeconds']=time.perf_counter()-phase
    phase=time.perf_counter(); branch_geometries=np.asarray(geometry_list,dtype=object)
    total_linework={key:merged_well_geometry([geometry_list[i] for i in indexes]) for key,indexes in per_well.items()}
    total_lengths={key:float(line.length) for key,line in total_linework.items()}
    for key,value in total_lengths.items():
        if not math.isfinite(value) or value<=0: raise ValueError('Invalid whole-well horizontal length')
    phases['deduplicateWholeWellLineworkSeconds']=time.perf_counter()-phase
    phase=time.perf_counter()
    tree=STRtree(branch_geometries)
    pair_indices=tree.query(polygons,predicate='intersects')
    # Vectorized exact clipping is restricted to STRtree candidates. A point-only
    # intersection has zero line length and never creates membership.
    clipped=shapely.intersection(branch_geometries[pair_indices[1]],polygons[pair_indices[0]])
    lengths=shapely.length(clipped)
    valid=lengths>MIN_OVERLAP_FT
    counters['intersectingCandidateBranchDSUPairs']=len(lengths)
    counters['touchOnlyOrNumericalZeroPairsExcluded']=int((~valid).sum())
    counters['positiveBranchDSUPairs']=int(valid.sum())
    grouped=collections.defaultdict(list)
    for unit_index,branch_index,inside in zip(pair_indices[0,valid],pair_indices[1,valid],clipped[valid]):
        grouped[(int(unit_index),geometry_well_keys[branch_index])].append((int(branch_index),inside))
    units={feature_id:[] for feature_id in ids}; fractions=[]; anomalous=[]
    for (unit_index,key),parts in grouped.items():
        # Union clips from all branches, so shared branch trajectories contribute
        # once. This equals clipping the unioned whole-well lateral linework.
        inside_geometry=merged_well_geometry([part[1] for part in parts])
        inside=float(inside_geometry.length); total=total_lengths[key]
        if inside>total+max(1e-5,total*1e-9):
            anomalous.append({'unit':ids[unit_index],'key':key,'insideFt':inside,'totalFt':total})
            raise ValueError('Inside line length exceeds whole-well deduplicated length')
        fraction=min(1.0,max(0.0,inside/total))
        record={**well_meta[key],
                'intersectingBranchIds':sorted(geometry_branch_ids[index] for index,_ in parts),
                'insideFt':round(inside,6),'totalFt':round(total,6),'fraction':round(fraction,10)}
        units[ids[unit_index]].append(record); fractions.append(fraction)
    for rows in units.values(): rows.sort(key=lambda r:(int(r['permit']),r['api10']))
    phases['IndexClipAndGroupSeconds']=time.perf_counter()-phase
    dsu_geometry_hash=hashlib.sha256(json.dumps([[f['id'],f['geometry']] for f in features],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    source_hashes={'dsuFileSha256':sha_file(dsu_path),'dsuGeometryAndIdsSha256':dsu_geometry_hash,
                   'manifestSha256':sha_file(dataset_path/'manifest.json'),'metricsManifestSha256':sha_file(dataset_path/'metrics.json'),
                   'chunks':chunk_hashes}
    survey={'stations':manifest['stations'],'branchCount':len(manifest['wells']),'wellCount':len(well_meta),
            'tileCount':len(manifest['tiles']),'origin':manifest['origin'],'sourceCRS':manifest['sourceCRS'],
            'sourceDate':manifest.get('sourceSnapshot',{}).get('date'),
            'archiveSha256':manifest.get('sourceSnapshot',{}).get('archiveSHA256')}
    method={'purpose':'Geometric lateral overlap for DSU highlighting and deduplicated whole-well production lookup.',
            'coordinates':'Viewer NAD83 ellipsoidal tangent plane: east X, south Z, feet; original source DSU polygons projected with projectReference formula.',
            'sourceFootprint':'Feature.geometry only; display inset/band geometry and approximate vertical zones are ignored.',
            'sections':'Actual survey station segments whose ending station has section code 4 (Lateral), matching the renderer section convention.',
            'gapPolicy':{'maxMeasuredDepthGapFt':MAX_MD_GAP_FT,'missingMD':'exclude segment','nonincreasingMD':'exclude segment','nonfiniteXYZ':'exclude segment'},
            'length':'Horizontal XY/plan length in feet, not MD or 3D path length.',
            'deduplication':'Union exact linework across all branches of each unique permit + API10 identity; no snapping or tolerance expansion.',
            'membership':'STRtree candidate index followed by exact original-polygon clipping; positive unioned line length only.',
            'minimumPositiveOverlapFt':MIN_OVERLAP_FT,
            'fraction':'Deduplicated horizontal lateral line length inside this source DSU / deduplicated total horizontal lateral line length for the whole well.',
            'branchIds':'All current manifest branches for the well, including non-lateral branches, for whole-well highlighting.',
            'intersectingBranchIds':'Only branches with a positive-length surveyed lateral overlap in this source DSU.',
            'production':'Use each permit + API10 once per selected unit for whole-well production; no production is prorated by fraction or allocated exclusively to a DSU.',
            'limitations':['Geometric overlap is not a legal DSU assignment, ownership statement, completion allocation or inventory estimate.',
                          'A well may overlap multiple overlapping DSUs; production totals across DSUs must not be summed as exclusive allocations.',
                          'The full station geometry is Float32 and carries its source coordinate precision.',
                          'No path is inferred between excluded survey intervals, from wellheads, or from approximate formation depths.']}
    result={'version':1,'createdAtUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'survey':survey,
            'dsu':{'featureCount':len(features),'idsSha256':hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()},
            'method':method,'sourceHashes':source_hashes,'units':units}
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    assigned_keys={row['key'] for rows in units.values() for row in rows}
    report={'survey':survey,'dsuFeatures':len(features),'unitsWithWells':sum(bool(rows) for rows in units.values()),
            'geometricMembershipRecords':sum(map(len,units.values())),'distinctOverlappingWells':len(assigned_keys),
            'wellsWithLateralLinework':len(per_well),'branchesWithLateralLinework':len(branch_geometries),
            'wellsWithoutUsableLateralLinework':len(well_meta)-len(per_well),
            'wellsWithLateralLineworkOutsideAllDSUs':len(per_well)-len(assigned_keys),
            'wholeWellDeduplicatedHorizontalFt':sum(total_lengths.values()),'counts':dict(counters),
            'fractionMin':min(fractions) if fractions else None,'fractionMax':max(fractions) if fractions else None,
            'containedMembershipsAtLeast99_9999Percent':sum(f>=.999999 for f in fractions),
            'outputBytes':output_path.stat().st_size,'performanceSeconds':phases,'totalSeconds':time.perf_counter()-started,
            'lengthAnomalies':anomalous,'sourceHashes':source_hashes,
            'examples':sorted(((unit_id,rows) for unit_id,rows in units.items() if rows),key=lambda item:len(item[1]),reverse=True)[:3]}
    output_path.with_suffix('.audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('sourceHashes','examples')},indent=2))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dsus'); parser.add_argument('dataset'); parser.add_argument('output')
    args=parser.parse_args(); build(args.dsus,args.dataset,args.output)
