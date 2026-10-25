"""Prepare mapped-lateral footage and measured-area inputs for scenario viewing.

This emits observed drilling-geometry proxies, not completed-reservoir depletion,
remaining locations or EUR. No density default or inventory residual is computed.
Install the optional preprocessing dependencies with:
    python -m pip install -r requirements-footage.txt

Example:
    python prepare_footage.py --dataset full-dataset --dsus local-data/dsus.geojson \
        --townships local-data/Townships.shp --output-dir viewer/data/inventory
"""
from __future__ import annotations
import argparse
import collections
import datetime
import hashlib
import importlib.util
import json
import math
import pathlib
import sys
import time

sys.dont_write_bytecode=True
import geopandas as gpd
import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.strtree import STRtree

REPO_ROOT=pathlib.Path(__file__).resolve().parent
SQM_PER_ACRE=4046.8564224
METRES_PER_FOOT=.3048
MIN_OVERLAP_FT=1e-6
AREA_CRS='EPSG:5070'


def sha_file(path):
    with pathlib.Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def dataset_file(dataset_path,name):
    """Prepared manifests may reference files only inside their dataset folder."""
    root=pathlib.Path(dataset_path).resolve()
    if not isinstance(name,str) or not name or pathlib.Path(name).is_absolute():
        raise ValueError('Dataset filename must be a relative path')
    target=(root/name).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Dataset filename escapes its source folder')
    return target


def guard_output_inputs(output_dir,input_paths):
    """Refuse an output path that would overwrite any explicitly read input."""
    inputs={pathlib.Path(path).resolve() for path in input_paths}
    for name in ('footage.json','townships.geojson','build-audit.json','source-hashes.json'):
        if (pathlib.Path(output_dir)/name).resolve() in inputs:
            raise ValueError('Output would overwrite a source input: '+name)


def load_membership_helpers(path):
    spec=importlib.util.spec_from_file_location('read_only_membership_geometry',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tangent_inverse(origin):
    """Invert projectReference's GRS80 surface east/south projection.

    Solve the intersection of the known east/north point plus origin-normal
    direction with the GRS80 ellipsoid, choosing the near-side root. No station
    TVD or elevation is used as height. Input coordinates are viewer X/Z feet.
    """
    lon0,lat0=np.deg2rad(np.asarray(origin,dtype=np.float64))
    a=6378137.0; flattening=1/298.257222101; b=a*(1-flattening)
    e2=flattening*(2-flattening); ep2=(a*a-b*b)/(b*b)
    n=a/math.sqrt(1-e2*math.sin(lat0)**2)
    center=np.asarray([n*math.cos(lat0)*math.cos(lon0),n*math.cos(lat0)*math.sin(lon0),n*(1-e2)*math.sin(lat0)])
    east=np.asarray([-math.sin(lon0),math.cos(lon0),0.0])
    north=np.asarray([-math.sin(lat0)*math.cos(lon0),-math.sin(lat0)*math.sin(lon0),math.cos(lat0)])
    up=np.asarray([math.cos(lat0)*math.cos(lon0),math.cos(lat0)*math.sin(lon0),math.sin(lat0)])
    diagonal=np.asarray([1/a**2,1/a**2,1/b**2])
    qa=float(np.sum(up*up*diagonal))
    def inverse(coords):
        xy=np.asarray(coords,dtype=np.float64)
        q=center+xy[:,0,None]*METRES_PER_FOOT*east-xy[:,1,None]*METRES_PER_FOOT*north
        qb=2*np.sum(q*up*diagonal,axis=1)
        qc=np.sum(q*q*diagonal,axis=1)-1
        discriminant=qb*qb-4*qa*qc
        if np.any(discriminant<0): raise ValueError('Tangent coordinate does not intersect near-side GRS80 ellipsoid')
        # Stable near root avoids cancellation near the origin.
        height=-2*qc/(qb+np.sqrt(discriminant))
        xyz=q+height[:,None]*up
        longitude=np.arctan2(xyz[:,1],xyz[:,0])
        p=np.hypot(xyz[:,0],xyz[:,1])
        theta=np.arctan2(xyz[:,2]*a,p*b)
        latitude=np.arctan2(xyz[:,2]+ep2*b*np.sin(theta)**3,p-e2*a*np.cos(theta)**3)
        return np.rad2deg(np.column_stack((longitude,latitude)))
    return inverse


def geographic_projector():
    transformer=Transformer.from_crs('EPSG:4269',AREA_CRS,always_xy=True)
    def project(coords):
        x,y=transformer.transform(coords[:,0],coords[:,1])
        return np.column_stack((x,y))
    return project


def viewer_projector(origin):
    inverse=tangent_inverse(origin); project=geographic_projector()
    return lambda coords:project(inverse(coords))


def project_geometry(geometry,project):
    return shapely.transform(geometry,project)


def group_observations(polygons,well_geometries,branch_geometries):
    """Exact positive-length clips, independently summed once per well/group."""
    polygons=np.asarray(polygons,dtype=object)
    observed=np.zeros(len(polygons),dtype=np.int64)
    footage=np.zeros(len(polygons),dtype=np.float64)
    branches=np.zeros(len(polygons),dtype=np.int64)
    if not len(polygons): return footage,observed,branches,[]
    pairs=STRtree(well_geometries).query(polygons,predicate='intersects')
    clipped=shapely.intersection(well_geometries[pairs[1]],polygons[pairs[0]])
    lengths=shapely.length(clipped)/METRES_PER_FOOT
    keep=lengths>MIN_OVERLAP_FT
    footage=np.bincount(pairs[0,keep],weights=lengths[keep],minlength=len(polygons))
    observed=np.bincount(pairs[0,keep],minlength=len(polygons))
    b_pairs=STRtree(branch_geometries).query(polygons,predicate='intersects')
    b_length=shapely.length(shapely.intersection(branch_geometries[b_pairs[1]],polygons[b_pairs[0]]))/METRES_PER_FOOT
    branches=np.bincount(b_pairs[0,b_length>MIN_OVERLAP_FT],minlength=len(polygons))
    memberships=[(int(group),int(well)) for group,well in zip(pairs[0,keep],pairs[1,keep])]
    return footage,observed,branches,memberships


def total_clipped_ft(wells,polygon):
    if polygon.is_empty: return 0.0
    indexes=STRtree(wells).query(polygon,predicate='intersects')
    return float(shapely.length(shapely.intersection(wells[indexes],polygon)).sum()/METRES_PER_FOOT)


def township_identity(row):
    township=float(row['TOWNSHIP']);range_number=float(row['RANGE'])
    td=str(row['TDIR']).strip().upper();rd=str(row['RDIR']).strip().upper()
    if not (math.isfinite(township) and township.is_integer() and township>0 and
            math.isfinite(range_number) and range_number.is_integer() and range_number>0 and td in ('N','S') and rd in ('E','W')):
        raise ValueError('Invalid full township/range/direction identity')
    township=int(township);range_number=int(range_number)
    return f'township-{township:03}{td}-{range_number:03}{rd}',{
        'township':township,'township_direction':td,'range':range_number,'range_direction':rd,
        'tr_key':f'T{township}{td}-R{range_number}{rd}','label':f'T{township}{td} R{range_number}{rd}'}


def read_townships(path):
    frame=gpd.read_file(path)
    if frame.crs is None or frame.crs.to_epsg()!=4269:
        raise ValueError('Townships require explicit geographic NAD83 source CRS')
    if not frame.is_valid.all() or frame.geometry.isna().any() or frame.geometry.is_empty.any():
        raise ValueError('Invalid source township polygons')
    groups=collections.defaultdict(list);properties={}
    for _,row in frame.iterrows():
        key,props=township_identity(row)
        groups[key].append(row.geometry);properties[key]=props
    dissolved={key:shapely.union_all(groups[key]) for key in sorted(groups)}
    if not all(geom.is_valid and not geom.is_empty for geom in dissolved.values()):
        raise ValueError('Invalid dissolved township geometry')
    return dissolved,properties,{'fragments':len(frame),'dissolved_townships':len(dissolved)}


def round_number(value):
    return round(float(value),6)


def build(dsus_path,dataset_path,township_path,output_dir,helpers_path=None,
          expected_manifest_sha256=None,membership_path=None):
    start=time.perf_counter();timings={}
    dsus_path=pathlib.Path(dsus_path);dataset_path=pathlib.Path(dataset_path)
    township_path=pathlib.Path(township_path);output_dir=pathlib.Path(output_dir)
    helpers_path=pathlib.Path(helpers_path) if helpers_path is not None else REPO_ROOT/'prepare_dsu_membership.py'
    membership_path=pathlib.Path(membership_path) if membership_path is not None else None
    manifest_path=dataset_path/'manifest.json'
    manifest_hash=sha_file(manifest_path)
    if expected_manifest_sha256 is not None:
        if len(expected_manifest_sha256)!=64 or any(c not in '0123456789abcdef' for c in expected_manifest_sha256):
            raise ValueError('Expected manifest SHA256 must be 64 lowercase hexadecimal characters')
        if manifest_hash!=expected_manifest_sha256:
            raise ValueError('Survey manifest does not match the expected SHA256')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    metrics=json.loads((dataset_path/'metrics.json').read_text(encoding='utf-8'))
    dsus=json.loads(dsus_path.read_text(encoding='utf-8'))
    if manifest.get('version')!=1 or not manifest.get('wells') or not manifest.get('tiles'):
        raise ValueError('Expected a prepared version-1 survey dataset')
    if len(manifest.get('origin',[]))!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in manifest['origin']):
        raise ValueError('Survey origin must contain two finite geographic coordinates')
    if not -180<=manifest['origin'][0]<=180 or not -90<=manifest['origin'][1]<=90:
        raise ValueError('Survey origin is outside geographic longitude/latitude limits')
    if len({tile['id'] for tile in manifest['tiles']})!=len(manifest['tiles']):
        raise ValueError('Duplicate survey tile IDs')
    if len({tile['id'] for tile in metrics['tiles']})!=len(metrics['tiles']):
        raise ValueError('Duplicate metric tile IDs')
    if {tile['id'] for tile in manifest['tiles']}!={tile['id'] for tile in metrics['tiles']}:
        raise ValueError('Survey and metric tile IDs do not match')
    metric_tile_index={tile['id']:tile for tile in metrics['tiles']}
    if any(metric_tile_index[tile['id']]['count']!=tile['stations'] for tile in manifest['tiles']):
        raise ValueError('Survey and metric tile station counts do not match')
    if sum(tile['stations'] for tile in manifest['tiles'])!=manifest['stations']:
        raise ValueError('Survey tile counts do not sum to the manifest station count')
    input_paths=[dsus_path,manifest_path,dataset_path/'metrics.json',helpers_path,
                 *(township_path.with_suffix('.'+suffix) for suffix in ('shp','shx','dbf','prj')),
                 *(dataset_file(dataset_path,tile['file']) for tile in manifest['tiles']),
                 *(dataset_file(dataset_path,tile['file']) for tile in metrics['tiles'])]
    if membership_path is not None: input_paths.append(membership_path)
    guard_output_inputs(output_dir,input_paths)
    helpers=load_membership_helpers(helpers_path)
    if manifest['sourceCRS']!='NAD83' or dsus['metadata']['sourceCRS']!='EPSG:4269':
        raise ValueError('Survey and DSUs must share NAD83')
    if not (metrics['stride']==8 and metrics['stations']==manifest['stations'] and
            metrics['branchCount']==len(manifest['wells']) and metrics['source']['origin']==manifest['origin'] and
            metrics['source']['sourceCRS']==manifest['sourceCRS'] and
            metrics['source']['datasetManifestSHA256']==manifest_hash and
            any(field.get('index')==0 and field.get('name')=='mdFt' and field.get('unit')=='ft' for field in metrics.get('fields',[]))):
        raise ValueError('Measured-depth metric index does not match the survey snapshot')
    project=geographic_projector();from_viewer=viewer_projector(manifest['origin'])
    features=dsus['features'];ids=[f['id'] for f in features]
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate DSU viewer IDs')
    if not features or any(not isinstance(feature_id,str) or not feature_id for feature_id in ids):
        raise ValueError('DSUs need nonempty stable string IDs')
    dsu_geometry_sha=canonical_sha([[f['id'],f['geometry']] for f in features])
    membership_matches=None
    if membership_path is not None:
        prior=json.loads(membership_path.read_text(encoding='utf-8'))
        membership_matches=(prior.get('sourceHashes',{}).get('dsuGeometryAndIdsSha256')==dsu_geometry_sha and
                            prior.get('sourceHashes',{}).get('manifestSha256')==manifest_hash)
        if not membership_matches:
            raise ValueError('Membership sidecar does not match the source DSU geometry and survey snapshot')
    dsu_polygons=np.asarray([project_geometry(shape(f['geometry']),project) for f in features],dtype=object)
    eligible=np.asarray([str(f['properties'].get('formation') or '').strip().casefold()=='bakken' for f in features])
    if not shapely.is_valid(dsu_polygons).all(): raise ValueError('Invalid projected original DSU geometry')
    # Union removes duplicate/overlapping source polygons without assigning the
    # same land to whichever legal DSU happens to precede another.
    eligible_union=shapely.union_all(dsu_polygons[eligible])
    towns,town_props,town_info=read_townships(township_path)
    town_ids=list(towns)
    town_polygons=np.asarray([project_geometry(towns[key],project) for key in town_ids],dtype=object)
    town_eligible=shapely.intersection(town_polygons,eligible_union)
    if not shapely.is_valid(town_eligible).all(): raise ValueError('Invalid clipped eligible township footprint')
    timings['read_project_union_seconds']=time.perf_counter()-start
    phase=time.perf_counter()
    by_tile=collections.defaultdict(list);well_meta={}
    for index,branch in enumerate(manifest['wells']):
        if branch['id']!=index: raise ValueError('Branch ID/index mismatch')
        key,permit,api10=helpers.well_identity(branch)
        well_meta.setdefault(key,{'permit':permit,'api10':api10,'branch_ids':[]})['branch_ids'].append(index)
        by_tile[branch['tile']].append(branch)
    if set(by_tile)-{tile['id'] for tile in manifest['tiles']}:
        raise ValueError('A survey branch references an unlisted tile')
    permit_apis=collections.defaultdict(set)
    for record in well_meta.values():permit_apis[record['permit']].add(record['api10'])
    if any(len(apis)>1 for apis in permit_apis.values()):
        raise ValueError('One permit maps to multiple API10 identities; resolve before grouping footage')
    counters=collections.Counter();source_branches=[];branch_well_keys=[];well_branch_indexes=collections.defaultdict(list)
    tile_hashes=[];metric_files={t['id']:t['file'] for t in metrics['tiles']}
    for tile in manifest['tiles']:
        geometry_path=dataset_file(dataset_path,tile['file']);metric_path=dataset_file(dataset_path,metric_files[tile['id']])
        stations=np.fromfile(geometry_path,dtype='<f4').reshape((-1,4))
        measured=np.fromfile(metric_path,dtype='<f4').reshape((-1,8))
        if len(stations)!=tile['stations'] or len(measured)!=len(stations): raise ValueError('Incomplete station/MD tile')
        expected=0
        for branch in sorted(by_tile[tile['id']],key=lambda b:b['offset']):
            first=branch['offset'];last=first+branch['count']
            if not isinstance(first,int) or not isinstance(branch['count'],int) or branch['count']<=0 or first!=expected or last>len(stations):
                raise ValueError('Branch offsets do not cover source tile exactly')
            expected=last
            line=helpers.lateral_geometry(stations[first:last],measured[first:last,0],counters)
            if line is not None and line.length>0:
                key=helpers.well_identity(branch)[0]
                well_branch_indexes[key].append(len(source_branches));source_branches.append(line);branch_well_keys.append(key)
        if expected!=len(stations): raise ValueError('Unindexed source stations')
        tile_hashes.append({'id':tile['id'],'geometry_sha256':sha_file(geometry_path),'metrics_sha256':sha_file(metric_path)})
    well_keys=sorted(well_branch_indexes)
    # Exact shared/retraced source XY is unioned before the nonlinear projection;
    # independently sampled shared source segments cannot become duplicate curved
    # projection chords merely because their station subdivisions differ.
    source_wells=[helpers.merged_well_geometry([source_branches[i] for i in well_branch_indexes[key]]) for key in well_keys]
    well_geometries=np.asarray([shapely.union_all([project_geometry(line,from_viewer)]) for line in source_wells],dtype=object)
    branch_geometries=np.asarray([project_geometry(line,from_viewer) for line in source_branches],dtype=object)
    if not shapely.is_valid(well_geometries).all(): raise ValueError('Invalid projected well linework')
    timings['read_deduplicate_project_surveys_seconds']=time.perf_counter()-phase
    phase=time.perf_counter()
    dsu_ft,dsu_wells,dsu_branches,_=group_observations(dsu_polygons[eligible],well_geometries,branch_geometries)
    town_ft,town_wells,town_branches,town_members=group_observations(town_eligible,well_geometries,branch_geometries)
    timings['clip_group_observations_seconds']=time.perf_counter()-phase
    phase=time.perf_counter()
    dsu_records={};position=0
    for index,feature in enumerate(features):
        supported=bool(eligible[index]);props=feature['properties']
        record={'id':feature['id'],'label':props.get('label',feature['id']),'eligible':supported,
                'eligibility_status':'source_bakken_mask' if supported else 'unknown_source_formation',
                'formation':props.get('formation'),'full_acres':float(dsu_polygons[index].area/SQM_PER_ACRE),
                'eligible_acres':float(dsu_polygons[index].area/SQM_PER_ACRE) if supported else None,
                'mapped_lateral_ft':round_number(dsu_ft[position]) if supported else None,
                'observed_wells':int(dsu_wells[position]) if supported else None,
                'observed_lateral_branches':int(dsu_branches[position]) if supported else None}
        dsu_records[feature['id']]=record
        if supported: position+=1
    town_records={};town_features=[]
    for index,key in enumerate(town_ids):
        acres=float(town_eligible[index].area/SQM_PER_ACRE)
        # Area is a source-mask classification, not an assessment of geological
        # prospectivity outside the existing public spacing polygons.
        supported=acres>0
        record={'id':key,**town_props[key],'eligible':supported,
                'eligibility_status':'source_bakken_mask' if supported else 'outside_dataset_mask',
                'full_acres':float(town_polygons[index].area/SQM_PER_ACRE),'eligible_acres':acres,
                'mapped_lateral_ft':round_number(town_ft[index]),'observed_wells':int(town_wells[index]),
                'observed_lateral_branches':int(town_branches[index])}
        town_records[key]=record
        town_features.append({'type':'Feature','id':key,'properties':record,'bbox':list(towns[key].bounds),'geometry':mapping(towns[key])})
    # Measure actual PLSS gaps/overlaps rather than silently forcing a partition.
    union_towns=shapely.union_all(town_polygons)
    eligible_town_union=shapely.union_all(town_eligible)
    covered_by_town_union=shapely.intersection(union_towns,eligible_union)
    difference_area=float(shapely.symmetric_difference(eligible_town_union,covered_by_town_union).area)
    if difference_area>max(1e-3,eligible_union.area*1e-10): raise ValueError('Eligible township footprint union does not conserve intersection')
    eligible_area=float(eligible_union.area/SQM_PER_ACRE)
    covered_area=float(eligible_town_union.area/SQM_PER_ACRE)
    summed_town_area=float(shapely.area(town_eligible).sum()/SQM_PER_ACRE)
    mask_ft=total_clipped_ft(well_geometries,eligible_union)
    covered_ft=total_clipped_ft(well_geometries,eligible_town_union)
    summed_town_ft=float(town_ft.sum())
    area_gap=max(0.0,eligible_area-covered_area)
    area_overlap=max(0.0,summed_town_area-covered_area)
    footage_gap=max(0.0,mask_ft-covered_ft)
    footage_overlap=max(0.0,summed_town_ft-covered_ft)
    sliver_mask=(shapely.area(town_eligible)>0)&(shapely.area(town_eligible)<=1)
    if covered_area>eligible_area+1e-4 or covered_ft>mask_ft+1e-3 or summed_town_ft<covered_ft-1e-3:
        raise ValueError('Inconsistent township coverage accounting')
    coverage={'usable_wells':len(well_geometries),'unusable_wells':len(well_meta)-len(well_geometries),
              'usable_lateral_branches':len(branch_geometries),'all_targets_unverified':True,
              'completion_intervals_unverified':True,'observed_footage_is_completeness_claim':False,
              'dsus_with_observed_wells':sum(bool(r['observed_wells']) for r in dsu_records.values()),
              'townships_with_eligible_area':sum(r['eligible'] for r in town_records.values()),
              'townships_with_eligible_area_over_1sqm':int((shapely.area(town_eligible)>1).sum()),
              'township_positive_slivers_at_most_1sqm':int(sliver_mask.sum()),
              'township_sliver_total_acres':float(shapely.area(town_eligible[sliver_mask]).sum()/SQM_PER_ACRE),
              'township_sliver_mapped_lateral_ft':float(town_ft[sliver_mask].sum()),
              'townships_with_observed_wells':sum(bool(r['observed_wells']) for r in town_records.values()),
              'eligible_union_acres':eligible_area,'township_covered_eligible_union_acres':covered_area,
              'township_gap_acres':area_gap,'township_gap_fraction':area_gap/eligible_area,
              'township_overlap_acres_in_summed_groups':area_overlap,'township_overlap_fraction':area_overlap/eligible_area,
              'eligible_union_mapped_lateral_ft':mask_ft,'township_union_mapped_lateral_ft':covered_ft,
              'sum_township_mapped_lateral_ft':summed_town_ft,
              'township_gap_mapped_lateral_ft':footage_gap,'township_overlap_mapped_lateral_ft_in_summed_groups':footage_overlap,
              'township_union_intersection_symmetric_difference_sqm':difference_area,
              'source_segment_exclusions':dict(counters)}
    method={'area_crs':AREA_CRS,'source_geographic_crs':'EPSG:4269','length_units':'ft','area_units':'acres',
            'footage_label':'Mapped classified lateral plan footage','population':'All mapped source lateral branches; targets and completion status unverified.',
            'interpretation':'Observed drilling-geometry proxy, not verified completed footage, percent oil depleted, reserves, EUR or reviewed feasible inventory.',
            'source_sections':'Segments ending at classifier section 4 (Lateral), matching existing viewer rendering.',
            'source_gap_policy':'Exclude missing/nonincreasing MD, nonfinite XYZ, MD gaps >1000 ft and zero horizontal steps; never bridge rejected intervals.',
            'projection':'Invert source GRS80 surface tangent east/south coordinates by near-side ellipsoid intersection; transform recovered NAD83 longitude/latitude to EPSG:5070.',
            'deduplication':'Exact shared/retraced XY linework is unioned within each permit+API10 well before projection; separate wells remain separate.',
            'clipping':'Exact positive-length line intersection with original source DSU footprints; display insets/depth boxes ignored.',
            'dsu_aggregation':'Each DSU independently measured; overlapping/duplicate DSU rows and their footage are nonadditive. No statewide DSU sum is published.',
            'township_aggregation':'Dissolve all supplied township/range/direction fragments; clip their full boundaries to the union of reported-Bakken DSUs, then clip each whole-well line once per resulting footprint.',
            'township_gaps_overlaps':'Source PLSS gaps/overlaps are measured and reported, not repaired or forced to a gapless partition.',
            'eligibility':'Reported DSU formation exactly Bakken after trim/case normalization. This public spacing footprint mask is not a verified prospective target mask.',
            'unknown_formation':'Withhold acreage/footage/count metrics for the unexpected source formation; do not silently include it as Bakken.',
            'minimum_positive_overlap_ft':MIN_OVERLAP_FT,
            'limitations':['Surveyed branches may be abandoned, sidetracked, uncompleted or completed in different targets; no completion ledger was supplied.',
                'Plan-view within-well union may collapse coincident stacked branches when their distinct targets cannot be verified.',
                'Source station coordinates are Float32; returned NAD83 coordinates retain that quantization.',
                'Townships without published-Bakken DSU coverage are outside this dataset mask, not proven nonprospective or undeveloped.',
                'Raw supplied township keys lack principal-meridian identity; no missing meridian is invented.',
                'Observed counts describe mapped overlap only and do not establish complete well coverage.',
                'No density, optimum spacing, remaining-footage, developed-percent or reserves assumption is embedded in these observations.']}
    survey={'manifest_sha256':manifest_hash,'stations':manifest['stations'],'branch_count':len(manifest['wells']),
            'well_count':len(well_meta),'origin':manifest['origin'],'source_crs':manifest['sourceCRS'],
            'source_date':manifest.get('sourceSnapshot',{}).get('date')}
    source_hashes={'dsu_file_sha256':sha_file(dsus_path),'dsu_geometry_sha256':dsu_geometry_sha,
                   'survey_manifest_sha256':manifest_hash,'survey_metrics_manifest_sha256':sha_file(dataset_path/'metrics.json'),
                   'survey_geometry_tiles_sha256':canonical_sha([[h['id'],h['geometry_sha256']] for h in tile_hashes]),
                   'survey_metrics_tiles_sha256':canonical_sha([[h['id'],h['metrics_sha256']] for h in tile_hashes]),
                   'membership_geometry_helper_sha256':sha_file(helpers_path),
                   **{f'township_source_{suffix}_sha256':sha_file(township_path.with_suffix('.'+suffix)) for suffix in ('shp','shx','dbf','prj')}}
    if membership_path is not None: source_hashes['existing_membership_sha256']=sha_file(membership_path)
    towns_geojson={'type':'FeatureCollection','name':'North Dakota full dissolved township boundaries',
                    'metadata':{'sourceCRS':'EPSG:4269','footage_manifest_sha256':manifest_hash,
                                'footage_schema_version':1,'source_shapefile_sha256':source_hashes['township_source_shp_sha256'],
                                'featureCount':len(town_features),'eligibleMask':'Union of reported-Bakken source DSU footprints; measurements supplied separately.',
                                'geometryMeaning':'Full dissolved township boundaries, not clipped eligible footprints.','sourceFragmentCount':town_info['fragments']},
                    'features':town_features}
    town_path=output_dir/'townships.geojson'
    output_dir.mkdir(parents=True,exist_ok=True)
    town_path.write_text(json.dumps(towns_geojson,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    source_hashes['townships_geojson_sha256']=sha_file(town_path)
    result={'version':1,'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'survey':survey,'source_hashes':source_hashes,'method':method,'coverage':coverage,
            'dsus':dsu_records,'townships':town_records}
    result_path=output_dir/'footage.json'
    result_path.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    timings['records_coverage_and_write_seconds']=time.perf_counter()-phase
    report={'survey':survey,'source_hashes':source_hashes,'coverage':coverage,'township_source':town_info,
            'dsu_source_records':len(features),'eligible_dsu_records':int(eligible.sum()),
            'township_full_geometries_retained':len(town_features),'output_bytes':{result_path.name:result_path.stat().st_size,town_path.name:town_path.stat().st_size},
            'timings_seconds':timings,'total_seconds':time.perf_counter()-start,
            'canonical_dsu_geometry_digest_matches_existing_membership':membership_matches}
    (output_dir/'build-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    (output_dir/'source-hashes.json').write_text(json.dumps({'input_paths':{'dsus':str(dsus_path.resolve()),'dataset':str(dataset_path.resolve()),'township':str(township_path.resolve()),'helpers':str(pathlib.Path(helpers_path).resolve())},
        'hashes':source_hashes,'survey_chunks':tile_hashes},indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_hashes'},indent=2))
    return result,towns_geojson


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsus',required=True,help='Prepared source DSU GeoJSON with stable IDs and EPSG:4269 metadata.')
    parser.add_argument('--dataset',required=True,help='Prepared NAD83 dataset folder containing manifest.json, metrics.json and aligned binary tiles.')
    parser.add_argument('--townships',required=True,help='NAD83 Township shapefile with TOWNSHIP, TDIR, RANGE and RDIR fields.')
    parser.add_argument('--output-dir',required=True,help='Destination for footage.json, full-boundary townships.geojson and local audit reports.')
    parser.add_argument('--helpers',default=str(REPO_ROOT/'prepare_dsu_membership.py'),help='Membership geometry helper; defaults to the sibling public preparer.')
    parser.add_argument('--expected-manifest-sha256',help='Optional exact survey manifest fingerprint; all metric-alignment checks still apply when omitted.')
    parser.add_argument('--membership',help='Optional existing DSU membership sidecar to verify against both DSU geometry and survey manifest.')
    args=parser.parse_args()
    build(args.dsus,args.dataset,args.townships,args.output_dir,args.helpers,args.expected_manifest_sha256,args.membership)
