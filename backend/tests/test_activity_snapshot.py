"""Activity dates and volume semantics must survive repeated mapped branches."""
from contextlib import closing
import csv
import gzip
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_activity_snapshot as activity
import fracfocus_store as ff_store
import wells_store
from test_fracfocus import row
from test_wells_store_api import fixture


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.wells = self.root / 'wells.sqlite'
        self.frac = self.root / 'fracfocus.sqlite'
        self.manifest = self.root / 'manifest.json'
        self.source = self.root / 'DisclosureList_1.csv'
        self.dictionary = self.root / 'readme csv.txt'
        self.dictionary.write_text('Fixture dictionary.', encoding='utf-8')
        self.env = patch.dict(os.environ, {'DATABASE_URL': '', 'BAKKEN_WELLS_DB_PATH': str(self.wells), 'BAKKEN_FRACFOCUS_DB_PATH': str(self.frac)})
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def build(self, events, *, spud='2023-01-01', second_spud=None, geometry_api='33001000010000'):
        self.manifest.write_text(json.dumps({'wells': [
            {'permit': '1', 'api': geometry_api, 'branch': 'LAT1'},
            {'permit': '1', 'api': geometry_api, 'branch': 'LAT2'},
            {'permit': '2', 'api': '33001000020000', 'branch': 'LAT1'}]}), encoding='utf-8')
        bundle = fixture(self.root / 'bundle')
        rows = []
        with gzip.open(bundle / 'wells.csv.gz', 'rt', encoding='utf-8', newline='') as stream:
            for item in csv.reader(stream):
                payload = json.loads(item[-1]); payload['spud_date'] = spud if item[0] == '1' else second_spud
                item[-1] = json.dumps(payload); rows.append(item)
        with gzip.open(bundle / 'wells.csv.gz', 'wt', encoding='utf-8', newline='') as stream:
            csv.writer(stream).writerows(rows)
        meta = json.loads((bundle / 'release.json').read_text())
        meta['files']['wells']['sha256'] = ff_store.sha_file(bundle / 'wells.csv.gz')
        meta['survey'] = {'manifest_sha256': ff_store.sha_file(self.manifest)}
        (bundle / 'release.json').write_text(json.dumps(meta), encoding='utf-8')
        wells_store.import_sqlite(bundle, self.wells)
        with self.source.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=ff_store.FIELDS)
            writer.writeheader(); writer.writerows(events)
        ff_store.prepare(self.source, self.frac, self.dictionary)
        return activity.build(self.manifest)

    def test_repeated_branches_do_not_duplicate_wells_or_events(self):
        result = self.build([row(1)])
        self.assertEqual(len(result['wells']), 2)
        self.assertEqual(result['wells'][0]['branch_count'], 2)
        self.assertEqual(result['coverage']['disclosure_events'], 1)
        self.assertEqual(result['wells'][0]['monthly'][0]['water_gallons'], 1000)
        self.assertEqual(result['provenance']['survey_manifest_sha256'], ff_store.sha_file(self.manifest))

    def test_water_assigned_once_to_job_end_month(self):
        result = self.build([row(1, start='12/20/2023', end='2/5/2024', water='3000')])
        well = result['wells'][0]
        self.assertEqual(well['events'][0]['month'], '2024-02')
        self.assertEqual(well['monthly'], [{'month': '2024-02', 'event_count': 1, 'water_gallons': 3000, 'water_status': 'reported'}])
        self.assertEqual(result['months']['frac'], {'first': '2024-02', 'last': '2024-02'})

    def test_possible_duplicates_keep_counts_but_no_monthly_volume(self):
        result = self.build([row(1, water='3000'), row(2, water='3000')])
        well = result['wells'][0]
        self.assertEqual(len(well['events']), 2)
        self.assertTrue(all(event['review_required'] for event in well['events']))
        self.assertEqual(well['monthly'][0]['event_count'], 2)
        self.assertIsNone(well['monthly'][0]['water_gallons'])
        self.assertEqual(well['monthly'][0]['water_status'], 'review_required')

    def test_missing_zero_invalid_are_not_conflated(self):
        result = self.build([row(1, water='0'), row(2, start='2/1/2024', end='2/2/2024', water=''), row(3, start='3/1/2024', end='3/2/2024', water='NaN')])
        monthly = result['wells'][0]['monthly']
        self.assertEqual([entry['water_gallons'] for entry in monthly], [0, None, None])
        self.assertEqual([entry['water_status'] for entry in monthly], ['reported', 'missing', 'invalid'])
        self.assertIsNone(result['wells'][1]['spud_date'])
        self.assertEqual(result['wells'][1]['spud_status'], 'missing')

    def test_missing_spud_not_inferred_from_disclosure(self):
        result = self.build([row(1)], spud=None)
        self.assertIsNone(result['wells'][0]['spud_date'])
        self.assertEqual(result['wells'][0]['spud_status'], 'missing')
        self.assertEqual(result['wells'][0]['events'][0]['month'], '2024-01')

    def test_spud_after_frac_withheld_and_raw_date_kept(self):
        result = self.build([row(1)], spud='2025-01-01')
        well = result['wells'][0]
        self.assertIsNone(well['spud_date'])
        self.assertEqual(well['source_spud_date'], '2025-01-01')
        self.assertEqual(well['spud_status'], 'review_required')
        self.assertIsNone(well['events'][0]['month'])
        self.assertEqual(well['events'][0]['end'], '2024-01-02')
        self.assertEqual(well['monthly'], [])

    def test_future_spud_not_added_beyond_source_snapshot(self):
        result = self.build([row(1, api_number='33001000020000')], spud='2099-01-01')
        self.assertIsNone(result['wells'][0]['spud_date'])
        self.assertEqual(result['months']['spud'], {'first': None, 'last': None})

    def test_file_and_api_must_both_match(self):
        result = self.build([row(1)], geometry_api='33001000010001')
        self.assertEqual([well['permit'] for well in result['wells']], ['2'])
        self.assertEqual(result['coverage']['unmatched_geometry_identities'], 1)
        self.assertEqual(result['coverage']['disclosure_events'], 0)

    def test_changed_manifest_or_snapshot_binding_refused(self):
        self.build([row(1)])
        with closing(sqlite3.connect(self.frac)) as db:
            db.execute("UPDATE ff_bindings SET api='33001000010001' WHERE file_number='1'"); db.commit()
        with self.assertRaises(ValueError): activity.build(self.manifest)
        self.manifest.write_text(self.manifest.read_text() + '\n')
        with self.assertRaises(ValueError): activity.build(self.manifest)

    def test_unknown_end_month_not_assigned_from_start(self):
        result = self.build([row(1, start='1/1/2024', end='')])
        event = result['wells'][0]['events'][0]
        self.assertIsNone(event['month'])
        self.assertTrue(event['review_required'])
        self.assertEqual(result['wells'][0]['monthly'], [])

    def test_future_job_end_does_not_extend_playback(self):
        result = self.build([row(1, start='1/1/2099', end='1/2/2099')])
        event = result['wells'][0]['events'][0]
        self.assertIsNone(event['month'])
        self.assertIn('future_job_end', event['review_reasons'])
        self.assertEqual(result['months']['frac'], {'first': None, 'last': None})

    def test_mixed_known_and_missing_water_month_stays_unknown(self):
        result = self.build([row(1, start='1/1/2024', end='1/2/2024', water='1000'), row(2, start='1/3/2024', end='1/4/2024', water='')])
        monthly = result['wells'][0]['monthly'][0]
        self.assertIsNone(monthly['water_gallons'])
        self.assertEqual(monthly['event_count'], 2)
        self.assertEqual(monthly['water_status'], 'missing')

    def test_preparation_is_atomic_and_sources_unchanged(self):
        self.build([row(1)])
        before = [ff_store.sha_file(path) for path in (self.wells, self.frac, self.manifest)]
        output = self.root / 'activity.json'
        prepared = activity.prepare(self.manifest, output)
        self.assertEqual(prepared['sha256'], ff_store.sha_file(output))
        self.assertEqual(before, [ff_store.sha_file(path) for path in (self.wells, self.frac, self.manifest)])
        self.assertEqual(list(self.root.glob('.activity-*')), [])


if __name__ == '__main__': unittest.main()
