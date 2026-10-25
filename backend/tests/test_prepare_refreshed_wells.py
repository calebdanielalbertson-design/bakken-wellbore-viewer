"""Offline bridge checks; no source rebuild, SQL writes, network or deployment."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_refreshed_wells as bridge
import refresh_gis as refresh


class RefreshedWellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='well-refresh-', dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'run-test'
        self.run.mkdir()
        self.audit, self.production = self.root / 'historical.sqlite', self.root / 'production.json'
        self.audit.write_bytes(b'existing audit stand-in; builder is mocked')
        self.production.write_text('{}')
        self.sources = {}
        for key, url in refresh.SOURCES.items():
            filename = url.rsplit('/', 1)[-1]
            stem = Path(filename).stem
            self.put('sources/' + filename, b'archive-' + key.encode())
            members = []
            for ext in sorted(refresh.IMPORTANT):
                relative = 'sources/' + key + '/' + stem + ext
                self.put(relative, b'fixture component ' + relative.encode())
                members.append({'name': stem + ext, 'bytes': (self.run / relative).stat().st_size,
                                'sha256': self.sha(relative)})
            self.sources[key] = {'url': url, 'archiveSHA256': self.sha('sources/' + filename),
                'archiveBytes': (self.run / 'sources' / filename).stat().st_size,
                'contentSHA256': refresh.canonical_sha({m['name']: m['sha256'] for m in members}),
                'members': members, 'observedAtUTC': '2026-10-18T02:00:00+00:00',
                'dbfHeaderDate': '2026-10-17', 'sourcePublicationTime': None}
        scripts = {}
        for name in refresh.SCRIPTS:
            self.put('processors/' + name, ('copied ' + name).encode())
            scripts[name] = self.sha('processors/' + name)
        self.put_json('processors/classifier-settings.json', {})
        self.processor = {'refreshVersion': refresh.VERSION, 'refreshScriptSHA256': refresh.sha(refresh.__file__),
            'scripts': scripts, 'classifierConfig': {}, 'classifierConfigSHA256': refresh.canonical_sha({}),
            'sectionSource': 'recomputed', 'sourceCRS': 'NAD83', 'tvdSign': 'positive',
            'origin': [-103, 48], 'classifierVersion': '2.0'}
        manifest = {'sourceCRS': 'NAD83', 'origin': [-103, 48], 'tvdSign': 'positive',
            'classifier': {'version': '2.0', 'parameters': {}, 'sectionSource': 'recomputed'},
            'sourceSnapshot': {'date': '2026-10-18', 'dateMeaning': 'observed_at_not_verified_publication',
                'refreshRunId': self.run.name, 'archiveSHA256': self.sources['horizontals']['archiveSHA256'],
                'contentSHA256': self.sources['horizontals']['contentSHA256']},
            'wells': [{'id': 0}], 'stations': 2, 'labels': ['Vertical', 'Lateral'],
            'tiles': [{'id': 'a', 'file': 'a.bin', 'stations': 2}]}
        self.put_json('dataset/manifest.json', manifest)
        self.put('dataset/a.bin', struct.pack('<8f', 0, -100, 0, 0, 100, -100, 0, 1))
        self.put('dataset/a.metrics.bin', struct.pack('<16f', *range(16)))
        self.put('dataset/overview.bin', b'overview')
        self.put_json('dataset/metrics.json', {'tiles': [{'id': 'a', 'file': 'a.metrics.bin', 'count': 2}],
            'source': {'sha256': self.sha('sources/horizontals/OGD_Horizontals.dbf'),
                       'datasetManifestSHA256': self.sha('dataset/manifest.json'),
                       'overviewSHA256': self.sha('dataset/overview.bin'),
                       'tileGeometrySHA256ManifestOrder': self.sha('dataset/a.bin')}})
        self.put_json('dataset/metrics-validation.json', {'passed': True, 'geometryUnchanged': True})
        self.put_json('dataset/section-metric-scales-validation.json', {
            **{k: True for k in ('passed', 'geometryBinaryUnchanged', 'metricsBinariesUnchanged',
                'allMetricCountsAccountForFiniteAndMissingStations', 'allQuantilesWithinObservedRanges')},
            'geometrySHA256ManifestOrder': self.sha('dataset/a.bin'),
            'metricsSHA256ManifestOrder': self.sha('dataset/a.metrics.bin')})
        self.put_json('dataset/section-metric-scales.json', {})
        self.put_json('dataset/well-names.json', {'source': {'dbfSHA256': self.sha('sources/wells/OGD_Wells.dbf')},
            'survey': {'manifestSHA256': self.sha('dataset/manifest.json')}, 'coverage': {'missingBranches': 0}})
        self.put_json('dataset/operators.json', {'provenance': {'wellSourceSHA256': self.sha('sources/wells/OGD_Wells.dbf')},
            'survey': {'branchCount': 1}, 'joinStats': {'unknownBranches': 0}})
        features = [{'id': 'dsu-a', 'geometry': {'type': 'Polygon', 'coordinates': []}}]
        self.put_json('dsu/drilling-spacing-units.geojson', {'features': features,
            'metadata': {'archiveSha256': self.sources['dsu']['archiveSHA256']}})
        binding = {'manifestSha256': self.sha('dataset/manifest.json'),
            'metricsManifestSha256': self.sha('dataset/metrics.json'),
            'dsuFileSha256': self.sha('dsu/drilling-spacing-units.geojson'),
            'dsuGeometryAndIdsSha256': refresh.canonical_sha([[f['id'], f['geometry']] for f in features]),
            'chunks': [{'id': 'a', 'geometrySha256': self.sha('dataset/a.bin'),
                        'metricsSha256': self.sha('dataset/a.metrics.bin')}]}
        self.put_json('dsu/dsu-well-membership.json', {'sourceHashes': binding, 'units': {'dsu-a': []}})
        self.put_json('dsu/dsu-well-membership.audit.json', {'sourceHashes': binding, 'lengthAnomalies': []})
        self.report = {'runId': self.run.name, 'status': 'ready_for_review', 'stagingOnly': True,
            'createdAtUTC': '2026-10-18T02:00:00+00:00', 'sources': self.sources, 'processor': self.processor,
            'steps': [{'name': name, 'status': 'completed'} for name in bridge.STEPS],
            'validation': refresh.validate_outputs(self.run)}
        self.put_json('run.json', self.report)

    def put(self, name, value):
        path = self.run / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def put_json(self, name, value):
        self.put(name, json.dumps(value).encode())

    def sha(self, name):
        return refresh.sha(self.run / name)

    def prepare(self, **kwargs):
        return bridge.prepare(self.run, production_db=self.audit, production_meta=self.production, **kwargs)

    def test_default_plan_maps_fresh_gis_historical_production_and_withholds_inventory(self):
        with mock.patch.object(bridge.builder, 'build_bundle') as build:
            plan = self.prepare()
        build.assert_not_called()
        self.assertFalse(plan['writes'])
        self.assertFalse(plan['sql_imported'])
        self.assertIsNone(plan['inputs']['footage_path'])
        self.assertEqual(plan['inputs']['production_db'], str(self.audit.resolve()))
        self.assertEqual(plan['inputs']['wells_dbf'], str(self.run / 'sources/wells/OGD_Wells.dbf'))
        self.assertEqual(plan['inputs']['manifest_path'], str(self.run / 'dataset/manifest.json'))
        self.assertEqual(plan['inputs']['dsu_path'], str(self.run / 'dsu/drilling-spacing-units.geojson'))
        self.assertEqual(plan['refresh']['source_date_meaning'], 'observed_at_not_verified_publication')
        self.assertIsNone(plan['refresh']['sources']['wells']['sourcePublicationTime'])
        self.assertEqual(plan['refresh']['sources']['wells']['dbfHeaderDate'], '2026-10-17')

    def test_failed_unprocessed_nochange_and_failed_validation_rejected(self):
        for status in ('failed', 'processing', 'acquired_not_processed', 'no_change'):
            with self.subTest(status=status):
                self.put_json('run.json', dict(self.report, status=status))
                with self.assertRaisesRegex(ValueError, 'ready_for_review'):
                    self.prepare()
        self.put_json('run.json', dict(self.report, validation={'passed': False}))
        with self.assertRaisesRegex(ValueError, 'validation summary'):
            self.prepare()

    def test_changed_source_processor_and_metric_binary_rejected(self):
        for name in ('sources/wells/OGD_Wells.dbf', 'processors/classifier.py', 'dataset/a.metrics.bin'):
            with self.subTest(name=name):
                original = (self.run / name).read_bytes()
                self.put(name, original + b'changed')
                with self.assertRaisesRegex(ValueError, 'hash'):
                    self.prepare()
                self.put(name, original)

    def test_execute_passes_explicit_inputs_and_checks_again_before_ready(self):
        def build(destination, **kwargs):
            self.assertEqual(destination, self.root / 'fresh-bundle')
            self.assertIsNone(kwargs['footage_path'])
            self.assertEqual(kwargs['names_path'], self.run / 'dataset/well-names.json')
            self.assertEqual(kwargs['membership_path'], self.run / 'dsu/dsu-well-membership.json')
            kwargs['finalize_check']()
            self.put('processors/classifier.py', b'changed during build')
            with self.assertRaisesRegex(ValueError, 'changed'):
                kwargs['finalize_check']()
            return {'release_id': 'fixture-release', 'counts': {},
                    'source_date_meaning': 'observed_at_not_verified_publication',
                    'measured_dsu_acres_status': 'unavailable_inventory_not_rebuilt'}
        # Execute mode only writes beneath the work directory; point it at this test's temp root.
        with mock.patch.object(bridge.builder.wp, 'WORK', self.root), \
                mock.patch.object(bridge.builder, 'build_bundle', side_effect=build) as called:
            result = self.prepare(execute=True, output=self.root / 'fresh-bundle')
        self.assertEqual(called.call_count, 1)
        self.assertFalse(result['cloud_updated'])
        self.assertFalse(result['sql_imported'])


if __name__ == '__main__':
    unittest.main()
