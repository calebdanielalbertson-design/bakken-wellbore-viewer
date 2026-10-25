"""Attach separately audited approximate display zones by exact current DSU ID."""
import argparse, hashlib, json, math, pathlib


def merge(current_path, zones_path, output_path):
    current_path=pathlib.Path(current_path); zones_path=pathlib.Path(zones_path)
    output_path=pathlib.Path(output_path)
    original=json.loads(current_path.read_text(encoding='utf-8'))
    zones=json.loads(zones_path.read_text(encoding='utf-8'))
    ids={f['id'] for f in original['features']}
    if len(ids)!=len(original['features']) or ids!=set(zones['zones']):
        raise ValueError('Zone identities do not exactly cover current source features')
    before=hashlib.sha256(json.dumps(original['features'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    for feature in original['features']:
        zone=zones['zones'][feature['id']]
        if not all(isinstance(zone[k],(int,float)) and math.isfinite(zone[k]) for k in ('topFt','bottomFt')):
            raise ValueError('Invalid display interval')
        if not (0<zone['topFt']<zone['bottomFt']):
            raise ValueError('Display depth interval must be positive and ordered')
        if 'zone' in feature['properties']:
            raise ValueError('Current feature already contains a display zone')
        feature['properties']['zone']=zone
    original['metadata']['zoneEstimates']=zones['metadata']
    original['metadata']['zoneEstimates']['zoneFileSha256']=hashlib.sha256(zones_path.read_bytes()).hexdigest()
    restored=[]
    for feature in original['features']:
        restored.append({**feature,'properties':{k:v for k,v in feature['properties'].items() if k!='zone'}})
    after=hashlib.sha256(json.dumps(restored,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if before!=after: raise ValueError('Zone merge changed source geometry or existing properties')
    output_path.write_text(json.dumps(original,separators=(',',':'),ensure_ascii=False),encoding='utf-8')
    report={'features':len(ids),'zoneCoverageExact':True,'positiveOrderedIntervals':True,
            'currentGeometryIdsAndPropertiesPreserved':True,'inputFeatureContentSha256':before,
            'inputZoneSha256':hashlib.sha256(zones_path.read_bytes()).hexdigest(),
            'outputBytes':output_path.stat().st_size,'inventoryCounts':original['metadata'].get('inventoryScenario',{}).get('counts'),
            'zoneMethodCounts':zones['metadata']['methodCounts']}
    output_path.with_suffix('.merge-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('current','zones','output'): parser.add_argument(name)
    args=parser.parse_args(); merge(args.current,args.zones,args.output)
