"""Local disclosure integrity: exact joins, no inferred totals and safe failure."""
from contextlib import closing
import csv
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend
import fracfocus_backend as api
import fracfocus_store as store
import wells_store
from test_wells_store_api import fixture


def row(number, *, api_number='33001000010000', water='1000', start='1/1/2024 12:00:00 AM', end='1/2/2024 12:00:00 AM', **changes):
    record = {field: '' for field in store.FIELDS}
    record.update(DisclosureId=str(uuid.UUID(int=number)), APINumber=api_number,
                  StateName='North Dakota', TotalBaseWaterVolume=water,
                  JobStartDate=start, JobEndDate=end, OperatorName='Reported operator',
                  WellName='Reported name')
    record.update(changes)
    return record


class FracFocusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.wells = self.root / 'wells.sqlite'
        wells_store.import_sqlite(fixture(self.root / 'release'), self.wells)
        self.source = self.root / 'DisclosureList_1.csv'
        self.dictionary = self.root / 'readme csv.txt'
        self.dictionary.write_text('Fixture dictionary; TotalBaseWaterVolume is gallons.', encoding='utf-8')
        self.target = self.root / 'fracfocus.sqlite'
        self.env = patch.dict(os.environ, {'DATABASE_URL': '', 'BAKKEN_WELLS_DB_PATH': str(self.wells), 'BAKKEN_FRACFOCUS_DB_PATH': str(self.target)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def build(self, rows):
        with self.source.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=store.FIELDS)
            writer.writeheader(); writer.writerows(rows)
        return store.prepare(self.source, self.target, self.dictionary)

    def detail(self, file_number='1'):
        return api.handle_api('/api/wells/' + file_number + '/fracfocus')

    def test_missing_zero_invalid_and_raw_evidence(self):
        metadata = self.build([row(1, water='0'), row(2, water=''), row(3, water='NaN'), row(4, water='-2'), row(5, water='1200.5')])
        status, body = self.detail()
        self.assertEqual(status, 200)
        values = {event['disclosure_id']: event for event in body['events']}
        self.assertEqual(values[row(1)['DisclosureId']]['water_gallons'], 0)
        self.assertEqual(values[row(1)['DisclosureId']]['water_status'], 'reported')
        self.assertEqual(values[row(2)['DisclosureId']]['water_status'], 'missing')
        self.assertEqual(values[row(3)['DisclosureId']]['water_status'], 'invalid')
        self.assertIsNone(values[row(3)['DisclosureId']]['water_gallons'])
        self.assertEqual(values[row(4)['DisclosureId']]['water_status'], 'invalid')
        self.assertEqual(values[row(5)['DisclosureId']]['water_gallons'], 1200.5)
        self.assertNotIn('water_total', body)
        self.assertEqual(body['provenance']['source_sha256'], store.sha_file(self.source))
        with closing(sqlite3.connect(self.target)) as db:
            evidence = db.execute('SELECT raw_json,raw_sha256 FROM ff_evidence WHERE disclosure_key=?', (row(3)['DisclosureId'],)).fetchone()
        self.assertEqual(json.loads(evidence[0])['TotalBaseWaterVolume'], 'NaN')
        self.assertEqual(len(evidence[1]), 64)
        self.assertEqual(metadata['counts']['accepted_disclosures'], 5)

    def test_conflicting_id_quarantines_every_variant_exact_dup_collapses(self):
        metadata = self.build([row(1), row(1), row(2), row(2, water='2000'), row(3)])
        status, body = self.detail()
        self.assertEqual(status, 200)
        self.assertEqual(body['coverage']['total'], 2)
        self.assertEqual(body['coverage']['quarantined_count'], 2)
        self.assertEqual(body['coverage']['status'], 'review_required')
        self.assertEqual(metadata['counts']['exact_duplicate_rows_collapsed'], 1)
        self.assertEqual(metadata['counts']['conflicting_disclosure_ids'], 1)
        event = next(event for event in body['events'] if event['disclosure_id'] == row(1)['DisclosureId'])
        self.assertEqual(event['source_occurrences'], 2)

    def test_conflict_anywhere_in_complete_source_is_quarantined(self):
        self.build([row(1), row(1, api_number='42317372620000', StateName='Texas')])
        status, body = self.detail()
        self.assertEqual(status, 200)
        self.assertEqual(body['events'], [])
        self.assertEqual(body['coverage']['status'], 'review_required')

    def test_same_api_dates_are_preserved_as_possible_duplicate_events(self):
        self.build([row(1), row(2)])
        _, body = self.detail()
        self.assertEqual(len(body['events']), 2)
        self.assertTrue(all(any('possible duplicate' in note for note in event['quality_notes']) for event in body['events']))

    def test_suffix_and_short_api_never_auto_join(self):
        self.build([row(1, api_number='33001000010001'), row(2, api_number='3300100001')])
        _, body = self.detail()
        self.assertEqual(body['events'], [])
        self.assertEqual(body['coverage']['api10_review_count'], 1)
        self.assertEqual(body['coverage']['status'], 'review_required')
        self.assertEqual(self.detail('2')[1]['coverage']['status'], 'no_disclosure')

    def test_dates_invalid_and_reversed_not_silently_normalized(self):
        self.build([row(1, start='garbage'), row(2, start='2/1/2024', end='1/1/2024')])
        events = self.detail()[1]['events']
        invalid = next(event for event in events if event['disclosure_id'] == row(1)['DisclosureId'])
        self.assertIsNone(invalid['job_start_date'])
        reversed_ = next(event for event in events if event['disclosure_id'] == row(2)['DisclosureId'])
        self.assertIsNone(reversed_['job_start_date']); self.assertIsNone(reversed_['job_end_date'])
        self.assertEqual(reversed_['raw_job_start_date'], '2/1/2024')

    def test_missing_and_unrelated_snapshot_are_unavailable_not_zero(self):
        self.assertEqual(self.detail()[0], 503)
        self.assertFalse(self.target.exists())
        self.target.write_bytes(b'not sqlite')
        self.assertEqual(self.detail()[0], 503)

    def test_release_change_and_identity_change_are_detected(self):
        self.build([row(1)])
        with closing(sqlite3.connect(self.wells)) as db:
            db.execute("UPDATE well_registry SET api='33001099990000' WHERE file_number='1'"); db.commit()
        self.assertEqual(self.detail()[1]['error']['code'], 'fracfocus_identity_mismatch')
        wells_store.import_sqlite(fixture(self.root / 'release2', 'release_fixture_002'), self.wells)
        self.assertEqual(self.detail()[1]['error']['code'], 'fracfocus_release_mismatch')

    def test_incomplete_snapshot_does_not_imply_no_disclosure(self):
        self.build([row(1)])
        with closing(sqlite3.connect(self.target)) as db:
            db.execute('DELETE FROM ff_events'); db.commit()
        self.assertEqual(self.detail()[0], 503)

    def test_source_change_during_import_preserves_previous_snapshot(self):
        self.build([row(1)])
        original = store.sha_file(self.target)
        original_sha = store.sha_file
        reads = 0
        def changed_after_read(path):
            nonlocal reads
            if Path(path) == self.source:
                reads += 1
                if reads > 1: return 'a' * 64
            return original_sha(path)
        with patch.object(store, 'sha_file', side_effect=changed_after_read), self.assertRaises(ValueError):
            store.prepare(self.source, self.target, self.dictionary)
        self.assertEqual(store.sha_file(self.target), original)

    def test_failed_import_keeps_previous_snapshot_and_success_replaces_atomically(self):
        self.build([row(1)])
        original = store.sha_file(self.target)
        self.source.write_text('invalid,csv\n', encoding='utf-8')
        with self.assertRaises(ValueError): store.prepare(self.source, self.target, self.dictionary)
        self.assertEqual(store.sha_file(self.target), original)
        self.build([row(2, water='3000')])
        self.assertEqual(self.detail()[1]['events'][0]['water_gallons'], 3000)
        self.assertEqual(list(self.root.glob('.fracfocus-*')), [])

    def test_read_only_boundaries_queries_and_no_remote_route(self):
        self.build([row(1)])
        with api.connect() as (db, _):
            with self.assertRaises(sqlite3.OperationalError): db.execute('DELETE FROM ff_events')
        self.assertEqual(api.handle_api('/api/wells/1/fracfocus', {'api': '33001000020000'})[0], 400)
        self.assertEqual(self.detail('999')[0], 404)
        self.assertEqual(self.detail('01')[0], 404)
        self.assertEqual(backend.handle_api('/api/wells/1/fracfocus')[0], 404)
        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://unused.invalid/db'}), patch.object(api.wells_backend, 'connect', side_effect=AssertionError('Remote connection must not be attempted')):
            self.assertEqual(self.detail()[1]['error']['code'], 'fracfocus_local_only')

    def test_bound_200_disclosures(self):
        self.build([row(number) for number in range(1, 203)])
        status, body = self.detail()
        self.assertEqual(status, 200)
        self.assertEqual(body['coverage']['total'], 202)
        self.assertEqual(body['coverage']['returned'], 200)
        self.assertTrue(body['coverage']['truncated'])


if __name__ == '__main__': unittest.main()
