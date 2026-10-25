"""Acquire and rebuild a private GIS staging candidate; never publish or import SQL.

Default is a read-only plan. Use --execute to create a fresh run, optionally
--source-dir for previously downloaded official ZIPs. No scheduler is installed.
Run folders are append-only snapshots; this tool never replaces a previous run
or a live/public dataset. A ready_for_review result still requires review/import.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import subprocess
import sys
import urllib.request
import uuid
import zipfile

import workspace_paths as wp
WORKSPACE = wp.REPO
VIEWER = wp.EXPLORER
VERSION = 'staging-gis-refresh-1'
CLASSIFIER_VERSION = '2.0'
DEFAULT_ORIGIN = [-102.99897097700921, 47.91137672734358]
BASE_URL = 'https://gis.dmr.nd.gov/downloads/oilgas/shapefile/'
SOURCES = {key: BASE_URL + stem + '.zip' for key, stem in (
    ('wells', 'OGD_Wells'), ('horizontals', 'OGD_Horizontals'),
    ('dsu', 'OGD_DrillingSpacingUnits'))}
MAX_ARCHIVE_BYTES = 600 * 1024 * 1024
MAX_EXPANDED_BYTES = 4 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 32
MAX_RATIO = 300
IMPORTANT = {'.dbf', '.shp', '.shx', '.prj', '.cpg'}
# The official Horizontals ZIP also carries the companion line shapefile.
COMPANION_STEMS = {'OGD_Horizontals': {'OGD_Horizontals_Line'}}
SCRIPTS = ['prepare_data.py', 'classifier.py', 'prepare_metrics.py',
           'prepare_section_scales.py', 'prepare_operators.py',
           'prepare_well_names.py', 'prepare_dsu.py', 'prepare_dsu_membership.py']


def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf8')
    temporary.replace(path)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('GIS download redirected; inspect and update the allowlist explicitly')


def download(url, target, *, opener=None, max_bytes=MAX_ARCHIVE_BYTES):
    """Stream only the three exact official HTTPS endpoints, with a hard cap."""
    if url not in SOURCES.values():
        raise ValueError('URL is not an allowlisted ND DMR GIS archive')
    opener = opener or urllib.request.build_opener(NoRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': 'BakkenSubsurfaceStaging/1'})
    target = Path(target)
    with opener.open(request, timeout=120) as response, target.open('xb') as output:
        if response.geturl() != url:
            raise ValueError('Unexpected final download URL')
        announced = response.headers.get('Content-Length')
        if announced and (not announced.isdigit() or int(announced) > max_bytes):
            raise ValueError('Invalid or oversized archive Content-Length')
        received = 0
        while block := response.read(1024 * 1024):
            received += len(block)
            if received > max_bytes:
                raise ValueError('Archive exceeds download limit')
            output.write(block)
        if announced and received != int(announced):
            raise ValueError('Truncated GIS download')
        if received == 0:
            raise ValueError('Empty GIS archive')
        return {'url': url, 'observedAtUTC': timestamp(), 'bytes': received,
                'httpLastModified': response.headers.get('Last-Modified'),
                'httpETag': response.headers.get('ETag'), 'origin': 'official_download'}


def inspect_extract(archive_path, output_dir, stem, *, max_expanded=MAX_EXPANDED_BYTES):
    """Validate every member before extracting; archive paths are never trusted."""
    archive_path, output_dir = Path(archive_path), Path(output_dir)
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('Local archive exceeds download limit')
    with archive_path.open('rb') as stream:
        if stream.read(4) != b'PK\x03\x04':
            raise ValueError('Expected a ZIP archive, not an HTML/error response')
    records = []
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_MEMBERS:
            raise ValueError('Unexpected archive member count')
        names, total = set(), 0
        for item in infos:
            name = item.filename
            pure = PurePosixPath(name)
            mode = item.external_attr >> 16
            if ('\\' in name or ':' in name or pure.is_absolute() or len(pure.parts) != 1
                    or name in ('.', '..') or stat.S_ISLNK(mode) or item.is_dir()):
                raise ValueError('Unsafe or nested archive member: ' + name)
            matched_stem = next((s for s in {stem} | COMPANION_STEMS.get(stem, set())
                                 if name.startswith(s + '.')), None)
            if matched_stem is None or name.casefold() in names:
                raise ValueError('Unexpected or duplicate archive member: ' + name)
            suffix = name[len(matched_stem):].lower()
            if suffix not in IMPORTANT | {'.sbn', '.sbx', '.xml', '.shp.xml'}:
                raise ValueError('Unsupported archive member: ' + name)
            if item.flag_bits & 1:
                raise ValueError('Encrypted archive member')
            names.add(name.casefold())
            total += item.file_size
            if (item.file_size > MAX_MEMBER_BYTES or total > max_expanded
                    or item.file_size > max(1, item.compress_size) * MAX_RATIO):
                raise ValueError('Archive expansion exceeds configured limits')
        required = {stem + suffix for suffix in IMPORTANT}
        if not required.issubset({i.filename for i in infos}):
            raise ValueError('Missing mandatory shapefile components')
        output_dir.mkdir(parents=True, exist_ok=False)
        for item in infos:
            target = output_dir / item.filename
            # Streaming reaches EOF and verifies CRC in Python's ZipExtFile.
            with archive.open(item) as source, target.open('xb') as output:
                copied = 0
                while block := source.read(1024 * 1024):
                    copied += len(block)
                    if copied > item.file_size:
                        raise ValueError('Member expanded beyond its declared size')
                    output.write(block)
            if copied != item.file_size:
                raise ValueError('Truncated archive member')
            records.append({'name': item.filename, 'bytes': copied, 'sha256': sha(target),
                            'zipTimestamp': list(item.date_time), 'crc32': f'{item.CRC:08x}'})
    projection = (output_dir / (stem + '.prj')).read_text(encoding='utf8').strip()
    if 'GCS_North_American_1983' not in projection or 'PROJCS' in projection:
        raise ValueError('Only explicit geographic NAD83 sources are supported')
    with (output_dir / (stem + '.dbf')).open('rb') as stream:
        header = stream.read(4)
    dbf_date = None
    if len(header) == 4:
        try:
            dbf_date = dt.date(1900 + header[1], header[2], header[3]).isoformat()
        except ValueError:
            pass
    important = {r['name']: r['sha256'] for r in records if Path(r['name']).suffix.lower() in IMPORTANT}
    return {'archiveSHA256': sha(archive_path), 'archiveBytes': archive_path.stat().st_size,
            'contentSHA256': canonical_sha(important), 'members': records,
            'dbfHeaderDate': dbf_date,
            'sourcePublicationTime': None,
            'timestampNote': 'HTTP/ZIP/DBF times are source metadata, not a verified publication date.'}


def processor_identity(viewer, config, origin):
    settings = json.loads(Path(config).read_text(encoding='utf8'))
    files = {name: sha(Path(viewer) / name) for name in SCRIPTS}
    return {'refreshVersion': VERSION, 'refreshScriptSHA256': sha(__file__),
            'classifierVersion': CLASSIFIER_VERSION, 'classifierConfig': settings,
            'classifierConfigSHA256': canonical_sha(settings), 'scripts': files,
            'sourceCRS': 'NAD83', 'tvdSign': 'positive', 'origin': list(origin),
            'sectionSource': 'recomputed'}


def compare_previous(sources, processor, previous):
    if previous is None:
        return {'contentChanged': list(SOURCES), 'archiveChanged': list(SOURCES),
                'processorChanged': True, 'rebuildRequired': True}
    if previous.get('status') != 'ready_for_review':
        raise ValueError('Previous run must be a fully validated ready_for_review run')
    old = previous.get('sources', {})
    content = [k for k in SOURCES if sources[k]['contentSHA256'] != old.get(k, {}).get('contentSHA256')]
    archives = [k for k in SOURCES if sources[k]['archiveSHA256'] != old.get(k, {}).get('archiveSHA256')]
    changed = canonical_sha(processor) != canonical_sha(previous.get('processor', {}))
    return {'contentChanged': content, 'archiveChanged': archives,
            'processorChanged': changed, 'rebuildRequired': bool(content or changed)}


def pipeline_commands(run_dir, viewer, config, source_date, origin, python=sys.executable):
    run_dir, viewer = Path(run_dir), Path(viewer)
    source = run_dir / 'sources'
    dataset, metrics, dsu = run_dir / 'dataset', run_dir / 'metrics', run_dir / 'dsu'
    horizontal = source / 'horizontals' / 'OGD_Horizontals.dbf'
    wells = source / 'wells' / 'OGD_Wells.dbf'
    archive = source / 'OGD_DrillingSpacingUnits.zip'
    def command(name, *args):
        return [python, str(viewer / name), *map(str, args)]
    return [
        ('geometry', command('prepare_data.py', horizontal, dataset, '--tvd-sign', 'positive',
                             '--source-crs', 'NAD83', '--origin', *origin,
                             '--classifier-config', config)),
        ('metrics', command('prepare_metrics.py', horizontal, dataset, metrics)),
        ('section_scales', command('prepare_section_scales.py', dataset, metrics)),
        ('operators', command('prepare_operators.py', wells, dataset, '--source-date', source_date)),
        ('well_names', command('prepare_well_names.py', wells, dataset, '--source-date', source_date)),
        ('dsu', command('prepare_dsu.py', archive, dsu / 'drilling-spacing-units.geojson')),
        ('membership', command('prepare_dsu_membership.py', dsu / 'drilling-spacing-units.geojson',
                               dataset, dsu / 'dsu-well-membership.json')),
    ]


def validate_outputs(run_dir):
    run_dir = Path(run_dir)
    read = lambda name: json.loads((run_dir / name).read_text(encoding='utf8'))
    manifest = read('dataset/manifest.json')
    metrics, quality = read('dataset/metrics.json'), read('dataset/metrics-validation.json')
    scales = read('dataset/section-metric-scales-validation.json')
    names, operators = read('dataset/well-names.json'), read('dataset/operators.json')
    dsu, membership = read('dsu/drilling-spacing-units.geojson'), read('dsu/dsu-well-membership.json')
    manifest_hash = sha(run_dir / 'dataset/manifest.json')
    if not manifest['wells'] or manifest['stations'] <= 0 or not dsu['features']:
        raise ValueError('Empty survey or DSU output')
    if not quality.get('passed') or not quality.get('geometryUnchanged') or not scales.get('passed'):
        raise ValueError('Metrics or section-scale validation failed')
    if metrics['source']['datasetManifestSHA256'] != manifest_hash or names['survey']['manifestSHA256'] != manifest_hash:
        raise ValueError('Derived survey metadata is stale')
    if operators['survey']['branchCount'] != len(manifest['wells']):
        raise ValueError('Operator metadata is misaligned')
    if membership['sourceHashes']['manifestSha256'] != manifest_hash:
        raise ValueError('DSU membership uses stale survey')
    if membership['sourceHashes']['dsuFileSha256'] != sha(run_dir / 'dsu/drilling-spacing-units.geojson'):
        raise ValueError('DSU membership uses stale boundaries')
    if set(membership['units']) != {f['id'] for f in dsu['features']}:
        raise ValueError('DSU membership identity coverage mismatch')
    sections = collections.Counter()
    for tile in manifest['tiles']:
        geometry_path = run_dir / 'dataset' / tile['file']
        if geometry_path.stat().st_size != tile['stations'] * 16:
            raise ValueError('Invalid geometry tile byte count')
        for _x, _y, _z, section in struct.iter_unpack('<ffff', geometry_path.read_bytes()):
            if section not in range(len(manifest['labels'])):
                raise ValueError('Invalid classified section code')
            sections[int(section)] += 1
    if sum(sections.values()) != manifest['stations']:
        raise ValueError('Classified section population mismatch')
    return {'passed': True, 'branches': len(manifest['wells']), 'stations': manifest['stations'],
            'dsuFeatures': len(dsu['features']), 'missingWellNames': names['coverage']['missingBranches'],
            'unknownOperators': operators['joinStats']['unknownBranches'],
            'sectionStationCounts': {label: sections[index] for index, label in enumerate(manifest['labels'])},
            'metricsQuality': {k: quality.get(k) for k in ('largeSurveyGaps', 'intervalsBelowPointOneFtMD',
                              'sourceAzimuthsOutside0To360', 'extremeValueCounts')},
            'missingPolicy': 'Unknown names/operators retained as missing; no zero inference.',
            'limitations': ['Mapped lateral overlap is not legal DSU membership or completed footage.',
                           'Production, formation zones, township footage and inventory scenarios are not rebuilt by this command.']}


def execute(args):
    runs = args.runs_dir.resolve()
    # Keep this tool confined to staging work, even if a caller supplies a live path.
    staging_root = (wp.WORK if WORKSPACE == wp.REPO else WORKSPACE / 'work').resolve()
    if not runs.is_relative_to(staging_root) or runs == staging_root:
        raise ValueError('--runs-dir must be a dedicated child of this workspace work directory')
    overrides = {}
    for entry in args.archive:
        key, separator, value = entry.partition('=')
        if not separator or key not in SOURCES or key in overrides or not value:
            raise ValueError('--archive requires a unique wells|horizontals|dsu=PATH mapping')
        overrides[key] = Path(value)
    previous = None
    if args.previous:
        previous = json.loads((args.previous / 'run.json').read_text(encoding='utf8'))
    identity = processor_identity(args.viewer_source, args.classifier_config, args.origin)
    run = runs / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12])
    run.mkdir(parents=True, exist_ok=False)
    sources_dir = run / 'sources'
    sources_dir.mkdir()
    report = {'version': 1, 'runId': run.name, 'createdAtUTC': timestamp(), 'status': 'acquiring',
              'stagingOnly': True, 'previousRun': str(args.previous) if args.previous else None,
              'processor': identity, 'sources': {}, 'steps': [], 'publicWebsiteUpdated': False,
              'sqlImported': False, 'schedulingEnabled': False}
    write_json(run / 'run.json', report)
    try:
        # Copy executable processors/settings once; concurrent source edits cannot change this run.
        processors = run / 'processors'
        processors.mkdir()
        for name in SCRIPTS:
            shutil.copyfile(args.viewer_source / name, processors / name)
            if sha(processors / name) != identity['scripts'][name]:
                raise ValueError('Processor source changed during snapshot')
        config = processors / 'classifier-settings.json'
        write_json(config, identity['classifierConfig'])
        for key, url in SOURCES.items():
            archive = sources_dir / url.rsplit('/', 1)[-1]
            if args.source_dir or key in overrides:
                incoming = overrides.get(key) or args.source_dir / archive.name
                if incoming.stat().st_size > MAX_ARCHIVE_BYTES:
                    raise ValueError('Local archive exceeds limit')
                shutil.copyfile(incoming, archive)
                metadata = {'url': url, 'observedAtUTC': timestamp(), 'origin': 'provided_local_archive',
                            'localSourcePath': str(incoming.resolve()), 'httpLastModified': None, 'httpETag': None}
            else:
                metadata = download(url, archive)
            metadata.update(inspect_extract(archive, sources_dir / key, archive.stem))
            report['sources'][key] = metadata
            write_json(run / 'run.json', report)
        report['comparison'] = compare_previous(report['sources'], identity, previous)
        if not report['comparison']['rebuildRequired']:
            report.update(status='no_change', reusedValidatedRun=str(args.previous))
        elif args.acquire_only:
            report['status'] = 'acquired_not_processed'
        else:
            report['status'] = 'processing'
            (run / 'logs').mkdir()
            (run / 'dsu').mkdir()
            # Name/operator sidecars require a calendar snapshot date. Label it explicitly as
            # observation date, rather than claiming a source publication time we do not know.
            observed_date = report['createdAtUTC'][:10]
            for step, command in pipeline_commands(run, processors, config, observed_date, args.origin):
                report['steps'].append({'name': step, 'status': 'running', 'startedAtUTC': timestamp()})
                write_json(run / 'run.json', report)
                with (run / 'logs' / (step + '.log')).open('wb') as log:
                    subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT,
                                   cwd=run, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
                if step == 'geometry':
                    path = run / 'dataset/manifest.json'
                    manifest = json.loads(path.read_text(encoding='utf8'))
                    manifest['sourceSnapshot'] = {'date': observed_date, 'dateMeaning': 'observed_at_not_verified_publication',
                        'archiveSHA256': report['sources']['horizontals']['archiveSHA256'],
                        'contentSHA256': report['sources']['horizontals']['contentSHA256'], 'refreshRunId': run.name}
                    write_json(path, manifest)
                if step == 'section_scales':
                    for item in (run / 'metrics').iterdir():
                        if item.is_file() and not item.name.startswith('.'):
                            shutil.copyfile(item, run / 'dataset' / item.name)
                report['steps'][-1].update(status='completed', finishedAtUTC=timestamp())
            report['validation'] = validate_outputs(run)
            report['status'] = 'ready_for_review'
        report['finishedAtUTC'] = timestamp()
        write_json(run / 'run.json', report)
        return run, report
    except Exception as error:
        report.update(status='failed', finishedAtUTC=timestamp(), error=f'{type(error).__name__}: {error}')
        if report['steps'] and report['steps'][-1]['status'] == 'running':
            report['steps'][-1]['status'] = 'failed'
        write_json(run / 'run.json', report)
        raise


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true', help='Print a plan without downloads or writes (default)')
    mode.add_argument('--execute', action='store_true', help='Acquire and process a new staging run')
    result.add_argument('--acquire-only', action='store_true', help='Validate/download only; candidate is not ready')
    result.add_argument('--source-dir', type=Path, help='Read the three official-name ZIPs locally instead of downloading')
    result.add_argument('--archive', action='append', default=[], metavar='SOURCE=PATH',
                        help='Explicit local wells|horizontals|dsu archive; overrides --source-dir for that source')
    result.add_argument('--previous', type=Path, help='Previous validated run directory for no-change detection')
    result.add_argument('--runs-dir', type=Path, default=wp.WORK / 'staging-gis-runs')
    result.add_argument('--viewer-source', type=Path, default=VIEWER)
    result.add_argument('--classifier-config', type=Path, default=VIEWER / 'classifier-settings.json')
    result.add_argument('--origin', nargs=2, type=float, default=DEFAULT_ORIGIN, metavar=('LONGITUDE', 'LATITUDE'))
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if not (-180 <= args.origin[0] <= 180 and -89 <= args.origin[1] <= 89):
        raise ValueError('Invalid fixed geographic origin')
    if not args.execute:
        print(json.dumps({'mode': 'plan', 'writes': False, 'downloads': False, 'stagingOnly': True,
                          'sources': SOURCES, 'origin': args.origin,
                          'pipeline': [name for name, _ in pipeline_commands(Path('<new-run>'), args.viewer_source,
                                      args.classifier_config, '<observation-date>', args.origin)],
                          'sectionSource': 'Always recomputed; preserved source labels are unsupported.',
                          'deferred': ['production refresh pending supplied data', 'formation-zone display estimates',
                                       'township/DSU inventory footage builder requires removal of Oct17 hardcoded guards',
                                       'scheduling', 'SQL import', 'public publication']}, indent=2))
        return 0
    run, report = execute(args)
    print(json.dumps({'run': str(run), 'status': report['status'], 'publicWebsiteUpdated': False}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
