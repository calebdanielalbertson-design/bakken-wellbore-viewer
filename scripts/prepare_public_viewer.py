"""Stage the authorized static public viewer without changing the local installation.

Writes only the site's viewer/ and full-dataset/ directories. Prepared data is
losslessly gzip-compressed into immutable <=20 MiB parts; the browser verifies
both compressed and original bytes before the existing application reads them.
"""
from __future__ import annotations
import argparse
import hashlib
import gzip
import json
import mimetypes
import pathlib
import re
import shutil

REPO = pathlib.Path(__file__).resolve().parent.parent
MAX_BYTES = 20 * 1024 * 1024
PRIVATE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/Users?/|/home/|\\\\)", re.I)

FETCH_MODULE = r'''// Public snapshot transport. Reconstructed bytes retain original snapshot hashes.
const hex=bytes=>Array.from(new Uint8Array(bytes),v=>v.toString(16).padStart(2,'0')).join('');
const hash=async bytes=>{if(!globalThis.crypto?.subtle)throw Error('This viewer requires Web Crypto in a secure HTTPS browser context.');return hex(await crypto.subtle.digest('SHA-256',bytes));};
export function createSplitAssetFetch(nativeFetch,index,baseURL){
  if(index?.version!==2||!index.assets||index.maxPartBytes!==20971520)throw Error('Invalid public asset index.');
  const base=new URL(baseURL),pending=new Map();
  const safePath=value=>typeof value==='string'&&!value.startsWith('/')&&!value.includes('..')&&!value.includes('\\')&&!/[?#]/.test(value);
  for(const [name,asset]of Object.entries(index.assets)){
    if(!safePath(name)||!Number.isSafeInteger(asset.bytes)||asset.bytes<=0||asset.encoding!=='gzip'||!Number.isSafeInteger(asset.storedBytes)||asset.storedBytes<=0||!Array.isArray(asset.parts)||!asset.parts.length||!/^[a-f0-9]{64}$/.test(asset.sha256)||!/^[a-f0-9]{64}$/.test(asset.storedSHA256))throw Error('Invalid split asset metadata.');
    let bytes=0;for(const part of asset.parts){if(!safePath(part.path)||!Number.isSafeInteger(part.bytes)||part.bytes<=0||part.bytes>index.maxPartBytes||!/^[a-f0-9]{64}$/.test(part.sha256))throw Error('Invalid public asset part.');bytes+=part.bytes;}
    if(bytes!==asset.storedBytes)throw Error('Split stored asset lengths do not reconcile.');
  }
  async function assemble(asset,signal){
    if(typeof DecompressionStream!=='function')throw Error('This viewer requires a current browser with gzip DecompressionStream support. Please update your browser.');
    const parts=await Promise.all(asset.parts.map(async part=>{
      const response=await nativeFetch(new URL(part.path,base),{signal,credentials:'same-origin'});
      if(!response.ok)throw Error('Public snapshot part is unavailable. Please reload the viewer.');
      const bytes=new Uint8Array(await response.arrayBuffer());
      if(bytes.byteLength!==part.bytes||await hash(bytes)!==part.sha256)throw Error('Public snapshot part failed its integrity check. Please reload.');
      return bytes;
    }));
    const stored=new Uint8Array(asset.storedBytes);let offset=0;for(const part of parts){stored.set(part,offset);offset+=part.length;}
    if(await hash(stored)!==asset.storedSHA256)throw Error('Compressed public snapshot failed its integrity check.');
    let result;try{result=new Uint8Array(await new Response(new Blob([stored]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());}catch{throw Error('Public snapshot could not be decompressed. Please reload in a current browser.');}
    if(result.byteLength!==asset.bytes)throw Error('Decompressed public snapshot length is incorrect.');
    if(await hash(result)!==asset.sha256)throw Error('Reconstructed public snapshot failed its integrity check.');
    return result;
  }
  return async function publicFetch(input,init){
    const request=input instanceof Request?input:null,url=new URL(request?request.url:String(input),globalThis.location?.href??new URL('viewer/',base));
    const method=String(init?.method??request?.method??'GET').toUpperCase();
    const relative=url.origin===base.origin&&url.pathname.startsWith(base.pathname)?url.pathname.slice(base.pathname.length):null;
    const asset=relative===null?null:index.assets[relative];
    if(method!=='GET'||!asset)return nativeFetch(input,init);
    const signal=init?.signal??request?.signal;if(signal?.aborted)throw signal.reason??new DOMException('Aborted','AbortError');
    // Share only an in-flight reconstruction, not an unbounded permanent cache.
    // Requests with an explicit signal keep independent cancellation semantics.
    let promise=signal?null:pending.get(relative);
    if(!promise){promise=assemble(asset,signal);if(!signal){pending.set(relative,promise);promise.finally(()=>{if(pending.get(relative)===promise)pending.delete(relative)}).catch(()=>{});}}
    return new Response(await promise,{status:200,headers:{'Content-Type':asset.contentType,'Content-Length':String(asset.bytes),'X-Public-Asset-SHA256':asset.sha256}});
  };
}
export async function installPublicAssetFetch(){
  const nativeFetch=globalThis.fetch.bind(globalThis),base=new URL('../',import.meta.url);
  const response=await nativeFetch(new URL('./public-assets-index.json',import.meta.url),{cache:'no-store'});
  if(!response.ok)throw Error('Public snapshot index is unavailable. Please reload.');
  globalThis.fetch=createSplitAssetFetch(nativeFetch,await response.json(),base);
}
'''

PUBLIC_LOGS = r'''// The public static edition intentionally has no raw LAS/API dependency.
export function createGammaController(){
  const explain=()=>{const status=document.getElementById('gammaStatus');if(status)status.textContent='GR and CBL overlays are available in the local viewer. This public release includes well surveys, production and footage scenarios.';const hover=document.getElementById('gammaHover');if(hover)hover.hidden=true;};
  const noop=()=>{};explain();
  return {load:async()=>explain(),reset:explain,setPermitFilter:noop,selected:noop,
    enabled:()=>false,contextVisible:()=>true,intersection:()=>null,hover:noop,
    focus:noop,limits:()=>null,group:null};
}
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def excluded(relative):
    name = relative.name.casefold()
    return ('__pycache__' in relative.parts or name == 'inventory-review.html'
            or any(token in name for token in ('audit', 'validation', 'verification'))
            or relative.suffix.casefold() in {'.pyc', '.dbf', '.shp', '.shx', '.las', '.csv', '.xlsx', '.ods', '.zip', '.npy', '.mp4', '.webm'})


def strip_private(value):
    if isinstance(value, dict):
        return {key: strip_private(item) for key, item in value.items()}
    if isinstance(value, list):
        return [strip_private(item) for item in value]
    if isinstance(value, str) and PRIVATE_PATH.match(value):
        return value.replace('\\', '/').rstrip('/').split('/')[-1]
    return value


def private_strings(value):
    if isinstance(value, dict):
        return sum((private_strings(item) for item in value.values()), [])
    if isinstance(value, list):
        return sum((private_strings(item) for item in value), [])
    return [value] if isinstance(value, str) and PRIVATE_PATH.match(value) else []


def stage(source, destination):
    source, destination = source.resolve(), destination.resolve()
    if not destination.is_relative_to(REPO / 'site') or destination.name != 'dist':
        raise ValueError('Destination must be the Bakken Subsurface site dist directory.')
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('Source and destination must be separate.')
    destination.mkdir(parents=True, exist_ok=True)
    changed, omitted = [], []
    # Verify exact resolved targets before deleting either owned staging subtree.
    for folder in ('viewer', 'full-dataset'):
        target = (destination / folder).resolve()
        if target.parent != destination or target.name != folder or (destination / folder).is_symlink():
            raise ValueError('Unsafe staging target.')
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()
        for original in sorted((source / folder).rglob('*')):
            if not original.is_file():
                continue
            relative = original.relative_to(source)
            if excluded(relative):
                omitted.append(relative.as_posix())
                continue
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            raw = original.read_bytes()
            if original.suffix in ('.json', '.geojson'):
                data = json.loads(raw)
                cleaned = strip_private(data)
                if original.name == 'production.json':
                    # Keep numerical observations and coverage; local workbook audits stay private.
                    cleaned.pop('audit', None)
                    cleaned.pop('auditFile', None)
                if cleaned != data:
                    if original.name == 'manifest.json' or relative.as_posix() == 'viewer/data/dsu/drilling-spacing-units.geojson':
                        raise ValueError('A hash-bound identity asset needs manual privacy review.')
                    raw = json.dumps(cleaned, separators=(',', ':'), ensure_ascii=False).encode('utf8')
                    changed.append(relative.as_posix())
            output.write_bytes(raw)

    viewer = destination / 'viewer'
    html_path = viewer / 'index.html'
    html = html_path.read_text(encoding='utf8')
    html = html.replace('<title>Wellbore · Section Explorer</title>', '<title>Bakken Subsurface Analytics | 3D Well Viewer</title>')
    html = html.replace('<link rel="stylesheet" href="style.css">', '<link rel="canonical" href="https://bakkensubsurface.com/viewer/"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="style.css">')
    html = html.replace('Explore OGD survey paths in 3D, colored by well section.', 'Explore North Dakota Bakken well surveys, operators, production history and lateral-footage scenarios in an interactive 3D viewer.')
    html = html.replace('<div class="brand"><span class="mark">W</span><div>WELLBORE <span class="sub">SECTION EXPLORER</span></div></div>', '<a class="brand" href="/" aria-label="Bakken Subsurface Analytics home"><span class="mark">B</span><div>BAKKEN SUBSURFACE <span class="sub">ANALYTICS · 3D WELL VIEWER</span></div></a>')
    html, replacements = re.subn(r'<section class="gamma-controls" aria-label="Well log overlay">.*?</div></section>', '<section class="gamma-controls" aria-label="Well logs in the local viewer"><div class="section-head"><h2>Well logs</h2></div><p id="gammaStatus" class="caption">GR and CBL overlays are available in the local viewer. This public release includes well surveys, production and footage scenarios.</p></section>', html, count=1, flags=re.S)
    if replacements != 1:
        raise ValueError('Could not replace the local-only log controls.')
    html = html.replace('<a href="./inventory-review.html" target="_blank" rel="noopener">Read the inventory methodology review</a>', '<a href="/methodology/">Read the public methodology and limitations</a>')
    html = html.replace('<script type="module" src="app.js"></script>', '<script type="module" src="public-app.js"></script>')
    html_path.write_text(html, encoding='utf8')
    (viewer / 'style.css').write_text((viewer / 'style.css').read_text(encoding='utf8') + '\n.brand{text-decoration:none;color:inherit}.brand:hover{color:#b7fff0}\n', encoding='utf8')
    (viewer / 'gamma.js').write_text(PUBLIC_LOGS, encoding='utf8')
    app = (viewer / 'app.js').read_text(encoding='utf8')
    old = "if(new URLSearchParams(location.search).get('dataset')==='full'){load("
    new = "if(new URLSearchParams(location.search).get('dataset')!=='sample'&&!['cluster','tour'].includes(new URLSearchParams(location.search).get('showcase'))){load("
    if old not in app:
        raise ValueError('Public default-dataset hook is missing.')
    (viewer / 'app.js').write_text(app.replace(old, new, 1), encoding='utf8')
    (viewer / 'public-assets.js').write_text(FETCH_MODULE, encoding='utf8')
    (viewer / 'public-app.js').write_text("import {installPublicAssetFetch} from './public-assets.js';\ntry{await installPublicAssetFetch();await import('./app.js')}catch(error){document.getElementById('message').textContent='Could not load the public snapshot: '+error.message;}\n", encoding='utf8')

    index = {'version': 2, 'maxPartBytes': MAX_BYTES, 'assets': {}}
    parts_dir = viewer / 'data' / 'public-parts'
    for path in sorted(destination.rglob('*')):
        if not path.is_file() or not (path.is_relative_to(viewer / 'data') or path.is_relative_to(destination / 'full-dataset')) or path.suffix.lower() not in {'.bin', '.json', '.geojson'} or path.stat().st_size <= 4096:
            continue
        raw = path.read_bytes()
        fingerprint = sha(raw)
        stored = gzip.compress(raw, compresslevel=9, mtime=0)
        stored_fingerprint = sha(stored)
        record = {'bytes': len(raw), 'sha256': fingerprint, 'encoding': 'gzip', 'storedBytes': len(stored), 'storedSHA256': stored_fingerprint,
                  'contentType': 'application/geo+json' if path.suffix == '.geojson' else mimetypes.guess_type(path.name)[0] or 'application/octet-stream', 'parts': []}
        parts_dir.mkdir(parents=True, exist_ok=True)
        for number, offset in enumerate(range(0, len(stored), MAX_BYTES)):
            part = stored[offset:offset + MAX_BYTES]
            part_path = parts_dir / f'{stored_fingerprint}-{number:03d}.gz.bin'
            part_path.write_bytes(part)
            record['parts'].append({'path': part_path.relative_to(destination).as_posix(), 'bytes': len(part), 'sha256': sha(part)})
        index['assets'][path.relative_to(destination).as_posix()] = record
        path.unlink()
    (viewer / 'public-assets-index.json').write_text(json.dumps(index, separators=(',', ':')), encoding='utf8')
    stored_site_bytes = sum(path.stat().st_size for path in destination.rglob('*') if path.is_file())
    if stored_site_bytes >= 250 * 1024 * 1024:
        raise ValueError(f'Public release is still above the 250 MiB stored target: {stored_site_bytes} bytes')
    report = verify(source, destination, index)
    report['omittedLocalArtifacts'] = omitted
    report['sanitizedMetadata'] = changed
    report['logs'] = 'Public static edition excludes raw LAS, survey DBF and log API dependencies.'
    (viewer / 'public-release.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    return report


def verify(source, destination, index):
    def logical_bytes(name):
        if name in index['assets']:
            record = index['assets'][name]
            stored = b''.join((destination / part['path']).read_bytes() for part in record['parts'])
            if len(stored) != record['storedBytes'] or sha(stored) != record['storedSHA256']:
                raise ValueError('Compressed asset reconstruction differs: ' + name)
            result = gzip.decompress(stored)
            if len(result) != record['bytes'] or sha(result) != record['sha256']:
                raise ValueError('Split asset reconstruction differs: ' + name)
            for part in record['parts']:
                raw = (destination / part['path']).read_bytes()
                if len(raw) != part['bytes'] or sha(raw) != part['sha256']:
                    raise ValueError('Split asset part differs.')
            return result
        return (destination / name).read_bytes()
    original_manifest = (source / 'full-dataset/manifest.json').read_bytes()
    manifest_raw = logical_bytes('full-dataset/manifest.json')
    if original_manifest != manifest_raw:
        raise ValueError('Main survey manifest bytes changed.')
    for name in index['assets']:
        original = (source / name).read_bytes()
        if pathlib.Path(name).name == 'production.json':
            original_data = json.loads(original)
            cleaned = strip_private(original_data)
            cleaned.pop('audit', None);cleaned.pop('auditFile', None)
            if cleaned != original_data:
                original = json.dumps(cleaned, separators=(',', ':'), ensure_ascii=False).encode('utf8')
        if logical_bytes(name) != original:
            raise ValueError('Logical asset bytes changed: ' + name)
        if pathlib.Path(name).suffix in ('.json', '.geojson') and private_strings(json.loads(logical_bytes(name))):
            raise ValueError('Private local path remains in a compressed logical asset.')
    footage = json.loads(logical_bytes('viewer/data/inventory/footage.json'))
    if footage['survey']['manifest_sha256'] != sha(manifest_raw):
        raise ValueError('Footage manifest fingerprint changed.')
    dsu_raw = logical_bytes('viewer/data/dsu/drilling-spacing-units.geojson')
    if footage['source_hashes']['dsu_file_sha256'] != sha(dsu_raw):
        raise ValueError('Footage DSU fingerprint changed.')
    if footage['source_hashes']['townships_geojson_sha256'] != sha(logical_bytes('viewer/data/inventory/townships.geojson')):
        raise ValueError('Footage township fingerprint changed.')
    membership = json.loads(logical_bytes('viewer/data/dsu/dsu-well-membership.json'))
    if membership['sourceHashes']['manifestSha256'] != sha(manifest_raw) or membership['sourceHashes']['dsuFileSha256'] != sha(dsu_raw):
        raise ValueError('Existing DSU membership fingerprints changed.')
    shape_name = 'full-dataset/well-shape-overlays.json'
    if (source / shape_name).exists():
        shapes = json.loads(logical_bytes(shape_name))
        for key, asset in [('manifestSHA256', 'manifest.json'),
                           ('overviewSHA256', 'overview.bin'),
                           ('metricsSHA256', 'metrics.json')]:
            if shapes['source'][key] != sha(logical_bytes('full-dataset/' + asset)):
                raise ValueError('Trajectory display overlay fingerprint changed: ' + key)
    for folder in ('full-dataset', 'viewer/data/sample', 'viewer/data/showcase'):
        original = source / folder / 'production.json'
        if original.exists():
            left = json.loads(original.read_bytes());right = json.loads(logical_bytes(folder + '/production.json'))
            for key in ('audit', 'auditFile'):
                left.pop(key, None)
            if left != right:
                raise ValueError('Numerical production metadata changed.')
    files = [path for folder in ('viewer', 'full-dataset') for path in (destination / folder).rglob('*') if path.is_file()]
    for path in files:
        if path.stat().st_size > MAX_BYTES:
            raise ValueError('Public asset exceeds static host size cap.')
        if excluded(path.relative_to(destination)):
            raise ValueError('Excluded local artifact remains.')
        if path.suffix in ('.json', '.geojson') and private_strings(json.loads(path.read_bytes())):
            raise ValueError('Private local path remains in ' + path.name)
        if path.suffix in ('.js', '.html', '.css', '.txt') and re.search(r'(?i)[A-Z]:[\\/]+Users[\\/]|/Users/|/home/', path.read_text(encoding='utf8')):
            raise ValueError('Private text path remains in ' + path.name)
        relative = path.relative_to(destination)
        if path.suffix == '.bin' and relative.parts[:3] != ('viewer', 'data', 'public-parts'):
            if path.read_bytes() != (source / relative).read_bytes():
                raise ValueError('Numerical binary changed: ' + str(relative))
    return {'version': 2, 'surveyManifestSHA256': sha(manifest_raw), 'dsuSHA256': sha(dsu_raw),
            'sourceDate': json.loads(manifest_raw)['sourceSnapshot']['date'],
            'preparedFileCount': len(files) + 1, 'maximumPreparedFileBytes': max(path.stat().st_size for path in files),
            'preparedBytesBeforeReleaseNote': sum(path.stat().st_size for path in files),
            'compressedLogicalAssetCount': len(index['assets']),
            'logicalBytesInCompressedAssets': sum(record['bytes'] for record in index['assets'].values()),
            'storedBytesInCompressedAssets': sum(record['storedBytes'] for record in index['assets'].values()),
            'checks': ['gzip payloads and decompressed originals independently hashed', 'all numerical binaries preserved', 'exact survey manifest preserved', 'footage and membership fingerprints preserved', 'production audit removed without changing observations', 'no private local paths', 'no raw LAS/DBF or local audit files', 'every stored asset at most 20 MiB', 'total stored site below 250 MiB']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=pathlib.Path, default=REPO / 'explorer')
    parser.add_argument('--site-dist', type=pathlib.Path, default=REPO / 'site' / 'dist')
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.site_dist), indent=2))
