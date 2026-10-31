"""Validate the complete static release before source synchronization."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import hashlib
import gzip
import json
import re
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parent
DIST=ROOT/'dist'
EXPECTED_MANIFEST='328deaf1f1d2bf9c9d7d5e961cd25be653f082a51fb6966f13be9e495ef4599c'
sha=lambda b:hashlib.sha256(b).hexdigest()
hosting=json.loads((ROOT/'.openai/hosting.json').read_text())
assert hosting['project_id']=='appgprj_6ad3fd50b2488191993a92f3ed09603f'
assert hosting['static']['not_found_handling']=='404-page'
import sys
REQUIRE_DATA='--require-data' in sys.argv
index=json.loads((DIST/'viewer/public-assets-index.json').read_text())
HAVE_DATA=all((DIST/part['path']).is_file() for asset in index['assets'].values() for part in asset['parts'])
if REQUIRE_DATA: assert HAVE_DATA, 'Prepared viewer data is missing; run scripts/fetch_data.py first'
logical={}
if not HAVE_DATA:
    print('note: prepared viewer data not present; checking code, pages and links only (use --require-data before a release)', file=sys.stderr)
if HAVE_DATA:
    assert index['version']==2
    for name,asset in index['assets'].items():
        parts=[]
        for part in asset['parts']:
            payload=(DIST/part['path']).read_bytes()
            assert len(payload)==part['bytes'] and sha(payload)==part['sha256']
            parts.append(payload)
        stored=b''.join(parts)
        assert asset['encoding']=='gzip'
        assert len(stored)==asset['storedBytes'] and sha(stored)==asset['storedSHA256']
        joined=gzip.decompress(stored)
        assert len(joined)==asset['bytes'] and sha(joined)==asset['sha256']
        assert not (DIST/name).exists(), 'Uncompressed logical data was duplicated in the artifact'
        logical[name]=joined
    def read_logical(name):
        return logical[name] if name in logical else (DIST/name).read_bytes()
    assert sha(read_logical('full-dataset/manifest.json'))==EXPECTED_MANIFEST
    shapes=json.loads(read_logical('full-dataset/well-shape-overlays.json'))
    assert shapes['version']==1 and shapes['kind']=='well-shape-display-overlays'
    for key, name in [('manifestSHA256','manifest.json'),('overviewSHA256','overview.bin'),('metricsSHA256','metrics.json')]:
        assert shapes['source'][key]==sha(read_logical('full-dataset/'+name)), key
    shape_wells={w['id']:w for w in json.loads(read_logical('full-dataset/manifest.json'))['wells']}
    assert sum(bool(b['uturnRanges']) for b in shapes['branches'])==18
    for branch in shapes['branches']:
        assert all(branch[key]==shape_wells[branch['id']][key] for key in ('id','permit','api','branch','tile','offset','count'))
assert 'U-turn laterals' in (DIST/'viewer/index.html').read_text(encoding='utf8')
# Page content that the tours and EOR pages fetch at runtime (not covered by the HTML link check).
for name in ('tours/data/tours.json','tours/data/shoreline.json','tours/data/hawkinson-design.json'):
    assert (DIST/name).is_file(), name
for project in json.loads((DIST/'eor/projects.json').read_text(encoding='utf-8'))['projects']:
    assert (DIST/'eor/data'/(project['id']+'.json')).is_file(), project['id']
assert (DIST/'viewer/well-shapes.js').exists()
app_text=(DIST/'viewer/app.js').read_text(encoding='utf8')
assert '\u00b7' in app_text and '\u2026' in app_text
assert not any(token in app_text for token in ('\u00c2\u00b7','\u00e2\u20ac','\u00e2\u2020')), 'Viewer text is not clean UTF-8'
if HAVE_DATA:
    for folder in ('full-dataset','viewer/data/sample','viewer/data/showcase'):
        manifest_raw=read_logical(folder+'/manifest.json')
        survey=json.loads(manifest_raw)
        metadata=json.loads(read_logical(folder+'/well-names.json'))
        assert metadata['survey']['manifestSHA256']==sha(manifest_raw)
        assert metadata['survey']['branchCount']==len(survey['wells'])
        assert set(metadata['names'])=={str(w['id']) for w in survey['wells']}
        assert all(isinstance(n,str) and n.strip() for n in metadata['names'].values())
        assert metadata['coverage']['matchedWellIdentities']==metadata['coverage']['datasetWellIdentities']
    # Every geometry and metrics tile the viewer can request must ship, either as split
    # gzip parts or as a small plain file in dist/full-dataset/.
    tiles=json.loads(read_logical('full-dataset/manifest.json'))['tiles']
    for tile in tiles:
        for name in (tile['file'], tile['file'].replace('.bin','.metrics.bin')):
            assert 'full-dataset/'+name in logical or (DIST/'full-dataset'/name).is_file(), 'missing tile '+name
    production=json.loads(read_logical('full-dataset/production.json'))
    assert 'audit' not in production and 'auditFile' not in production
    for name in ('production-audit.json','refresh-validation.json'):
        assert not (DIST/'full-dataset'/name).exists()
assert not (DIST/'viewer/inventory-review.html').exists()
# Bakken Subsurface 3D (/3d/): page plus one gzip object per data file, listed with hashes in release.json
# (scripts/prepare_3d_viewer.py). The data folder is fetched like the survey viewer's, so it is checked when present.
release3d=json.loads((DIST/'3d/release.json').read_text(encoding='utf-8'))
assert release3d['kind']=='bakken-subsurface-3d' and release3d['wells']>0
page3d=(DIST/'3d/index.html').read_bytes()
assert page3d.startswith(b'<!doctype html>') and sha(page3d)==release3d['page']['sha256']
assert b"inflate('data/meta.gz.bin')" in page3d and b"fetch('meta.json'" not in page3d
HAVE_3D=(DIST/'3d/data/meta.gz.bin').is_file()
if HAVE_3D:
    for name,entry in release3d['data'].items():
        stored=(DIST/'3d/data'/name).read_bytes()
        assert len(stored)==entry['storedBytes'] and sha(stored)==entry['storedSHA256'], name
        original=gzip.decompress(stored)
        assert len(original)==entry['bytes'] and sha(original)==entry['sha256'], name
    meta3d=json.loads(gzip.decompress((DIST/'3d/data/meta.gz.bin').read_bytes()))
    assert meta3d['n_wells']==release3d['wells']
    # Public edition: no subscription-only numbers leave the site (see scripts/prepare_3d_viewer.py)
    assert release3d.get('edition')=='public-level-1', 'only the public edition of the 3D viewer may be released'
    assert meta3d.get('edition')=='public-level-1' and 'swd_year' in meta3d and 'swd_classes' in meta3d
    assert all(set(s)<={'w','name','op','x','y','z','cls','cumc','r'} for s in meta3d['swd'])
    assert all(v is None for key in ('cem_top','cem_ik','bond_good') for v in meta3d['wells'][key])
    from array import array
    paths3d=array('f'); paths3d.frombytes(gzip.decompress((DIST/'3d/data/paths.gz.bin').read_bytes()))
    for col in (3,4,5):
        assert len({v for v in paths3d[col::9] if v==v})<=16, ('log column not quantized', col)
    for marker in (b'Lateral gamma ray, median', b'Inyan Kara top (subsea)', b'<option value="cem_top">', b'<option value="cem_ik">', b'<option value="bond_good">', b's.psi[', b's.cum['):
        assert marker not in page3d, marker
    assert b'class="prov"' in page3d
else:
    print('note: 3D viewer data not present (site/dist/3d/data); run scripts/prepare_3d_viewer.py or datasets.py fetch site-3d-data', file=sys.stderr)
if REQUIRE_DATA: assert HAVE_3D, '3D viewer data is missing'
assert 'local viewer' in (DIST/'viewer/index.html').read_text(encoding='utf-8')
forbidden={'.las','.dbf','.xlsx','.ods','.csv','.env','.zip','.sqlite','.db','.py'}
private=re.compile(r'(?i)(?:[A-Z]:[\\/]+Users[\\/]|(?:/Users/|/home/)[^/\s]+|github_pat_|ghp_[A-Za-z0-9]{30})')
files=list(p for p in DIST.rglob('*') if p.is_file())
assert sum(p.stat().st_size for p in files)<250*1024*1024, 'Stored release must stay below 250 MiB'
if HAVE_DATA:
    for name,payload in logical.items():
        if Path(name).suffix.lower() in {'.json','.geojson'}:
            assert not private.search(payload.decode('utf-8')), name
for path in files:
    assert path.stat().st_size<=20*1024*1024, path
    assert path.suffix.lower() not in forbidden, path
    assert '.git' not in path.parts and '.openai' not in path.parts, path
    if path.suffix.lower() in {'.html','.js','.css','.json','.geojson','.xml','.txt','.svg'}:
        assert not private.search(path.read_text(encoding='utf-8')), path
class Links(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]; self.headings=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='h1':self.headings+=1
        for name in ('href','src','srcset'):
            if name in attrs:self.links.append(attrs[name])
for filename in ('index.html','methodology/index.html','eor/index.html','tours/index.html','404.html'):
    page=DIST/filename; parser=Links(); parser.feed(page.read_text(encoding='utf-8'))
    assert parser.headings==1, filename
    for value in parser.links:
        url=urlsplit(value)
        if url.scheme or url.netloc or not url.path:continue
        target=(DIST/unquote(url.path).lstrip('/')) if url.path.startswith('/') else page.parent/unquote(url.path)
        assert target.exists(), (filename,value)
ns={'s':'http://www.sitemaps.org/schemas/sitemap/0.9'}
urls=[x.text for x in ET.parse(DIST/'sitemap.xml').findall('s:url/s:loc',ns)]
expected_urls={'https://bakkensubsurface.com/','https://bakkensubsurface.com/viewer/','https://bakkensubsurface.com/3d/','https://bakkensubsurface.com/methodology/','https://bakkensubsurface.com/eor/','https://bakkensubsurface.com/tours/'}
expected_urls.update('https://bakkensubsurface.com/eor/project/?project='+project for project in ('durant','clover-roadrunner','en-ortloff','nygaard','haley'))
assert set(urls)==expected_urls
assert 'https://bakkensubsurface.com/sitemap.xml' in (DIST/'robots.txt').read_text()
print(json.dumps({'status':'passed','files':len(files),'bytes':sum(p.stat().st_size for p in files),'maximum_asset_bytes':max(p.stat().st_size for p in files),'data_checked':HAVE_DATA,'data_checked_3d':HAVE_3D,'split_assets_verified':len(index['assets']) if HAVE_DATA else 0,'crawlable_pages':len(urls)}))
