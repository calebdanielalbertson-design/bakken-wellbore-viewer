"""Depth-weighted native LAS interval means with relocatable, fingerprinted cache.

Call get_averaged_well(store, permit, source_id=None, interval_ft=100).
The detailed GammaStore/CBLStore endpoints remain unchanged. Source LAS files and
survey files are read only. Fixed measured-depth bins contain only valid, surveyed
piecewise-linear native intervals; NULL samples and unsupported gaps are excluded.
"""
from pathlib import Path
import collections, hashlib, inspect, json, math, os, tempfile
import numpy as np
import gamma_service as gamma

ALGORITHM_VERSION = 'native-depth-weighted-mean-v1'
CACHE_ROOT = Path(__file__).resolve().parent / 'averaged-cache'
_CODE_HASHES = {}

def _survey_ranges(survey, max_gap=1000.0):
    """Continuous supported MD ranges; no support across a large survey gap."""
    md = survey[:, 0]
    result = []; start = None; end = None
    for a, b in zip(md[:-1], md[1:]):
        if b <= a or b - a > max_gap:
            if start is not None: result.append((float(start), float(end)))
            start = end = None
            continue
        if start is None: start = a
        end = b
    if start is not None: result.append((float(start), float(end)))
    return result

def average_native_intervals(depth, values, interval_ft=100.0, survey_ranges=None, max_native_gap_ft=None):
    """Return fixed-MD bin means and exact supported fragments, without geometry.

    sampleCount counts finite native observations located inside that bin and a
    valid surveyed range. min/max are extrema of the supported linear signal
    inside the bin, including interpolated clipped boundaries. Native observations
    on a bin's right boundary belong to the next bin. These conventions avoid
    counting bracketing observations outside the requested interval as raw samples.
    """
    width = float(interval_ft)
    if not math.isfinite(width) or width <= 0: raise ValueError('Averaging interval must be positive')
    d = np.asarray(depth, dtype=float); v = np.asarray(values, dtype=float)
    if d.ndim != 1 or len(d) != len(v) or len(d) < 2: return []
    if not np.isfinite(d).all() or np.any(np.diff(d) <= 0): raise ValueError('Native depths must be finite and strictly increasing')
    native_step = float(np.median(np.diff(d)))
    max_gap = max(1e-3, native_step * 2.1) if max_native_gap_ft is None else float(max_native_gap_ft)
    valid = np.isfinite(v[:-1]) & np.isfinite(v[1:]) & (np.diff(d) <= max_gap)
    source_ids = np.flatnonzero(valid)
    if not len(source_ids): return []
    supplied_ranges = survey_ranges if survey_ranges is not None else [(float(d[0]), float(d[-1]))]
    ranges=[]
    for left,right in sorted((float(left),float(right)) for left,right in supplied_ranges):
        if not math.isfinite(left) or not math.isfinite(right):raise ValueError('Survey ranges must be finite')
        if right<=left:continue
        if ranges and left<=ranges[-1][1]+1e-8:ranges[-1][1]=max(ranges[-1][1],right)
        else:ranges.append([left,right])
    starts = []; ends = []; lows = []; highs = []; ids = []
    for range_a, range_b in ranges:
        if range_b <= range_a: continue
        a = np.maximum(d[source_ids], range_a); b = np.minimum(d[source_ids + 1], range_b)
        keep = b - a > 1e-9
        if not keep.any(): continue
        ii = source_ids[keep]; aa, bb = a[keep], b[keep]
        slope = (v[ii + 1] - v[ii]) / (d[ii + 1] - d[ii])
        va = v[ii] + slope * (aa - d[ii]); vb = v[ii] + slope * (bb - d[ii])
        # Most native intervals fit in one bin. Only boundary-crossing intervals
        # need scalar splitting; the large native arrays remain vectorized.
        ba = np.floor(aa / width).astype(np.int64)
        bz = np.floor(np.nextafter(bb, -np.inf) / width).astype(np.int64)
        same = ba == bz
        starts.append(aa[same]); ends.append(bb[same]); lows.append(va[same]); highs.append(vb[same]); ids.append(ii[same])
        split_a=[];split_b=[];split_va=[];split_vb=[];split_ids=[]
        for j in np.flatnonzero(~same):
            knots = [float(aa[j])] + [k * width for k in range(int(ba[j]) + 1, int(bz[j]) + 1)] + [float(bb[j])]
            for left, right in zip(knots[:-1], knots[1:]):
                if right - left <= 1e-9: continue
                split_a.append(left);split_b.append(right)
                split_va.append(float(va[j] + slope[j] * (left - aa[j])))
                split_vb.append(float(va[j] + slope[j] * (right - aa[j])))
                split_ids.append(int(ii[j]))
        if split_a:
            starts.append(np.asarray(split_a));ends.append(np.asarray(split_b));lows.append(np.asarray(split_va));highs.append(np.asarray(split_vb));ids.append(np.asarray(split_ids,dtype=np.int64))
    if not starts: return []
    a=np.concatenate(starts);b=np.concatenate(ends);va=np.concatenate(lows);vb=np.concatenate(highs);ii=np.concatenate(ids)
    order=np.argsort(a,kind='stable');a,b,va,vb,ii=a[order],b[order],va[order],vb[order],ii[order]
    absolute_bins=np.floor(a/width).astype(np.int64);unique_bins,inverse=np.unique(absolute_bins,return_inverse=True)
    lengths=b-a;coverage=np.bincount(inverse,weights=lengths,minlength=len(unique_bins));area=np.bincount(inverse,weights=(va+vb)*.5*lengths,minlength=len(unique_bins))
    minimum=np.full(len(unique_bins),np.inf);maximum=np.full(len(unique_bins),-np.inf)
    np.minimum.at(minimum,inverse,np.minimum(va,vb));np.maximum.at(maximum,inverse,np.maximum(va,vb))
    # Count native samples that lie in supported geometry and participate in one
    # of the valid source intervals. Final right-boundary samples are not duplicated.
    participating=np.zeros(len(d),dtype=bool);participating[ii]=True;participating[ii+1]=True
    in_survey=np.zeros(len(d),dtype=bool)
    for left,right in ranges:in_survey|=(d>=left)&(d<=right)
    sample_depth=d[participating&in_survey&np.isfinite(v)]
    sample_bins=np.floor(sample_depth/width).astype(np.int64)
    sample_counts=collections.Counter(sample_bins.tolist())
    fragments=[[] for _ in unique_bins]
    for left,right,bin_i in zip(a,b,inverse):
        ranges_here=fragments[int(bin_i)]
        if ranges_here and left<=ranges_here[-1][1]+1e-8:ranges_here[-1][1]=max(ranges_here[-1][1],float(right))
        else:ranges_here.append([float(left),float(right)])
    result=[]
    for j,number in enumerate(unique_bins):
        if coverage[j]<=0:continue
        result.append({'startMD':round(float(number*width),6),'endMD':round(float((number+1)*width),6),'mean':round(float(area[j]/coverage[j]),8),
                       'coverageFraction':round(min(1.0,float(coverage[j]/width)),8),'coverageFt':round(float(coverage[j]),6),
                       'min':round(float(minimum[j]),8),'max':round(float(maximum[j]),8),'sampleCount':int(sample_counts.get(int(number),0)),
                       'validRanges':[[round(left,6),round(right,6)] for left,right in fragments[j]]})
    return result

def _file_stamp(path):
    path=Path(path);stat=path.stat()
    return {'path':str(path.resolve()),'bytes':stat.st_size,'mtimeNs':stat.st_mtime_ns}

def _code_hash(path):
    path=Path(path);stamp=(str(path),path.stat().st_size,path.stat().st_mtime_ns)
    if stamp not in _CODE_HASHES:_CODE_HASHES[stamp]=hashlib.sha256(path.read_text(encoding='utf8').encode('utf8')).hexdigest()
    return _CODE_HASHES[stamp]

def _selected_source(store,permit,source_id):
    well=store.get_sources(str(permit))
    if not well:raise ValueError('No eligible log source for FileNo '+str(permit))
    wanted=source_id or well['defaultSourceId']
    source=next((s for s in well['sources'] if s['id']==wanted or s['file']==wanted),None)
    if source is None:raise ValueError('Selected log source is unavailable')
    if source['errors']:raise ValueError('; '.join(source['errors']))
    return well,source

def cache_identity(store,permit,source_id=None,interval_ft=100):
    well,source=_selected_source(store,str(permit),source_id)
    kind=store.catalog.get('measurementKind','gamma')
    fingerprint={'algorithm':ALGORITHM_VERSION,'measurement':kind,'intervalFt':float(interval_ft),'permit':str(permit),
                 'sourceId':source['id'],'source':_file_stamp(gamma.LAS/source['file']),'survey':_file_stamp(gamma.DBF),
                 'origin':store.catalog['origin'],'api10s':well['api10s'],
                 'columns':{k:source.get(k) for k in ('curveIndex','depthIndex','curveCount','unit','depthUnit','null','wrap','identityStatus','api10s')},
                 'parserHash':_code_hash(inspect.getfile(gamma.GammaStore)), 'storeHash':_code_hash(inspect.getfile(type(store))),
                 'averagingHash':_code_hash(__file__)}
    key=hashlib.sha256(json.dumps(fingerprint,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return key,fingerprint

def _build_points(bins,survey,xyz):
    """One mesh-ready sequence per survey branch, with explicit NULL gap markers."""
    fragments=[(bounds[0],bounds[1],index,item['mean']) for index,item in enumerate(bins) for bounds in item['validRanges']]
    fragments.sort(key=lambda x:x[0]);points=[];point_bins=[];previous_end=None;previous_length=None
    def point(md,value):
        coords=[float(np.interp(md,survey[:,0],xyz[:,j])) for j in range(3)]
        return [round(x,6) for x in coords]+[round(float(md),6),value]
    for start,end,index,mean in fragments:
        left=start;right=end
        if previous_end is not None:
            if start-previous_end>1e-7:
                marker=points[-1][:];marker[3]=round((previous_end+start)/2,6);marker[4]=None
                points.append(marker);point_bins.append(-1)
            else:
                epsilon=min(.0005,previous_length/4,(end-start)/4)
                points[-1]=point(previous_end-epsilon,points[-1][4]);left=start+epsilon
        points.append(point(left,mean));point_bins.append(index)
        points.append(point(right,mean));point_bins.append(index)
        previous_end=end;previous_length=end-start
    return points,point_bins

def _compute(store,permit,source_id,interval_ft):
    permit=str(permit);well,source=_selected_source(store,permit,source_id)
    geometry=store._survey(permit)
    if not geometry:raise ValueError('No observed VERT survey branch for this FileNo')
    d,v,stats,flags=store._read_curve(source)
    paths=[];means=[];coverage=0;count=0
    for branch,api,survey in geometry:
        if api not in well['api10s']:continue
        if source['api10s'] and api not in source['api10s']:continue
        ranges=_survey_ranges(survey)
        bins=average_native_intervals(d,v,interval_ft,survey_ranges=ranges)
        if not bins:continue
        xyz=store._project(survey);points,point_bins=_build_points(bins,survey,xyz)
        means.extend(item['mean'] for item in bins);coverage+=sum(item['coverageFt'] for item in bins)
        count+=sum(p[4] is not None for p in points)
        paths.append({'branch':branch,'api10':api,'points':points,'pointBinIndices':point_bins,'bins':bins,
                      'surveyMDRange':[float(survey[0,0]),float(survey[-1,0])],
                      'loggedMDRange':[float(min(r[0] for item in bins for r in item['validRanges'])),float(max(r[1] for item in bins for r in item['validRanges']))],
                      'surveyStations':len(survey)})
        if np.any(np.diff(survey[:,0])>1000):flags.append('Averages exclude survey gaps exceeding 1000 ft')
    if not paths:raise ValueError('No valid native log interval overlaps a matching observed VERT survey')
    kind=store.catalog.get('measurementKind','gamma');label=store.catalog.get('measurement','Gamma ray');unit='mV' if kind=='cbl_amplitude' else source['unit']
    flags=[flag.replace('Raw source gamma values','Source gamma readings').replace('Raw source CBL amplitude values','Source CBL amplitude readings').replace('Raw amplitude in mV','Source amplitude in mV') for flag in flags]
    stats.update({'displaySamples':sum(len(p['points']) for p in paths),'validDisplaySamples':count,'displayStepFt':float(interval_ft),
                  'averagedBins':len(means),'coveredMDLengthFt':round(coverage,6),
                  'partialBins':sum(item['coverageFraction']<.999999 for p in paths for item in p['bins']),
                  'percentiles':{str(q):round(float(x),6) for q,x in zip([0,2,5,50,95,98,100],np.percentile(means,[0,2,5,50,95,98,100]))}})
    result={'version':1,'permit':permit,'api10':paths[0]['api10'],'source':source,'unit':unit,'depthUnit':'ft',
            'measurement':label,'measurementLabel':label,'measurementKind':kind,'reference':gamma.REFERENCE,'origin':store.catalog['origin'],
            'paths':paths,'stats':stats,'flags':sorted(set(flags)),
            'sampling':f'{interval_ft:g}-ft measured-depth bins; depth-weighted means integrated from valid native samples; NULL and unsupported depth gaps remain open',
            'geometryScope':'Observed VERT survey branch as stored; may include directional stations',
            'aggregation':{'intervalFt':float(interval_ft),'method':'depth-weighted mean','algorithmVersion':ALGORITHM_VERSION,'nativeInterpolation':'piecewise linear',
                           'binOriginMD':0,'boundaryTransitionFt':.001,'coverageDefinition':'Valid integrated MD length divided by nominal bin width',
                           'rangeDefinition':'Minimum/maximum supported linear signal inside the bin',
                           'sampleCountDefinition':'Finite native observations inside the half-open bin and supported survey range'}}
    return result

def get_averaged_well(store,permit,source_id=None,interval_ft=100):
    """Return the fingerprinted cached API artifact; cache is beside this module."""
    width=float(interval_ft)
    if not math.isfinite(width) or width<1 or width>10000:raise ValueError('Averaging interval must be between 1 and 10000 ft')
    key,fingerprint=cache_identity(store,permit,source_id,width)
    target=CACHE_ROOT/(key+'.json')
    if target.exists():
        try:return json.loads(target.read_text(encoding='utf8'))
        except (OSError,ValueError):pass
    result=_compute(store,permit,source_id,width)
    result['aggregation']['cacheKey']=key
    CACHE_ROOT.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix=key+'-',suffix='.tmp',dir=CACHE_ROOT)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as file:json.dump(result,file,separators=(',',':'),allow_nan=False)
        os.replace(temporary,target)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    return result
