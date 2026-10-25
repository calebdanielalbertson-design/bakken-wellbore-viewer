"""Offline refresh tests: archive attacks, revision identity, failure isolation.

No network access, real geometry rebuild, cloud writes or public outputs.
"""
from __future__ import annotations
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import struct
import unittest
from unittest import mock
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import refresh_gis as refresh

PRJ = b'GEOGCS["GCS_North_American_1983",DATUM["D_North_American_1983"]]'


def archive(path, stem='OGD_Wells', extra=None, *, stamp=(2026, 10, 17, 12, 0, 0), content=b'survey'):
    entries = {stem + '.dbf': bytes([3, 126, 10, 17]) + content,
               stem + '.shp': content, stem + '.shx': b'index',
               stem + '.prj': PRJ, stem + '.cpg': b'UTF-8'}
    entries.update(extra or {})
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as output:
        for name, data in entries.items():
            item = zipfile.ZipInfo(name, stamp)
            item.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(item, data)
    return path


class Response(io.BytesIO):
    def __init__(self, data, headers=None, url=None):
        super().__init__(data)
        self.headers = headers or {}
        self.url = url or refresh.SOURCES['wells']

    def geturl(self):
        return self.url


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='refresh-test-', dir=PROJECT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def inspect(self, path, **kwargs):
        return refresh.inspect_extract(path, self.root / 'extracted', 'OGD_Wells', **kwargs)

    def test_valid_archive_records_components_and_source_timestamp_limits(self):
        result = self.inspect(archive(self.root / 'wells.zip'))
        self.assertEqual(len(result['members']), 5)
        self.assertEqual(result['dbfHeaderDate'], '2026-10-17')
        self.assertIsNone(result['sourcePublicationTime'])
        self.assertEqual(len(result['contentSHA256']), 64)

    def test_repackaged_archive_preserves_content_identity(self):
        one = archive(self.root / 'one.zip')
        two = archive(self.root / 'two.zip', stamp=(2026, 10, 18, 12, 0, 0))
        a = refresh.inspect_extract(one, self.root / 'a', 'OGD_Wells')
        b = refresh.inspect_extract(two, self.root / 'b', 'OGD_Wells')
        self.assertNotEqual(a['archiveSHA256'], b['archiveSHA256'])
        self.assertEqual(a['contentSHA256'], b['contentSHA256'])

    def test_changed_survey_content_changes_identity(self):
        a = refresh.inspect_extract(archive(self.root / 'a.zip'), self.root / 'a', 'OGD_Wells')
        b = refresh.inspect_extract(archive(self.root / 'b.zip', content=b'new survey'), self.root / 'b', 'OGD_Wells')
        self.assertNotEqual(a['contentSHA256'], b['contentSHA256'])

    def test_official_horizontal_companion_is_allowed_without_arbitrary_prefixes(self):
        path = archive(self.root / 'horizontal.zip', stem='OGD_Horizontals',
                       extra={'OGD_Horizontals_Line.cpg': b'UTF-8', 'OGD_Horizontals_Line.shp': b'line'})
        result = refresh.inspect_extract(path, self.root / 'horizontal', 'OGD_Horizontals')
        self.assertEqual(len(result['members']), 7)

    def test_unsafe_paths_are_rejected_before_extraction(self):
        for index, name in enumerate(('../escape.dbf', '/absolute.dbf', 'C:\\escape.dbf',
                                      'OGD_Wells/evil.dbf', 'OGD_Wells.exe')):
            with self.subTest(name=name):
                path = archive(self.root / f'bad-{index}.zip', extra={name: b'bad'})
                with self.assertRaises(ValueError):
                    self.inspect(path)
                self.assertFalse((self.root / 'extracted').exists())

    def test_duplicate_members_rejected(self):
        path = archive(self.root / 'duplicate.zip')
        with zipfile.ZipFile(path, 'a') as output:
            output.writestr('ogd_wells.dbf', b'duplicate')
        with self.assertRaisesRegex(ValueError, 'Unexpected or duplicate'):
            self.inspect(path)

    def test_symlink_rejected(self):
        path = archive(self.root / 'link.zip')
        with zipfile.ZipFile(path, 'a') as output:
            item = zipfile.ZipInfo('OGD_Wells.xml')
            item.create_system = 3
            item.external_attr = 0o120777 << 16
            output.writestr(item, '../escape')
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            self.inspect(path)

    def test_expansion_limit_rejected(self):
        with self.assertRaisesRegex(ValueError, 'expansion'):
            self.inspect(archive(self.root / 'large.zip'), max_expanded=10)

    def test_missing_component_rejected(self):
        path = self.root / 'missing.zip'
        with zipfile.ZipFile(path, 'w') as output:
            output.writestr('OGD_Wells.dbf', b'dbf')
        with self.assertRaisesRegex(ValueError, 'Missing mandatory'):
            self.inspect(path)

    def test_crc_failure_cannot_be_accepted(self):
        path = self.root / 'corrupt.zip'
        archive(path)
        with zipfile.ZipFile(path) as source:
            item = source.getinfo('OGD_Wells.dbf')
            position = item.header_offset + 30 + len(item.filename.encode()) + len(item.extra)
        data = bytearray(path.read_bytes())
        data[position + 2] ^= 0x01
        path.write_bytes(data)
        with self.assertRaises((zipfile.BadZipFile, RuntimeError)):
            self.inspect(path)

    def test_html_error_is_not_a_zip(self):
        path = self.root / 'html.zip'
        path.write_text('<html>error</html>')
        with self.assertRaisesRegex(ValueError, 'HTML/error'):
            self.inspect(path)

    def test_projected_source_is_not_implicitly_accepted(self):
        path = archive(self.root / 'projection.zip', extra={'OGD_Wells.prj': b'PROJCS["GCS_North_American_1983"]'})
        with self.assertRaisesRegex(ValueError, 'geographic NAD83'):
            self.inspect(path)

    def test_download_allowlist_rejects_arbitrary_url_before_open(self):
        opener = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'allowlisted'):
            refresh.download('http://127.0.0.1/private', self.root / 'out.zip', opener=opener)
        opener.open.assert_not_called()

    def test_download_hard_limit_applies_without_content_length(self):
        opener = mock.Mock()
        opener.open.return_value = Response(b'x' * 11)
        with self.assertRaisesRegex(ValueError, 'download limit'):
            refresh.download(refresh.SOURCES['wells'], self.root / 'out.zip', opener=opener, max_bytes=10)

    def test_download_rejects_oversized_and_truncated_responses(self):
        for label, data, length in [('large', b'a', '20'), ('short', b'a', '5')]:
            with self.subTest(label=label):
                opener = mock.Mock()
                opener.open.return_value = Response(data, {'Content-Length': length})
                with self.assertRaises(ValueError):
                    refresh.download(refresh.SOURCES['wells'], self.root / (label + '.zip'), opener=opener, max_bytes=10)

    def test_download_final_url_and_redirects_are_rejected(self):
        opener = mock.Mock()
        opener.open.return_value = Response(b'zip', url='https://elsewhere.invalid/file.zip')
        with self.assertRaisesRegex(ValueError, 'final download URL'):
            refresh.download(refresh.SOURCES['wells'], self.root / 'out.zip', opener=opener)
        with self.assertRaisesRegex(ValueError, 'redirected'):
            refresh.NoRedirect().redirect_request(None, None, 302, None, {}, 'https://elsewhere.invalid')

    def test_no_change_ignores_container_repacking_but_rebuilds_new_processor(self):
        sources = {k: {'contentSHA256': 'same', 'archiveSHA256': 'repacked'} for k in refresh.SOURCES}
        old_sources = {k: {'contentSHA256': 'same', 'archiveSHA256': 'old'} for k in refresh.SOURCES}
        previous = {'status': 'ready_for_review', 'sources': old_sources, 'processor': {'classifier': 'v2'}}
        result = refresh.compare_previous(sources, {'classifier': 'v2'}, previous)
        self.assertFalse(result['rebuildRequired'])
        self.assertEqual(result['archiveChanged'], list(refresh.SOURCES))
        self.assertTrue(refresh.compare_previous(sources, {'classifier': 'v3'}, previous)['rebuildRequired'])

    def test_failed_or_unprocessed_run_cannot_be_last_good(self):
        with self.assertRaisesRegex(ValueError, 'fully validated'):
            refresh.compare_previous({}, {}, {'status': 'failed'})

    def test_pipeline_order_recomputes_and_stays_inside_candidate(self):
        candidate = self.root / 'candidate'
        commands = refresh.pipeline_commands(candidate, refresh.VIEWER, refresh.VIEWER / 'classifier-settings.json', '2026-10-17', refresh.DEFAULT_ORIGIN)
        self.assertEqual([name for name, _ in commands], ['geometry', 'metrics', 'section_scales', 'operators', 'well_names', 'dsu', 'membership'])
        self.assertNotIn('--preserve-sections', commands[0][1])
        self.assertIn('--classifier-config', commands[0][1])
        self.assertIn(str(candidate / 'dataset'), commands[0][1])
        self.assertIn(str(candidate / 'dsu/dsu-well-membership.json'), commands[-1][1])

    def test_default_plan_does_not_acquire_or_create_directories(self):
        with mock.patch.object(refresh, 'execute') as execute, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(refresh.main([]), 0)
        execute.assert_not_called()
        result = json.loads(output.getvalue())
        self.assertFalse(result['writes'])
        self.assertFalse(result['downloads'])

    def test_existing_label_flags_are_rejected(self):
        for flag in ('--use-existing-labels', '--preserve-sections'):
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                refresh.parser().parse_args([flag])

    def test_failure_preserves_previous_run_and_records_failed_candidate(self):
        work = self.root / 'work'
        previous = work / 'runs' / 'previous'
        previous.mkdir(parents=True)
        sentinel = {'status': 'ready_for_review', 'sentinel': 'last good'}
        (previous / 'run.json').write_text(json.dumps(sentinel))
        sources = self.root / 'sources'
        sources.mkdir()
        # First valid archive then missing horizontals fails after a real staged validation.
        archive(sources / 'OGD_Wells.zip')
        args = refresh.parser().parse_args(['--execute', '--acquire-only', '--source-dir', str(sources),
                                            '--runs-dir', str(work / 'runs'), '--previous', str(previous)])
        with mock.patch.object(refresh, 'WORKSPACE', self.root), self.assertRaises(FileNotFoundError):
            refresh.execute(args)
        self.assertEqual(json.loads((previous / 'run.json').read_text()), sentinel)
        failed = [p for p in (work / 'runs').iterdir() if p != previous]
        self.assertEqual(len(failed), 1)
        report = json.loads((failed[0] / 'run.json').read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertFalse(report['publicWebsiteUpdated'])

    def test_acquire_only_and_no_change_are_not_implicitly_published(self):
        work = self.root / 'work'
        sources = self.root / 'sources'
        sources.mkdir()
        for url in refresh.SOURCES.values():
            filename = url.rsplit('/', 1)[-1]
            archive(sources / filename, stem=Path(filename).stem)
        args = refresh.parser().parse_args(['--execute', '--acquire-only', '--source-dir', str(sources),
                                            '--runs-dir', str(work / 'runs')])
        with mock.patch.object(refresh, 'WORKSPACE', self.root):
            run, report = refresh.execute(args)
        self.assertEqual(report['status'], 'acquired_not_processed')
        self.assertFalse(report['sqlImported'])
        self.assertFalse(report['schedulingEnabled'])
        self.assertEqual(set(report['sources']), set(refresh.SOURCES))
        self.assertFalse((run / 'dataset').exists())

    def test_live_output_directory_rejected(self):
        args = refresh.parser().parse_args(['--execute', '--runs-dir', str(refresh.WORKSPACE / 'dist')])
        with self.assertRaisesRegex(ValueError, 'dedicated child'):
            refresh.execute(args)

    def output_fixture(self):
        run = self.root / 'candidate'
        dataset, dsus = run / 'dataset', run / 'dsu'
        dataset.mkdir(parents=True)
        dsus.mkdir()
        manifest = {'wells': [{'id': 0}], 'stations': 2,
                    'labels': ['Vertical', 'Directional', 'Curve', 'Drillback', 'Lateral', 'Unknown'],
                    'tiles': [{'file': 'a.bin', 'stations': 2}]}
        (dataset / 'manifest.json').write_text(json.dumps(manifest))
        (dataset / 'a.bin').write_bytes(struct.pack('<8f', 0, -100, 0, 0, 100, -100, 0, 4))
        manifest_hash = refresh.sha(dataset / 'manifest.json')
        values = {
            'dataset/metrics.json': {'source': {'datasetManifestSHA256': manifest_hash}},
            'dataset/metrics-validation.json': {'passed': True, 'geometryUnchanged': True},
            'dataset/section-metric-scales-validation.json': {'passed': True},
            'dataset/well-names.json': {'survey': {'manifestSHA256': manifest_hash}, 'coverage': {'missingBranches': 1}},
            'dataset/operators.json': {'survey': {'branchCount': 1}, 'joinStats': {'unknownBranches': 1}},
            'dsu/drilling-spacing-units.geojson': {'features': [{'id': 'dsu-example'}]},
        }
        for name, value in values.items():
            (run / name).write_text(json.dumps(value))
        membership = {'sourceHashes': {'manifestSha256': manifest_hash,
                       'dsuFileSha256': refresh.sha(dsus / 'drilling-spacing-units.geojson')},
                      'units': {'dsu-example': []}}
        (dsus / 'dsu-well-membership.json').write_text(json.dumps(membership))
        return run

    def test_output_qa_retains_unknown_coverage_and_classification_distribution(self):
        report = refresh.validate_outputs(self.output_fixture())
        self.assertEqual(report['missingWellNames'], 1)
        self.assertEqual(report['unknownOperators'], 1)
        self.assertEqual(report['sectionStationCounts']['Vertical'], 1)
        self.assertEqual(report['sectionStationCounts']['Lateral'], 1)

    def test_stale_membership_cannot_be_ready_for_review(self):
        run = self.output_fixture()
        path = run / 'dsu/dsu-well-membership.json'
        membership = json.loads(path.read_text())
        membership['sourceHashes']['manifestSha256'] = 'stale'
        path.write_text(json.dumps(membership))
        with self.assertRaisesRegex(ValueError, 'stale survey'):
            refresh.validate_outputs(run)


if __name__ == '__main__':
    unittest.main()
