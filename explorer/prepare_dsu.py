"""Convert the official ND DMR DSU ZIP to compact NAD83 geographic GeoJSON.

Uses only Python's standard library. Polygons, multipart records, holes and raw
attributes are retained. This does not infer operator, inventory or DSU depth.
"""
import argparse
import collections
import datetime
import hashlib
import json
import math
import pathlib
import struct
import zipfile

SOURCE_URL = 'https://gis.dmr.nd.gov/downloads/oilgas/shapefile/OGD_DrillingSpacingUnits.zip'

def read_dbf(data, encoding='utf-8'):
    count, header, size = struct.unpack_from('<IHH', data, 4)
    fields=[]
    offset=32
    while data[offset] != 13:
        entry=data[offset:offset+32]
        fields.append((entry[:11].split(b'\0')[0].decode('ascii'),chr(entry[11]),entry[16],entry[17]))
        offset += 32
    records=[]
    for index in range(count):
        raw=data[header+index*size:header+(index+1)*size]
        if len(raw)!=size or raw[:1]==b'*':
            raise ValueError('Truncated or deleted DBF record would lose shape alignment')
        row={}; position=1
        for name,kind,width,decimal in fields:
            value=raw[position:position+width].decode(encoding,errors='strict').strip()
            position+=width
            if not value: value=None
            elif kind in ('N','F'):
                value=float(value) if decimal else int(value)
                if not math.isfinite(value): raise ValueError('Nonfinite DBF number')
            row[name]=value
        records.append(row)
    return fields,records

def read_shapes(data):
    if struct.unpack_from('>i',data)[0]!=9994:
        raise ValueError('Invalid shapefile header')
    bounds=struct.unpack_from('<4d',data,36)
    offset=100; result=[]
    while offset<len(data):
        _,words=struct.unpack_from('>2i',data,offset); offset+=8
        record=data[offset:offset+2*words]; offset+=2*words
        if len(record)!=2*words: raise ValueError('Truncated shape record')
        kind=struct.unpack_from('<i',record)[0]
        if kind==0: result.append([]); continue
        if kind not in (5,15,25): raise ValueError(f'Expected polygon, received {kind}')
        parts,points=struct.unpack_from('<2i',record,36)
        starts=list(struct.unpack_from(f'<{parts}i',record,44))+[points]
        xy=struct.unpack_from(f'<{2*points}d',record,44+4*parts)
        coords=list(zip(xy[::2],xy[1::2]))
        if not all(math.isfinite(x) for x in xy): raise ValueError('Nonfinite shape coordinate')
        rings=[coords[a:b] for a,b in zip(starts,starts[1:])]
        for ring in rings:
            if len(ring)<4 or ring[0]!=ring[-1]: raise ValueError('Invalid polygon ring')
        result.append(rings)
    return bounds,result

def ring_area(ring):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring,ring[1:])))/2

def contains_point(ring, point):
    x,y=point; inside=False
    for a,b in zip(ring,ring[1:]):
        if (a[1]>y)!=(b[1]>y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside=not inside
    return inside

def rings_geometry(rings):
    if len(rings)==1: return {'type':'Polygon','coordinates':rings}
    areas=[ring_area(r) for r in rings]
    parent=[]
    for index,ring in enumerate(rings):
        candidates=[(areas[j],j) for j,outer in enumerate(rings)
                    if areas[j]>areas[index] and contains_point(outer,ring[0])]
        parent.append(min(candidates)[1] if candidates else None)
    depths=[]
    for index in range(len(rings)):
        depth=0; p=parent[index]
        while p is not None:
            depth+=1; p=parent[p]
            if depth>len(rings): raise ValueError('Circular ring nesting')
        depths.append(depth)
    polygons=[]
    for index,ring in enumerate(rings):
        if depths[index]%2==0:
            polygons.append([ring]+[rings[j] for j in range(len(rings)) if parent[j]==index and depths[j]%2==1])
    return {'type':'Polygon','coordinates':polygons[0]} if len(polygons)==1 else {'type':'MultiPolygon','coordinates':polygons}

def prepare(archive_path, output_path):
    archive_path=pathlib.Path(archive_path); output_path=pathlib.Path(output_path)
    raw_zip=archive_path.read_bytes()
    with zipfile.ZipFile(archive_path) as archive:
        # Read in memory: never extract archive-supplied paths.
        required=['OGD_DrillingSpacingUnits.'+ext for ext in ('dbf','shp','prj','cpg')]
        for name in required:
            if archive.namelist().count(name)!=1: raise ValueError('Missing or duplicate source member '+name)
        bad=archive.testzip()
        if bad: raise ValueError('ZIP CRC mismatch '+bad)
        prj=archive.read(required[2]).decode('utf-8').strip()
        if 'GCS_North_American_1983' not in prj or 'PROJCS' in prj:
            raise ValueError('Source must use geographic NAD83; projection conversion is not implicit')
        encoding=archive.read(required[3]).decode('ascii').strip()
        fields,records=read_dbf(archive.read(required[0]), encoding)
        bounds,shapes=read_shapes(archive.read(required[1]))
        entries=[{'name':i.filename,'bytes':i.file_size,'crc32':f'{i.CRC:08x}',
                  'zipTimestamp':list(i.date_time)} for i in archive.infolist()]
    if len(records)!=len(shapes): raise ValueError('DBF and SHP record count mismatch')
    features=[]; nulls=[]; ids=collections.Counter()
    for index,(record,rings) in enumerate(zip(records,shapes)):
        if not rings: nulls.append(index); continue
        geometry=rings_geometry(rings)
        digest=hashlib.sha256(json.dumps([record,geometry],sort_keys=True,separators=(',',':')).encode()).hexdigest()[:20]
        ids[digest]+=1
        feature_id='dsu-'+digest+('-'+str(ids[digest]) if ids[digest]>1 else '')
        acres=record['dssize']
        label=' · '.join(str(x) for x in (record['formation'],f'{acres:,} acres' if isinstance(acres,(int,float)) else None,record['dstype']) if x is not None)
        properties={'id':feature_id,'sourceRecord':index+1,'label':label,
                    'formation':record['formation'],'acres':acres,'spacingType':record['dstype'],
                    'caseNo':record['caseno'] or None,'orderNo':record['orderno'] or None,
                    'mapSymbol':record['mapsymbol'],'referenceCode':record['refcode'],
                    'source':record}
        coords=[point for ring in rings for point in ring]
        bbox=[min(p[0] for p in coords),min(p[1] for p in coords),max(p[0] for p in coords),max(p[1] for p in coords)]
        features.append({'type':'Feature','id':feature_id,'bbox':bbox,'properties':properties,'geometry':geometry})
    provenance={'url':SOURCE_URL,'retrievedAtUTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'archiveSha256':hashlib.sha256(raw_zip).hexdigest(),'archiveBytes':len(raw_zip),
                'sourceCRS':'EPSG:4269','coordinateOrder':'longitude,latitude','sourceProjectionWKT':prj,
                'recordCount':len(records),'featureCount':len(features),'nullShapeRecords':nulls,
                'fields':[{'name':n,'type':t,'width':w,'decimals':d} for n,t,w,d in fields],
                'archiveEntries':entries,
                'limitations':['Spacing acreage is the published dssize attribute, not SHAPE_Area (which uses square degrees).',
                    'Source boundaries and overlaps are preserved; no bounding rectangle replacement or deduplication.',
                    'The source has no operator, remaining inventory or vertical depth attributes.',
                    'NAD83 coordinates require a matching projection in the viewer; this is not RFC 7946 WGS84 GeoJSON.']}
    result={'type':'FeatureCollection','name':'North Dakota DMR Drilling Spacing Units','bbox':bounds,
            'metadata':provenance,'features':features}
    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_text(json.dumps(result,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    output_path.with_suffix('.provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output_path),'bytes':output_path.stat().st_size,'features':len(features),
                      'formations':dict(collections.Counter(r['formation'] for r in records)),
                      'spacingTypes':dict(collections.Counter(r['dstype'] for r in records)),
                      'acresRange':[min(r['dssize'] for r in records if r['dssize'] is not None),max(r['dssize'] for r in records if r['dssize'] is not None)]},indent=2))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive'); parser.add_argument('output')
    args=parser.parse_args(); prepare(args.archive,args.output)
