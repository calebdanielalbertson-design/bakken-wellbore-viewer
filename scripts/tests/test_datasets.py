"""Offline tests for scripts/datasets.py using a fake in-memory bucket."""
import io
import shutil
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import datasets as ds  # noqa: E402


class NotFound(Exception):
    response = {'Error': {'Code': '404'}}


class FakeBucket:
    def __init__(self):
        self.objects = {}

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise NotFound()
        return {'Metadata': self.objects[Key][1]}

    def upload_file(self, filename, bucket, key, ExtraArgs):
        self.objects[key] = (Path(filename).read_bytes(), dict(ExtraArgs['Metadata']))

    def download_file(self, bucket, key, filename):
        Path(filename).write_bytes(self.objects[key][0])


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp, ignore_errors=True)
        self.repo = self.temp / 'repo'
        self.archives = self.temp / 'archives'
        data_dir = self.repo / 'explorer' / 'gamma-data'
        (data_dir / 'nested').mkdir(parents=True)
        (data_dir / 'catalog.json').write_text('{"wells": 2}')
        (data_dir / 'nested' / 'cache.bin').write_bytes(b'\x00\x01' * 500)
        (data_dir / 'gamma_service.py').write_text('# tracked in Git')
        self.data = {'version': 1, 'datasets': {'gamma': {'path': 'explorer/gamma-data', 'exclude': ['*.py']}}}
        self.bucket = FakeBucket()

    def pack(self, version='2026-10-17'):
        return ds.pack('gamma', version, data=self.data, repo=self.repo, archives=self.archives)

    def test_pack_records_checksum_and_skips_code(self):
        entry = self.pack()
        self.assertEqual(entry['files'], 2)
        self.assertEqual(entry['key'], 'datasets/gamma/2026-10-17/gamma.tar.gz')
        self.assertEqual(entry['sha256'], ds.sha256_file(ds.archive_path('gamma', '2026-10-17', self.archives)))
        with tarfile.open(ds.archive_path('gamma', '2026-10-17', self.archives)) as tar:
            self.assertEqual(sorted(tar.getnames()), ['catalog.json', 'nested/cache.bin'])

    def test_pack_refuses_to_reuse_a_version(self):
        self.pack()
        with self.assertRaises(ds.DataError):
            self.pack()

    def test_push_then_fetch_round_trip_keeps_tracked_code(self):
        self.pack()
        self.assertEqual(ds.push('gamma', data=self.data, client=self.bucket, bucket='b', archives=self.archives), 'uploaded')
        self.assertEqual(ds.push('gamma', data=self.data, client=self.bucket, bucket='b', archives=self.archives),
                         'already uploaded')
        folder = self.repo / 'explorer' / 'gamma-data'
        shutil.rmtree(folder / 'nested')
        (folder / 'catalog.json').unlink()  # like a fresh clone: only the tracked .py remains
        count = ds.fetch('gamma', data=self.data, client=self.bucket, bucket='b', repo=self.repo)
        self.assertEqual(count, 2)
        self.assertEqual((folder / 'catalog.json').read_text(), '{"wells": 2}')
        self.assertEqual((folder / 'gamma_service.py').read_text(), '# tracked in Git')

    def test_fetch_refuses_to_overwrite_local_data_without_force(self):
        self.pack()
        ds.push('gamma', data=self.data, client=self.bucket, bucket='b', archives=self.archives)
        with self.assertRaises(ds.DataError):
            ds.fetch('gamma', data=self.data, client=self.bucket, bucket='b', repo=self.repo)
        self.assertEqual(ds.fetch('gamma', data=self.data, client=self.bucket, bucket='b', repo=self.repo, force=True), 2)

    def test_checksum_mismatch_changes_nothing(self):
        self.pack()
        ds.push('gamma', data=self.data, client=self.bucket, bucket='b', archives=self.archives)
        key = self.data['datasets']['gamma']['key']
        self.bucket.objects[key] = (b'tampered', self.bucket.objects[key][1])
        before = (self.repo / 'explorer' / 'gamma-data' / 'catalog.json').read_text()
        with self.assertRaises(ds.DataError):
            ds.fetch('gamma', data=self.data, client=self.bucket, bucket='b', repo=self.repo, force=True)
        self.assertEqual((self.repo / 'explorer' / 'gamma-data' / 'catalog.json').read_text(), before)

    def test_push_never_overwrites_a_different_upload(self):
        self.pack()
        key = self.data['datasets']['gamma']['key']
        self.bucket.objects[key] = (b'other', {'sha256': 'different'})
        with self.assertRaises(ds.DataError):
            ds.push('gamma', data=self.data, client=self.bucket, bucket='b', archives=self.archives)

    def test_unsafe_archive_entries_are_refused(self):
        evil = self.temp / 'evil.tar.gz'
        with tarfile.open(evil, 'w:gz') as tar:
            info = tarfile.TarInfo('../escape.txt')
            info.size = 3
            tar.addfile(info, io.BytesIO(b'bad'))
        with self.assertRaises(ds.DataError):
            ds.extract(evil, self.temp / 'out')
        self.assertFalse((self.temp / 'escape.txt').exists())

    def test_status_reports_missing_and_present(self):
        self.pack()
        rows = dict((name, state) for name, _, state in ds.status(self.data, self.repo))
        self.assertEqual(rows['gamma'], 'present (2 files)')
        shutil.rmtree(self.repo / 'explorer' / 'gamma-data' / 'nested')
        (self.repo / 'explorer' / 'gamma-data' / 'catalog.json').unlink()
        rows = dict((name, state) for name, _, state in ds.status(self.data, self.repo))
        self.assertTrue(rows['gamma'].startswith('missing'))

    def test_dataset_paths_cannot_leave_the_repo(self):
        with self.assertRaises(ds.DataError):
            ds.target_dir({'path': '../outside'}, self.repo)


if __name__ == '__main__':
    unittest.main()
