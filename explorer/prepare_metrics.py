"""Create survey metrics aligned exactly to an existing local well-viewer dataset.

Usage: python prepare_metrics.py SOURCE.dbf EXISTING_DATASET OUTPUT_FOLDER
The DBF and existing geometry are opened read-only and never rewritten.
Requires numpy and pandas; uses a disk-backed sort, matching prepare_data.py.
"""
import argparse
import hashlib
import heapq
import json
import math
from pathlib import Path
import sqlite3
import struct
import time

import numpy as np
import pandas as pd

FIELD_NAMES = ['mdFt', 'inclinationDeg', 'azimuthDeg', 'doglegDegPer100Ft',
               'buildDegPer100Ft', 'turnDegPer100Ft', 'tortuosityRatio', 'departureFt']
UNITS = ['ft', 'deg', 'deg', 'deg/100 ft', 'deg/100 ft', 'deg/100 ft', 'ratio', 'ft']
STRIDE = 8
GAP_FT = 1000.0
WINDOW_FT = 1000.0
MIN_WINDOW_FT = 500.0
AZIMUTH_MIN_INC = 5.0
GEOMETRY_EPSILON_FT = 1e-6


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def dbf_rows(path):
    with Path(path).open('rb') as stream:
        header = stream.read(32)
        count = struct.unpack_from('<I', header, 4)[0]
        start, step = struct.unpack_from('<HH', header, 8)
        fields = []
        for _ in range((start - 33) // 32):
            descriptor = stream.read(32)
            fields.append((descriptor[:11].split(b'\0')[0].decode().lower(), 'S' + str(descriptor[16])))
    dtype = np.dtype([('_deleted', 'S1')] + fields)
    if dtype.itemsize != step:
        raise ValueError('Unsupported DBF record layout')
    return np.memmap(path, dtype=dtype, mode='r', offset=start, shape=(count,))


def projection(manifest):
    """The converter's ellipsoidal ECEF tangent east/north projection, in feet."""
    a = 6378137.0
    flattening = 1 / (298.257222101 if manifest['sourceCRS'] == 'NAD83' else 298.257223563)
    e2 = flattening * (2 - flattening)
    lo, la = map(math.radians, manifest['origin'])
    nn = a / math.sqrt(1 - e2 * math.sin(la) ** 2)
    origin = np.array([nn*math.cos(la)*math.cos(lo), nn*math.cos(la)*math.sin(lo), nn*(1-e2)*math.sin(la)])
    east = np.array([-math.sin(lo), math.cos(lo), 0])
    north = np.array([-math.sin(la)*math.cos(lo), -math.sin(la)*math.sin(lo), math.cos(la)])

    def project(lon, lat, tvd):
        lon, lat = np.radians(lon), np.radians(lat)
        nn = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
        xyz = np.stack([nn*np.cos(lat)*np.cos(lon), nn*np.cos(lat)*np.sin(lon), nn*(1-e2)*np.sin(lat)], axis=1) - origin
        x = xyz @ east / .3048
        z = -(xyz @ north) / .3048
        return np.stack([x, -np.abs(tvd), z], axis=1)
    return project


def tortuosity(md, xyz):
    """Interpolated +/-500 ft MD windows, clipped at branch and >1000 ft gaps.

    At least 500 ft MD coverage and three distinct geometry points are required.
    The numerator is geometric polyline length, not measured-depth difference.
    """
    result = np.full(len(md), np.nan, dtype=np.float64)
    breaks = np.r_[0, np.flatnonzero(np.diff(md) > GAP_FT) + 1, len(md)]
    for begin, end in zip(breaks[:-1], breaks[1:]):
        d, p = md[begin:end], xyz[begin:end]
        if len(d) < 3 or d[-1]-d[0] < MIN_WINDOW_FT:
            continue
        arc = np.r_[0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
        lower = np.maximum(d[0], d - WINDOW_FT/2)
        upper = np.minimum(d[-1], d + WINDOW_FT/2)
        low_xyz = np.column_stack([np.interp(lower, d, p[:, j]) for j in range(3)])
        high_xyz = np.column_stack([np.interp(upper, d, p[:, j]) for j in range(3)])
        length = np.interp(upper, d, arc) - np.interp(lower, d, arc)
        chord = np.linalg.norm(high_xyz-low_xyz, axis=1)
        first_inside = np.searchsorted(d, lower, side='right')
        end_inside = np.searchsorted(d, upper, side='left')
        first_points = p[np.minimum(first_inside, len(d)-1)]
        distinct = (first_inside < end_inside) & (np.linalg.norm(first_points-low_xyz, axis=1) > GEOMETRY_EPSILON_FT) & (np.linalg.norm(first_points-high_xyz, axis=1) > GEOMETRY_EPSILON_FT)
        # Usually the first interior point establishes three distinct points.
        # Inspect the exceptional repeated-position windows without a quadratic
        # loop over the ordinary survey data.
        unresolved = np.flatnonzero((first_inside < end_inside) & ~distinct)
        for index in unresolved:
            inner = p[first_inside[index]:end_inside[index]]
            distinct[index] = np.any((np.linalg.norm(inner-low_xyz[index], axis=1) > GEOMETRY_EPSILON_FT) & (np.linalg.norm(inner-high_xyz[index], axis=1) > GEOMETRY_EPSILON_FT))
        valid = (upper-lower >= MIN_WINDOW_FT) & (chord > GEOMETRY_EPSILON_FT) & distinct
        local = np.full(len(d), np.nan)
        local[valid] = np.maximum(1.0, length[valid]/chord[valid])
        result[begin:end] = local
    return result


def station_metrics(md, inclination, azimuth, xyz):
    n = len(md)
    if len(xyz) != n or np.any(np.diff(md) <= 0):
        raise ValueError('Metrics require a single branch with strictly increasing MD')
    metrics = np.full((n, STRIDE), np.nan, dtype=np.float64)
    metrics[:, 0] = md
    metrics[:, 1] = inclination
    valid_azimuth = (azimuth >= 0) & (azimuth <= 360)
    metrics[:, 2] = np.where((inclination >= AZIMUTH_MIN_INC) & valid_azimuth, azimuth % 360, np.nan)
    dmd = np.diff(md)
    valid = (dmd > 0) & (dmd <= GAP_FT)
    inc, azi = np.radians(inclination), np.radians(azimuth)
    # Stable atan2(cross, dot) is mathematically the spherical acos dogleg;
    # it avoids tiny nonzero results for identical tangent vectors.
    tangent = np.column_stack([np.sin(inc)*np.sin(azi), np.sin(inc)*np.cos(azi), np.cos(inc)])
    angle = np.degrees(np.arctan2(np.linalg.norm(np.cross(tangent[:-1], tangent[1:]), axis=1), np.sum(tangent[:-1]*tangent[1:], axis=1)))
    valid_angular_interval = valid & valid_azimuth[:-1] & valid_azimuth[1:]
    metrics[1:, 3] = np.where(valid_angular_interval, angle*100/dmd, np.nan)
    metrics[1:, 4] = np.where(valid, np.diff(inclination)*100/dmd, np.nan)
    wrapped_turn = (np.diff(azimuth)+180) % 360 - 180
    valid_turn = valid_angular_interval & (inclination[:-1] >= AZIMUTH_MIN_INC) & (inclination[1:] >= AZIMUTH_MIN_INC)
    metrics[1:, 5] = np.where(valid_turn, wrapped_turn*100/dmd, np.nan)
    metrics[:, 6] = tortuosity(md, xyz)
    metrics[:, 7] = np.linalg.norm(xyz[:, [0, 2]]-xyz[0, [0, 2]], axis=1)
    return metrics


def overview_keep(section):
    return sorted(set([0, len(section)-1] + list(range(0, len(section), 12)) + [k for j in range(1, len(section)) if section[j] != section[j-1] for k in (j-1, j)]))


def aggregate_overview(metrics, keep):
    """Endpoint MD/inc/azi/departure; actual finite span peaks for other fields."""
    result = np.empty((len(keep)-1, STRIDE), dtype=np.float64)
    gaps = np.diff(metrics[:, 0]) > GAP_FT
    for index, (i, j) in enumerate(zip(keep[:-1], keep[1:])):
        result[index] = metrics[j]
        if np.any(gaps[i:j]):
            result[index, 3:7] = np.nan
            continue
        for col in (3, 4, 5, 6):
            values = metrics[(i if col == 6 else i+1):j+1, col]
            values = values[np.isfinite(values)]
            result[index, col] = values[np.argmax(np.abs(values))] if len(values) else np.nan
    return result


def statistics(arrays):
    answer = {}
    for index, (name, unit) in enumerate(zip(FIELD_NAMES, UNITS)):
        values = np.concatenate([a[:, index] for a in arrays])
        count = len(values)
        values = values[np.isfinite(values)]
        entry = {'unit': unit, 'finiteCount': len(values), 'undefinedCount': count-len(values)}
        if len(values):
            quantiles = np.quantile(values, [.01, .05, .5, .95, .99])
            entry.update(min=float(values.min()), max=float(values.max()), p01=float(quantiles[0]), p05=float(quantiles[1]), p50=float(quantiles[2]), p95=float(quantiles[3]), p99=float(quantiles[4]))
            entry['absP95'], entry['absP99'] = map(float, np.quantile(np.abs(values), [.95, .99]))
        else:
            entry.update({k: None for k in ['min','max','p01','p05','p50','p95','p99','absP95','absP99']})
        answer[name] = entry
    return answer


def section_metric_scales(manifest, geometry_tiles, metrics_tiles):
    """Exact finite full-resolution populations, grouped by geometry section.

    Tile arrays remain read-only inputs. Curvature is derived from DLS by the
    consumer and therefore does not duplicate a statistically identical field.
    """
    order = [tile['id'] for tile in manifest['tiles']]
    codes = np.concatenate([geometry_tiles[key][:, 3] for key in order])
    if len(codes) != manifest['stations']:
        raise ValueError('Section station population differs from manifest')
    if not np.isfinite(codes).all() or not np.array_equal(codes, codes.astype(np.int64)):
        raise ValueError('Geometry section labels must be finite integers')
    if np.any(codes < 0) or np.any(codes >= len(manifest['labels'])):
        raise ValueError('Geometry contains an unrecognized section label')
    codes = codes.astype(np.int8)
    sections = [{'id':i,'label':label,'stationCount':int((codes == i).sum()),'metrics':{}} for i,label in enumerate(manifest['labels'])]
    specifications = [('dls',3,'deg/100 ft'),('tortuosity',6,'ratio'),('inclination',1,'deg'),('azimuth',2,'deg'),('build',4,'deg/100 ft'),('turn',5,'deg/100 ft'),('tvd',None,'ft'),('md',0,'ft'),('departure',7,'ft')]
    for name,index,unit in specifications:
        values = (np.concatenate([np.abs(geometry_tiles[key][:,1]) for key in order]) if index is None else np.concatenate([metrics_tiles[key][:,index] for key in order]))
        if len(values) != len(codes):
            raise ValueError('Metrics station population differs from geometry')
        for section in sections:
            population = values[codes == section['id']]
            finite = population[np.isfinite(population)]
            result = {'count':len(finite),'missingCount':len(population)-len(finite)}
            if len(finite):
                p02,p98 = map(float,np.quantile(finite,[.02,.98],method='linear'))
                result.update(min=float(finite.min()),max=float(finite.max()),p02=p02,p98=p98,absP98=float(np.quantile(np.abs(finite),.98,method='linear')))
            else:
                result.update({key:None for key in ['min','max','p02','p98','absP98']})
            section['metrics'][name] = result
    if sum(section['stationCount'] for section in sections) != manifest['stations']:
        raise ValueError('Section counts do not sum to total stations')
    for section in sections:
        for name,stats in section['metrics'].items():
            if stats['count']+stats['missingCount'] != section['stationCount']:
                raise ValueError(f'Metric population mismatch: {section["label"]} / {name}')
            if stats['count'] and not (stats['min'] <= stats['p02'] <= stats['p98'] <= stats['max'] and stats['absP98'] >= 0):
                raise ValueError(f'Invalid quantile ordering: {section["label"]} / {name}')
    return {'version':1,'stations':manifest['stations'],'branchCount':len(manifest['wells']),'overviewSegments':manifest['overviewSegments'],'sourceCRS':manifest['sourceCRS'],'origin':manifest['origin'],
            'population':'Finite full-resolution station values grouped by the retained geometry section code; overview values are excluded.',
            'quantileMethod':'Exact NumPy quantile with linear interpolation; no sampling.',
            'units':{name:unit for name,index,unit in specifications},
            'curvatureConversion':'dls * pi / 18 yields radians per 1000 ft; apply to all DLS scale values.',
            'sections':sections}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    source, dataset, output = args.source.resolve(), args.dataset.resolve(), args.output.resolve()
    if output == dataset or output == source.parent:
        raise ValueError('Choose a separate output folder; original files are retained')
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = dataset/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest['source'] != source.name:
        raise ValueError('Source DBF does not match dataset manifest')
    project = projection(manifest)
    overview = np.memmap(dataset/'overview.bin', dtype='<f4', mode='r', shape=(manifest['overviewSegments'], STRIDE))
    overview_output = np.memmap(output/'overview.metrics.bin', dtype='<f4', mode='w+', shape=(len(overview), STRIDE))
    tiles = {t['id']: t for t in manifest['tiles']}
    originals, metric_tiles = {}, {}
    original_hash = hashlib.sha256()
    for tile in manifest['tiles']:
        originals[tile['id']] = np.memmap(dataset/tile['file'], dtype='<f4', mode='r', shape=(tile['stations'], 4))
        metric_tiles[tile['id']] = np.memmap(output/(tile['id']+'.metrics.bin'), dtype='<f4', mode='w+', shape=(tile['stations'], STRIDE))
        original_hash.update(originals[tile['id']].tobytes())
    rows = dbf_rows(source)
    required = ['wl_permit','api_wellno','well_sub','long','lat','measdpth','inclinatio','azimuth','tvd']
    for field in required:
        if field not in rows.dtype.names:
            raise ValueError('Missing DBF field: '+field)
    db_path = output/'.sort.sqlite'
    db = sqlite3.connect(db_path)
    db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA temp_store=FILE; PRAGMA cache_size=-65536; DROP TABLE IF EXISTS s; CREATE TABLE s(permit TEXT,api TEXT,branch TEXT,lon REAL,lat REAL,md REAL,inc REAL,azi REAL,tvd REAL);')
    skipped = 0
    start = time.time()
    for offset in range(0, len(rows), 100000):
        block = rows[offset:offset+100000]
        frame = pd.DataFrame({key: np.char.strip(block[key].astype('U')) for key in required})
        for key in required[3:]:
            frame[key] = pd.to_numeric(frame[key], errors='coerce')
        valid = (block['_deleted'] != b'*') & np.isfinite(frame[required[3:]]).all(axis=1) & frame['long'].between(-180,180) & frame['lat'].between(-89,89) & frame['inclinatio'].between(0,180) & (frame['measdpth'] >= 0) & (frame['wl_permit'] != '')
        valid &= frame['tvd'] >= 0 if manifest['tvdSign'] == 'positive' else frame['tvd'] <= 0
        skipped += int((~valid).sum())
        frame = frame[valid].copy()
        frame['well_sub'] = frame['well_sub'].replace('', 'MAIN')
        db.executemany('INSERT INTO s VALUES(?,?,?,?,?,?,?,?,?)', frame.itertuples(index=False, name=None))
        db.commit()
        if offset % 500000 == 0:
            print(json.dumps({'stage':'import','rows':min(offset+100000,len(rows)), 'total':len(rows), 'seconds':round(time.time()-start)}), flush=True)
    db.execute('CREATE INDEX ord ON s(permit,api,branch,md)')
    db.commit()
    well_index = 0
    overview_offset = 0
    duplicate = 0
    singleton = 0
    gap_count = 0
    exact_geometry_count = 0
    source_azi_outside_range = 0
    tiny_md_intervals = 0
    maximum_geometry_error = 0.0
    spots = []
    tile_station_counts = {key:0 for key in tiles}
    branch_stats = []
    quality_counts = {'doglegAbove100DegPer100Ft':0,'tortuosityAbove2':0,'tortuosityAbove10':0}
    largest_values = {'doglegDegPer100Ft':[], 'tortuosityRatio':[]}

    def emit(group):
        nonlocal well_index, overview_offset, duplicate, singleton, gap_count, exact_geometry_count, source_azi_outside_range, tiny_md_intervals, maximum_geometry_error
        if not group:
            return
        frame = pd.DataFrame(group, columns=['permit','api','branch','lon','lat','md','inc','azi','tvd'])
        before = len(frame)
        frame = frame.drop_duplicates('md', keep='last')
        duplicate += before-len(frame)
        if len(frame) < 2:
            singleton += len(frame)
            return
        if well_index >= len(manifest['wells']):
            raise ValueError('Source contains more branches than the viewer dataset')
        well = manifest['wells'][well_index]
        first = frame.iloc[0]
        identity = (str(first.permit), str(first.api), str(first.branch))
        if identity != (well['permit'], well['api'], well['branch']) or len(frame) != well['count']:
            raise ValueError(f'Branch ordering/count mismatch at {well_index}: {identity}')
        if well['id'] != well_index or well['offset'] != tile_station_counts[well['tile']]:
            raise ValueError('Manifest branch offset mismatch')
        md, inc, azi = frame.md.to_numpy(), frame.inc.to_numpy(), frame.azi.to_numpy()
        xyz = project(frame.lon.to_numpy(), frame.lat.to_numpy(), frame.tvd.to_numpy())
        existing = originals[well['tile']][well['offset']:well['offset']+well['count']]
        rounded = xyz.astype('<f4')
        same = np.all(rounded == existing[:, :3], axis=1)
        exact_geometry_count += int(same.sum())
        error = float(np.abs(rounded.astype(float)-existing[:, :3]).max())
        maximum_geometry_error = max(maximum_geometry_error,error)
        if not np.all(same):
            # Cross-platform BLAS reduction may differ by a final Float32 ULP;
            # fail beyond two representable units at each coordinate.
            tolerance = np.maximum(2*np.abs(np.spacing(existing[:, :3])), 1e-5)
            if np.any(np.abs(rounded.astype(float)-existing[:, :3]) > tolerance):
                raise ValueError(f'Source geometry cannot be aligned at branch {well_index}: {error} ft')
        metrics = station_metrics(md, inc, azi, xyz)
        quality_counts['doglegAbove100DegPer100Ft'] += int((metrics[:,3]>100).sum())
        quality_counts['tortuosityAbove2'] += int((metrics[:,6]>2).sum())
        quality_counts['tortuosityAbove10'] += int((metrics[:,6]>10).sum())
        for name,column in [('doglegDegPer100Ft',3),('tortuosityRatio',6)]:
            finite = np.flatnonzero(np.isfinite(metrics[:,column]))
            if len(finite):
                highest = int(finite[np.argmax(metrics[finite,column])])
                item = (float(metrics[highest,column]),well_index,highest,float(md[highest]))
                if len(largest_values[name])<5:
                    heapq.heappush(largest_values[name],item)
                else:
                    heapq.heappushpop(largest_values[name],item)
        metric_tiles[well['tile']][well['offset']:well['offset']+well['count']] = metrics
        tile_station_counts[well['tile']] += len(frame)
        section = existing[:,3]
        keep = overview_keep(section)
        expected = np.asarray([[*existing[i,:3], *existing[j,:3], section[j], well_index] for i,j in zip(keep[:-1],keep[1:])], dtype='<f4')
        original_span = overview[overview_offset:overview_offset+len(expected)]
        if original_span.shape != expected.shape or not np.array_equal(original_span, expected):
            raise ValueError(f'Overview segment mapping mismatch at branch {well_index}, offset {overview_offset}')
        aggregated = aggregate_overview(metrics, keep)
        overview_output[overview_offset:overview_offset+len(aggregated)] = aggregated
        overview_offset += len(aggregated)
        gaps = int((np.diff(md)>GAP_FT).sum())
        gap_count += gaps
        source_azi_outside_range += int(((azi<0)|(azi>360)).sum())
        tiny_md_intervals += int((np.diff(md)<.1).sum())
        branch_stats.append([well_index,gaps,int(np.isfinite(metrics[:,3]).sum()),int(np.isfinite(metrics[:,6]).sum())])
        if len(spots)<8 or (gaps and not any(s['gapCount'] for s in spots)):
            station = min(len(md)-1, max(1,len(md)//2))
            spots.append({'id':well_index,'permit':well['permit'],'api':well['api'],'branch':well['branch'],'tile':well['tile'],'offset':well['offset'],'stationIndex':station,'previousMD':float(md[station-1]),'previousInclination':float(inc[station-1]),'previousAzimuth':float(azi[station-1]),'sourceMD':float(md[station]),'sourceInclination':float(inc[station]),'sourceAzimuth':float(azi[station]),'gapCount':gaps,'values':[float(x) if np.isfinite(x) else None for x in metrics[station]],'overviewFirstRow':overview_offset-len(aggregated),'overviewRows':len(aggregated)})
        well_index += 1
        if well_index % 5000 == 0:
            print(json.dumps({'stage':'metrics','branches':well_index,'stations':sum(tile_station_counts.values()),'seconds':round(time.time()-start)}),flush=True)

    previous, group = None, []
    for row in db.execute('SELECT * FROM s ORDER BY permit,api,branch,md,rowid'):
        identity = row[:3]
        if identity != previous:
            emit(group)
            group, previous = [], identity
        group.append(row)
    emit(group)
    if well_index != len(manifest['wells']) or overview_offset != len(overview):
        raise ValueError('Final branch or overview count mismatch')
    if skipped != manifest['skipped'] or duplicate != manifest['duplicateMD']:
        raise ValueError('Input filtering or duplicate count differs from original converter')
    if any(tile_station_counts[k] != tiles[k]['stations'] for k in tiles):
        raise ValueError('Final tile station count mismatch')
    for values in metric_tiles.values():
        values.flush()
    overview_output.flush()
    db.close()
    db_path.unlink()
    print(json.dumps({'stage':'summary','seconds':round(time.time()-start)}),flush=True)
    summary = {'stations':statistics(list(metric_tiles.values())), 'overview':statistics([overview_output])}
    section_scales = section_metric_scales(manifest, originals, metric_tiles)
    input_hash = sha256(source)
    geometry_hash_after = hashlib.sha256()
    for tile in manifest['tiles']:
        geometry_hash_after.update(originals[tile['id']].tobytes())
    if original_hash.digest() != geometry_hash_after.digest():
        raise ValueError('Original geometry changed during metrics export')
    validation = {
        'passed':True,'sourceRecords':len(rows),'retainedStations':sum(tile_station_counts.values()),'branches':well_index,'overviewSegments':overview_offset,
        'skipped':skipped,'duplicateMDKeptLast':duplicate,'singletonStationsNotRendered':singleton,
        'stationCoordinatesExactlyMatched':exact_geometry_count,'maximumFloat32GeometryDifferenceFt':maximum_geometry_error,
        'allOverviewEndpointsAndSectionCodesExactlyMatched':True,'geometryUnchanged':True,
        'largeSurveyGaps':gap_count,'intervalsBelowPointOneFtMD':tiny_md_intervals,
        'sourceAzimuthsOutside0To360':source_azi_outside_range,
        'extremeValueCounts':quality_counts,
        'largestBranchMetricValues':{name:[{'value':v,'branchId':bid,'stationIndex':si,'mdFt':md} for v,bid,si,md in sorted(items,reverse=True)] for name,items in largest_values.items()},
        'spotChecks':spots,'elapsedSeconds':round(time.time()-start),
    }
    metadata = {
        'version':1,'title':'Measured survey geometry metrics','stride':STRIDE,'recordBytes':STRIDE*4,'type':'float32','byteOrder':'little','missing':'NaN',
        'fields':[{'index':i,'name':name,'unit':unit} for i,(name,unit) in enumerate(zip(FIELD_NAMES,UNITS))],
        'stations':manifest['stations'],'stationCount':manifest['stations'],'branchCount':well_index,'overviewSegments':overview_offset,
        'overview':{'file':'overview.metrics.bin','count':overview_offset,'alignment':'One record per original overview.bin record in unchanged order'},
        'tiles':[{'id':tile['id'],'file':tile['id']+'.metrics.bin','count':tile['stations']} for tile in manifest['tiles']],
        'tileAlignment':'Use the original manifest branch tile, offset and count; one metrics record per station.',
        'source':{'file':source.name,'sha256':input_hash,'datasetManifestSHA256':sha256(manifest_path),'overviewSHA256':sha256(dataset/'overview.bin'),'tileGeometrySHA256ManifestOrder':original_hash.hexdigest(),'sourceCRS':manifest['sourceCRS'],'origin':manifest['origin'],'tvdSign':manifest['tvdSign']},
        'settings':{'maximumIntervalFt':GAP_FT,'tortuosityWindowFt':WINDOW_FT,'minimumTortuosityCoverageFt':MIN_WINDOW_FT,'minimumDistinctTortuosityPoints':3,'azimuthMinimumInclinationDeg':AZIMUTH_MIN_INC,'zeroChordToleranceFt':GEOMETRY_EPSILON_FT},
        'formulas':{
            'doglegDegPer100Ft':'atan2(norm(cross(tangentPrevious,tangentCurrent)),dot(tangentPrevious,tangentCurrent)) * 180/pi * 100/deltaMD; stable equivalent of acos(cos(I1)cos(I2)+sin(I1)sin(I2)cos(deltaAz))',
            'buildDegPer100Ft':'(inclinationCurrent-inclinationPrevious)*100/deltaMD',
            'turnDegPer100Ft':'wrapped delta azimuth in [-180,180) *100/deltaMD; both inclinations must be at least 5 degrees',
            'tortuosityRatio':'unexaggerated source-coordinate polyline arc length / endpoint chord within a centered 1000 ft MD window, with linearly interpolated endpoints; clipped to branch/gap boundaries; minimum actual window coverage 500 ft and 3 distinct geometry points',
            'departureFt':'horizontal distance in feet from the first retained station of this branch; not necessarily surface departure',
            'curvatureRadPer1000Ft':'doglegDegPer100Ft * pi/180 * 10; a unit conversion of dogleg severity, not an independent measure',
        },
        'overviewAggregation':{
            'mdFt':'end station','inclinationDeg':'end station','azimuthDeg':'end station','departureFt':'end station',
            'doglegDegPer100Ft':'maximum of finite full-resolution incoming intervals within the span',
            'buildDegPer100Ft':'signed value of greatest absolute magnitude among finite full-resolution incoming intervals within the span',
            'turnDegPer100Ft':'signed value of greatest absolute magnitude among finite full-resolution incoming intervals within the span',
            'tortuosityRatio':'maximum of finite station-centered windows at all stations in the span, including its start and end',
            'gapHandling':'any interval greater than 1000 ft within a span makes its dogleg/build/turn/tortuosity undefined',
        },
        'notes':[
            'Survey station attributes and branch identities are retained; original source and viewer geometry are unchanged.',
            'Source order, sorting, validity filters, and last-record duplicate MD handling match the original converter.',
            'Angles are in degrees; valid source azimuths in [0,360] use 360=0. Azimuth is undefined below 5 degrees inclination or when the source value is outside [0,360]. Invalid source azimuths make adjacent dogleg and turn rates undefined; build rate still uses valid inclination.',
            'Rates describe incoming station intervals; first stations and gaps over 1000 ft have undefined rates.',
            'Tortuosity windows truncate at branch ends and survey gaps. They never connect separate branches or bridge a large gap.',
            'Tortuosity uses source geographic coordinates projected before Float32 display rounding, relative TVD, and no depth exaggeration. Ratios below 1 due to roundoff clamp to 1; zero chords are undefined.',
            'High rates or tortuosity may reflect survey quality or geometry; they do not independently establish a drilling operation.',
            'Fixed adjustable color limits clip extremes visually; retained values are not numerically capped. The validation report identifies short MD intervals, extreme values, and invalid source azimuths for review.',
        ],
        'summary':summary,'validationFile':'metrics-validation.json','summaryFile':'metrics-summary.json','sectionScalesFile':'section-metric-scales.json',
    }
    (output/'metrics.json').write_text(json.dumps(metadata,separators=(',',':')),encoding='utf8')
    (output/'metrics-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    (output/'metrics-validation.json').write_text(json.dumps(validation,indent=2),encoding='utf8')
    (output/'section-metric-scales.json').write_text(json.dumps(section_scales,separators=(',',':')),encoding='utf8')
    np.asarray(branch_stats,dtype='<u4').tofile(output/'branch-metric-counts.bin')
    print(json.dumps({k:validation[k] for k in ['passed','retainedStations','branches','overviewSegments','stationCoordinatesExactlyMatched','maximumFloat32GeometryDifferenceFt','largeSurveyGaps','elapsedSeconds']}),flush=True)


if __name__ == '__main__':
    main()
