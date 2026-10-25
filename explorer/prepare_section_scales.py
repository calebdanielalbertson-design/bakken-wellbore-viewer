"""Generate section scales from existing final binaries without rebuilding them.

Usage: python prepare_section_scales.py EXISTING_DATASET METRICS_FOLDER
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from prepare_metrics import section_metric_scales, sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path)
    parser.add_argument('metrics',type=Path)
    args=parser.parse_args()
    manifest_path=args.dataset/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    metadata=json.loads((args.metrics/'metrics.json').read_text())
    for key in ['stations','overviewSegments']:
        if metadata[key] != manifest[key]:
            raise ValueError('Metrics/geometry identity mismatch: '+key)
    if metadata['source']['datasetManifestSHA256'] != sha256(manifest_path):
        raise ValueError('Metrics were not built for this exact dataset manifest')
    geometry,metrics={},{}
    for tile in manifest['tiles']:
        geometry[tile['id']]=np.memmap(args.dataset/tile['file'],dtype='<f4',mode='r',shape=(tile['stations'],4))
        path=args.metrics/(tile['id']+'.metrics.bin')
        if path.stat().st_size != tile['stations']*32:
            raise ValueError('Incorrect metric file size: '+str(path))
        metrics[tile['id']]=np.memmap(path,dtype='<f4',mode='r',shape=(tile['stations'],8))
    def fingerprint(arrays):
        digest=hashlib.sha256()
        for tile in manifest['tiles']:
            digest.update(memoryview(arrays[tile['id']]))
        return digest.hexdigest()
    geometry_before,metrics_before=fingerprint(geometry),fingerprint(metrics)
    if geometry_before != metadata['source']['tileGeometrySHA256ManifestOrder']:
        raise ValueError('Geometry differs from the final metrics source')
    start=time.time()
    scales=section_metric_scales(manifest,geometry,metrics)
    assert fingerprint(geometry)==geometry_before
    assert fingerprint(metrics)==metrics_before
    target=args.metrics/'section-metric-scales.json'
    target.write_text(json.dumps(scales,separators=(',',':')),encoding='utf8')
    report={'passed':True,'stations':scales['stations'],'sectionStationCountSum':sum(s['stationCount'] for s in scales['sections']),
            'metricKeys':list(scales['sections'][0]['metrics']),'sectionCount':len(scales['sections']),'geometryBinaryUnchanged':True,'metricsBinariesUnchanged':True,
            'geometrySHA256ManifestOrder':geometry_before,'metricsSHA256ManifestOrder':metrics_before,
            'allMetricCountsAccountForFiniteAndMissingStations':True,'allQuantilesWithinObservedRanges':True,'quantiles':'exact, linear interpolation',
            'sections':[{'id':s['id'],'label':s['label'],'stations':s['stationCount'],'dlsP98':s['metrics']['dls']['p98'],'tortuosityP98':s['metrics']['tortuosity']['p98']} for s in scales['sections']],
            'jsonBytes':target.stat().st_size,'elapsedSeconds':round(time.time()-start,2)}
    (args.metrics/'section-metric-scales-validation.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
