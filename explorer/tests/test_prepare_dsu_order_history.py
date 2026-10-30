"""Allowance rules and DSU linking for the land-index order history."""
import importlib.util
import json
import pathlib
import sqlite3
import sys
import tempfile
import unittest

try:
    import shapely  # noqa: F401
except ImportError:
    raise unittest.SkipTest('Order history tests require optional Shapely.')

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
spec = importlib.util.spec_from_file_location('history_builder', ROOT.parent / 'prepare_dsu_order_history.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


def ev(order, event='spacing', wells=None, method='unit_clause'):
    return {'order': str(order), 'case': '1', 'date': None, 'event': event, 'wells': wells, 'method': method,
            'document_id': order, 'clause': 'C', 'pool': 'Test-Bakken', 'zone': 'I'}


def rect(x0, y0, x1, y1):
    return {'type': 'Polygon', 'coordinates': [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


class AllowanceTests(unittest.TestCase):
    def test_latest_order_number_with_a_count_wins(self):
        a = builder.resolve_allowance([ev(15000, wells=3), ev(23000, wells=8), ev(30000)])
        self.assertEqual((a['wells'], a['order']), (8, '23000'))

    def test_count_free_zone_never_resets_an_allowance(self):
        a = builder.resolve_allowance([ev(20000, wells=6), ev(35000, 'zone', None, 'zone_table')])
        self.assertEqual(a['wells'], 6)

    def test_zone_table_count_applies(self):
        a = builder.resolve_allowance([ev(20000, wells=2), ev(30000, 'zone', 7, 'zone_table')])
        self.assertEqual((a['wells'], a['method']), (7, 'zone_table'))

    def test_unit_clause_outranks_zone_table_in_same_order(self):
        a = builder.resolve_allowance([ev(30000, 'zone', 4, 'zone_table'), ev(30000, wells=8)])
        self.assertEqual((a['wells'], a['mixed']), (8, False))

    def test_equal_priority_conflict_is_mixed(self):
        a = builder.resolve_allowance([ev(30000, 'zone', 4, 'zone_table'), ev(30000, 'zone', 6, 'zone_table')])
        self.assertEqual((a['wells'], a['mixed']), (None, True))

    def test_later_termination_ends_allowance(self):
        a = builder.resolve_allowance([ev(20000, wells=8), ev(31000, 'termination')])
        self.assertEqual((a['wells'], a['terminated']), (None, True))
        a = builder.resolve_allowance([ev(20000, 'termination'), ev(31000, wells=4)])
        self.assertEqual((a['wells'], a['terminated']), (4, False))


class OrientationTests(unittest.TestCase):
    def test_standup_zone_skips_laydown_dsu_on_same_land(self):
        from shapely.geometry import shape
        self.assertEqual(builder.orientation(shape(rect(0, 0, 1, 2))), 'standup')
        self.assertEqual(builder.orientation(shape(rect(0, 0, 2.8, 1))), 'laydown')
        self.assertTrue(builder.zone_fits(['standup'], 'standup'))
        self.assertFalse(builder.zone_fits(['standup'], 'laydown'))
        self.assertTrue(builder.zone_fits(['overlapping 640s'], 'laydown'))


class BuildTests(unittest.TestCase):
    def test_units_and_zones_link_to_dsus(self):
        with tempfile.TemporaryDirectory() as folder:
            f = pathlib.Path(folder); db = f / 'index.sqlite3'
            con = sqlite3.connect(db)
            con.executescript('''CREATE TABLE documents(document_id INTEGER PRIMARY KEY, order_no TEXT, case_no TEXT, date TEXT, date_basis TEXT, applicant TEXT);
              CREATE TABLE units(document_id INTEGER, order_no TEXT, case_no TEXT, clause TEXT, unit_index INTEGER, kind TEXT, verb TEXT, acres INTEGER,
                wells INTEGER, orientation TEXT, zone TEXT, pools TEXT, tracts TEXT, warnings TEXT, text TEXT);
              CREATE TABLE unit_geometry(document_id INTEGER, clause TEXT, unit_index INTEGER, geojson TEXT, measured_acres REAL, missing_tracts INTEGER,
                best_dsu TEXT, best_iou REAL);
              CREATE TABLE zones(document_id INTEGER, order_no TEXT, pool TEXT, zone TEXT, wells INTEGER, acres INTEGER, kind TEXT, modifiers TEXT,
                tracts TEXT, ordinal INTEGER);
              CREATE TABLE zone_geometry(document_id INTEGER, ordinal INTEGER, geojson TEXT, measured_acres REAL, missing_tracts INTEGER);''')
            con.executemany('insert into documents values(?,?,?,?,?,?)', [(1, '20000', '1', '2012-01-01', 'date_signed', 'Alpha Oil'),
                                                                        (2, '30000', '2', '2020-01-01', 'date_signed', 'Alpha Oil'),
                                                                        (3, '31000', '3', '2021-01-01', 'date_signed', None)])
            tracts = json.dumps([[150, 100, 1, []], [150, 100, 12, []]])
            # Order 20000 establishes the unit with 2 wells; order 31000 designates it into Zone II whose same-order table says 8.
            con.executemany('insert into units values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', [
                (1, '20000', '1', 'C1', 0, 'unit', 'established', 1280, 2, 'standup', 'I', '["Test-Bakken"]', tracts, '[]', ''),
                (3, '31000', '3', 'C9', 0, 'unit', 'designated', 1280, None, 'standup', 'II', '["Test-Bakken"]', tracts, '[]', ''),
                (3, '31000', '3', 'C10', 0, 'unit', 'designated', 640, None, None, 'I', '["Test-Madison"]', tracts, '[]', '')])
            con.executemany('insert into unit_geometry values(?,?,?,?,?,?,?,?)', [
                (1, 'C1', 0, json.dumps(rect(0, 0, 1, 2)), 1280, 0, None, 0), (3, 'C9', 0, json.dumps(rect(0, 0, 1, 2)), 1280, 0, None, 0),
                (3, 'C10', 0, json.dumps(rect(0, 0, 1, 2)), 1280, 0, None, 0)])
            # Order 30000's count-free zone table lists the land; order 31000's table states 8 wells for Zone II.
            con.executemany('insert into zones values(?,?,?,?,?,?,?,?,?,?)', [
                (2, '30000', 'Test-Bakken', 'I', None, 1280, 'H', '[]', tracts, 0), (3, '31000', 'Test-Bakken', 'II', 8, 1280, 'H', '[]', tracts, 0)])
            con.executemany('insert into zone_geometry values(?,?,?,?,?)', [(2, 0, json.dumps(rect(0, 0, 3, 3)), 0, 0), (3, 0, json.dumps(rect(0, 0, 3, 3)), 0, 0)])
            con.commit(); con.close()
            (f / 'dsus.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'metadata': {'sourceCRS': 'EPSG:4269'}, 'features': [
                {'type': 'Feature', 'geometry': rect(0, 0, 1, 2), 'properties': {'id': 'a', 'acres': 1280}},
                {'type': 'Feature', 'geometry': rect(1.5, 0, 2.5, 2), 'properties': {'id': 'b', 'acres': 2560}}]}))
            result = builder.build(db, f / 'dsus.geojson', f / 'out.json')
        unit = result['units']['a']
        self.assertEqual((unit['allowance']['wells'], unit['allowance']['order'], unit['allowance']['method']), (8, '31000', 'zone_table_same_order'))
        events = [(h['order'], h['event'], h['wells']) for h in unit['footprints'][0]['history']]
        self.assertIn(('30000', 'zone', None), events)
        self.assertNotIn('C10', [c for h in unit['footprints'][0]['history'] for c in h['clauses']])
        self.assertNotIn('b', result['units'], 'zone acreage must match the DSU')
        self.assertEqual(unit['footprints'][0]['land'], {'township': 150, 'township_direction': 'N', 'range': 100, 'range_direction': 'W', 'sections': [1, 12]})
        self.assertEqual(result['applicants']['20000'], 'Alpha Oil')


if __name__ == '__main__':
    unittest.main()
