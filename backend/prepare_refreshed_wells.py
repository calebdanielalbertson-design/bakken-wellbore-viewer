"""Verify a ready GIS refresh and optionally build a new local SQL input bundle.

Default is a read-only plan. --execute writes a fresh bundle, never SQL/cloud.
Historical production is reused explicitly; old inventory acreage is withheld.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

# Keep the default plan from creating local import caches as a side effect.
sys.dont_write_bytecode = True

import build_well_bundle as builder
import refresh_gis as refresh

DEFAULT_AUDIT = builder.ROOT / 'work/nd-refresh-2026-10-17/production/production-audit.sqlite'
DEFAULT_PRODUCTION_META = builder.FULL / 'production.json'
STEPS = ['geometry', 'metrics', 'section_scales', 'operators', 'well_names', 'dsu', 'membership']


def require(condition, message):
    if not condition:
        raise ValueError(message)


def plain_name(value):
    require(isinstance(value, str) and bool(value) and value not in ('.', '..')
            and not any(c in value for c in '/\\:'), 'Unsafe file name in run metadata')
    return value


def validate_run(run_dir):
    """Recheck recorded sources/processors plus all existing output hash bindings."""
    root = Path(run_dir).resolve()
    verified = {}

    def path(relative):
        item = root / relative
        require(not item.is_symlink() and item.resolve().is_relative_to(root) and item.is_file(),
                'Missing or linked run input: ' + str(relative))
        return item

    def fingerprint(relative):
        item = path(relative)
        if item not in verified:
            verified[item] = builder.digest(item)
        return verified[item]

    def read(relative):
        fingerprint(relative)
        return json.loads(path(relative).read_bytes())

    report = read('run.json')
    require(report.get('status') == 'ready_for_review' and report.get('stagingOnly') is True,
            'Run must be ready_for_review in staging')
    require(report.get('runId') == root.name, 'Run directory identity mismatch')
    require([(x.get('name'), x.get('status')) for x in report.get('steps', [])]
            == [(name, 'completed') for name in STEPS], 'Incomplete or unexpected processor steps')
    processor = report['processor']
    require(processor['refreshVersion'] == refresh.VERSION
            and processor['refreshScriptSHA256'] == builder.digest(refresh.__file__),
            'Refresh processor version/hash changed; review before preparing SQL')
    require(set(processor['scripts']) == set(refresh.SCRIPTS), 'Processor script inventory mismatch')
    for name, expected in processor['scripts'].items():
        require(fingerprint('processors/' + plain_name(name)) == expected, 'Copied processor hash mismatch: ' + name)
    config = read('processors/classifier-settings.json')
    require(config == processor['classifierConfig']
            and refresh.canonical_sha(config) == processor['classifierConfigSHA256'], 'Classifier configuration hash mismatch')
    require(processor.get('sectionSource') == 'recomputed' and processor.get('sourceCRS') == 'NAD83'
            and processor.get('tvdSign') == 'positive', 'Unsupported survey processing policy')
    require(set(report['sources']) == set(refresh.SOURCES), 'Source archive inventory mismatch')
    source_summary = {}
    for key, url in refresh.SOURCES.items():
        source = report['sources'][key]
        archive_name = url.rsplit('/', 1)[-1]
        require(source['url'] == url, 'Unexpected source URL')
        archive = path('sources/' + archive_name)
        require(fingerprint('sources/' + archive_name) == source['archiveSHA256']
                and archive.stat().st_size == source['archiveBytes'], 'Source archive hash/size mismatch: ' + key)
        members, important = set(), {}
        for member in source['members']:
            name = plain_name(member['name'])
            require(name.casefold() not in members, 'Duplicate source component')
            members.add(name.casefold())
            relative = 'sources/' + key + '/' + name
            require(fingerprint(relative) == member['sha256'] and path(relative).stat().st_size == member['bytes'],
                    'Source component hash/size mismatch: ' + name)
            if Path(name).suffix.lower() in refresh.IMPORTANT:
                important[name] = member['sha256']
        stem = Path(archive_name).stem
        require({(stem + ext).casefold() for ext in refresh.IMPORTANT} <= members,
                'Mandatory source components absent')
        require(refresh.canonical_sha(important) == source['contentSHA256'], 'Source content hash mismatch')
        source_summary[key] = {k: source.get(k) for k in (
            'url', 'observedAtUTC', 'archiveSHA256', 'contentSHA256', 'dbfHeaderDate',
            'httpLastModified', 'sourcePublicationTime', 'timestampNote')}
    manifest = read('dataset/manifest.json')
    snapshot = manifest.get('sourceSnapshot', {})
    require(snapshot.get('refreshRunId') == report['runId']
            and snapshot.get('date') == report['createdAtUTC'][:10]
            and snapshot.get('dateMeaning') == 'observed_at_not_verified_publication'
            and snapshot.get('archiveSHA256') == report['sources']['horizontals']['archiveSHA256']
            and snapshot.get('contentSHA256') == report['sources']['horizontals']['contentSHA256'],
            'Survey observation/source revision mismatch')
    require(manifest['sourceCRS'] == processor['sourceCRS'] and manifest['origin'] == processor['origin']
            and manifest['tvdSign'] == processor['tvdSign']
            and manifest['classifier']['version'] == processor['classifierVersion']
            and manifest['classifier']['parameters'] == config
            and manifest['classifier']['sectionSource'] == 'recomputed', 'Survey classifier/projection mismatch')
    names, operators = read('dataset/well-names.json'), read('dataset/operators.json')
    wells_hash = fingerprint('sources/wells/OGD_Wells.dbf')
    require(names['source']['dbfSHA256'] == wells_hash
            and operators['provenance']['wellSourceSHA256'] == wells_hash, 'Well metadata uses a different registry')
    metrics = read('dataset/metrics.json')
    quality = read('dataset/metrics-validation.json')
    scales = read('dataset/section-metric-scales-validation.json')
    read('dataset/section-metric-scales.json')
    require(metrics['source']['sha256'] == fingerprint('sources/horizontals/OGD_Horizontals.dbf'),
            'Metrics use a different source survey')
    require(metrics['source']['overviewSHA256'] == fingerprint('dataset/overview.bin'), 'Survey overview hash mismatch')
    require(all(scales.get(k) is True for k in ('passed', 'geometryBinaryUnchanged', 'metricsBinariesUnchanged',
            'allMetricCountsAccountForFiniteAndMissingStations', 'allQuantilesWithinObservedRanges'))
            and quality.get('passed') is True and quality.get('geometryUnchanged') is True,
            'Output validation did not pass')
    dsus = read('dsu/drilling-spacing-units.geojson')
    membership = read('dsu/dsu-well-membership.json')
    audit = read('dsu/dsu-well-membership.audit.json')
    binding = membership['sourceHashes']
    require(dsus['metadata']['archiveSha256'] == report['sources']['dsu']['archiveSHA256'], 'DSU source archive mismatch')
    require(binding['metricsManifestSha256'] == fingerprint('dataset/metrics.json')
            and binding == audit['sourceHashes'] and not audit.get('lengthAnomalies'), 'Membership validation/hash mismatch')
    geometry_ids = [[f['id'], f['geometry']] for f in dsus['features']]
    require(binding['dsuGeometryAndIdsSha256'] == refresh.canonical_sha(geometry_ids), 'DSU geometry/identity hash mismatch')
    tiles = {t['id']: t for t in manifest['tiles']}
    measured = {t['id']: t for t in metrics['tiles']}
    chunks = {t['id']: t for t in binding['chunks']}
    require(len(tiles) == len(manifest['tiles']) and len(measured) == len(metrics['tiles'])
            and len(chunks) == len(binding['chunks']) and set(tiles) == set(measured) == set(chunks),
            'Tile/hash inventory mismatch')
    geometry_digest, metrics_digest = hashlib.sha256(), hashlib.sha256()
    for tile in manifest['tiles']:
        tile_id = tile['id']
        for item, size, expected, combined in (
            (tile, tile['stations'] * 16, chunks[tile_id]['geometrySha256'], geometry_digest),
            (measured[tile_id], tile['stations'] * 32, chunks[tile_id]['metricsSha256'], metrics_digest)):
            relative = 'dataset/' + plain_name(item['file'])
            require(path(relative).stat().st_size == size and fingerprint(relative) == expected, 'Tile binary hash/size mismatch')
            with path(relative).open('rb') as stream:
                while block := stream.read(1024 * 1024):
                    combined.update(block)
    require(geometry_digest.hexdigest() == metrics['source']['tileGeometrySHA256ManifestOrder']
            == scales['geometrySHA256ManifestOrder'] and metrics_digest.hexdigest() == scales['metricsSHA256ManifestOrder'],
            'Combined geometry/metric validation hash mismatch')
    validation = refresh.validate_outputs(root)
    require(validation == report.get('validation'), 'Run validation summary changed')
    context = {'run_id': report['runId'], 'run_sha256': fingerprint('run.json'),
        'bridge_sha256': builder.digest(__file__), 'observed_at': report['createdAtUTC'],
        'source_date_meaning': snapshot['dateMeaning'], 'sources': source_summary, 'processor': processor,
        'validated_files': {p.relative_to(root).as_posix(): h for p, h in verified.items()},
        'production_policy': 'Reuse supplied historical audit; GIS observation time does not extend production coverage.',
        'inventory_policy': 'Measured DSU acres and inventory scenarios withheld; only source nominal acres retained.'}
    return root, context, verified


def prepare(run_dir, *, output=None, execute=False, production_db=DEFAULT_AUDIT,
            production_meta=DEFAULT_PRODUCTION_META):
    root, context, verified = validate_run(run_dir)
    audit, production = Path(production_db).resolve(), Path(production_meta).resolve()
    require(audit.is_file() and production.is_file() and not Path(str(audit) + '-wal').exists(),
            'A stable existing historical production audit and metadata are required')
    for item in (audit, production):
        verified[item] = builder.digest(item)
    context['historical_production'] = {key: {'name': item.name, 'sha256': verified[item]}
                                      for key, item in [('audit', audit), ('metadata', production)]}
    inputs = {'wells_dbf': root / 'sources/wells/OGD_Wells.dbf',
              'manifest_path': root / 'dataset/manifest.json', 'names_path': root / 'dataset/well-names.json',
              'dsu_path': root / 'dsu/drilling-spacing-units.geojson',
              'membership_path': root / 'dsu/dsu-well-membership.json',
              'production_db': audit, 'production_meta': production, 'footage_path': None}
    destination = Path(output).resolve() if output else None
    if destination:
        work = (builder.ROOT / 'work').resolve()
        require(destination.is_relative_to(work) and destination != work and not destination.is_relative_to(root),
                'Output must be a separate new child of the workspace work directory')
        require(not destination.exists(), 'Output must be a fresh directory')
    plan = {'mode': 'execute' if execute else 'plan', 'writes': bool(execute), 'sql_imported': False,
            'cloud_updated': False, 'run_id': context['run_id'], 'refresh': context,
            'inputs': {k: str(v) if v is not None else None for k, v in inputs.items()},
            'output': str(destination) if destination else None}
    if not execute:
        return plan
    require(destination is not None, '--output is required with --execute')

    def unchanged():
        require(all(item.is_file() and builder.digest(item) == expected for item, expected in verified.items()),
                'A verified refresh input changed; release not published')

    result = builder.build_bundle(destination, **inputs, refresh_context=context, finalize_check=unchanged)
    return {k: plan[k] for k in ('mode', 'writes', 'sql_imported', 'cloud_updated', 'run_id', 'output')} | {
        'release_id': result['release_id'], 'counts': result['counts'],
        'source_date_meaning': result['source_date_meaning'],
        'measured_dsu_acres_status': result['measured_dsu_acres_status']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--production-db', type=Path, default=DEFAULT_AUDIT)
    parser.add_argument('--production-meta', type=Path, default=DEFAULT_PRODUCTION_META)
    args = parser.parse_args(argv)
    result = prepare(args.run, output=args.output, execute=args.execute,
                     production_db=args.production_db, production_meta=args.production_meta)
    # Detailed verified hashes remain in the returned plan/release; keep CLI output readable.
    if 'refresh' in result:
        result['refresh'] = {k: v for k, v in result['refresh'].items() if k not in ('validated_files', 'processor')}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
