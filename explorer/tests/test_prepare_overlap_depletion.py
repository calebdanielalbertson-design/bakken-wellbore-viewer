"""Overlapping-unit depletion: part selection, imbalance and the before/after well split."""
import csv
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

try:
    import shapely
    from shapely.geometry import box
except ImportError:
    raise unittest.SkipTest('Overlap tests require optional Shapely.')

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
spec = importlib.util.spec_from_file_location('overlap_builder', ROOT.parent / 'prepare_overlap_depletion.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


def rect(x0, y0, x1, y1):
    return {'type': 'Polygon', 'coordinates': [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


class UnitTests(unittest.TestCase):
    def test_imbalance_bounds(self):
        self.assertEqual(builder.imbalance([0.5, 0.5], [0.5, 0.5]), 0)
        self.assertEqual(builder.imbalance([1.0, 0.0], [0.5, 0.5]), 0.5)
        self.assertAlmostEqual(builder.imbalance([1.0, 0, 0, 0], [.25, .25, .25, .25]), 0.75)

    def test_parts_do_not_double_cover(self):
        area = lambda g: float(shapely.area(g))
        overlap = box(0, 0, 2, 2)
        cands = [('w', box(0, 0, 1, 2)), ('e', box(1, 0, 2, 2)), ('sw', box(0, 0, 1, 1)), ('outside', box(1.5, 0, 3, 2))]
        self.assertEqual(sorted(p for p, _ in builder.choose_parts(overlap, cands, area)), ['e', 'w'])


class BuildTests(unittest.TestCase):
    def test_one_sided_overlap(self):
        with tempfile.TemporaryDirectory() as folder:
            f = pathlib.Path(folder)
            (f / 'dsus.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'features': [
                {'type': 'Feature', 'geometry': rect(0, 0, 2, 2), 'properties': {'id': 'big', 'acres': 2560}},
                {'type': 'Feature', 'geometry': rect(0, 0, 1, 2), 'properties': {'id': 'west', 'acres': 1280}},
                {'type': 'Feature', 'geometry': rect(1, 0, 2, 2), 'properties': {'id': 'east', 'acres': 1280}}]}))
            hist = [{'order': '30000', 'date': '2018-06-01', 'event': 'spacing', 'wells': 1}]
            (f / 'orders.json').write_text(json.dumps({'units': {'big': {'footprints': [{'pool': 'Test-Bakken', 'land': None, 'history': hist}]}}}))
            m = lambda p, frac: {'permit': p, 'fraction': frac}
            (f / 'members.json').write_text(json.dumps({'units': {
                'west': [m('1', 1.0), m('3', 0.5), m('4', 1.0)], 'east': [m('3', 0.5)], 'big': [m('1', 1.0), m('3', 1.0), m('4', 1.0)]}}))
            with open(f / 'WellIndex.csv', 'w', newline='') as h:
                w = csv.DictWriter(h, ['FileNo', 'SpudDate', 'CountyName', 'Township', 'Range', 'Section']); w.writeheader()
                w.writerow({'FileNo': '1', 'SpudDate': '01/01/2012'}); w.writerow({'FileNo': '3', 'SpudDate': '01/01/2019'})
                w.writerow({'FileNo': '4', 'SpudDate': '01/01/2011'})  # a Madison horizontal inside the Bakken unit
            with open(f / 'prod.csv', 'w', newline='') as h:
                w = csv.DictWriter(h, ['File No', 'Pool Name', 'RPT_DATE', 'BBLS_OIL_COND', 'MCF_GAS']); w.writeheader()
                w.writerow({'File No': '1', 'Pool Name': 'BAKKEN', 'RPT_DATE': '2013-01-01', 'BBLS_OIL_COND': '200000', 'MCF_GAS': '60000'})
                w.writerow({'File No': '1', 'Pool Name': 'BAKKEN', 'RPT_DATE': '2019-01-01', 'BBLS_OIL_COND': '5000', 'MCF_GAS': '0'})
                w.writerow({'File No': '1', 'Pool Name': 'MADISON', 'RPT_DATE': '2013-01-01', 'BBLS_OIL_COND': '999', 'MCF_GAS': '0'})
                w.writerow({'File No': '1', 'Pool Name': 'BAKKEN/THREE FORKS', 'RPT_DATE': '2013-02-01', 'BBLS_OIL_COND': '10000', 'MCF_GAS': '0'})
                w.writerow({'File No': '4', 'Pool Name': 'MADISON', 'RPT_DATE': '2012-01-01', 'BBLS_OIL_COND': '50000', 'MCF_GAS': '0'})
                w.writerow({'File No': '4', 'Pool Name': 'BAKKEN', 'RPT_DATE': '2012-02-01', 'BBLS_OIL_COND': '100', 'MCF_GAS': '0'})
                w.writerow({'File No': '3', 'Pool Name': 'BAKKEN', 'RPT_DATE': '2019-02-01', 'BBLS_OIL_COND': '100000', 'MCF_GAS': '0'})
            r = builder.build(f / 'dsus.geojson', f / 'orders.json', f / 'members.json', f / 'WellIndex.csv', str(f / 'prod.csv'), f / 'out.json')
        o = r['overlaps'][0]
        self.assertEqual((o['id'], o['parts'], o['dryParts'], o['oneSided']), ('big', 2, 1, True))
        # Bakken and commingled BAKKEN/THREE FORKS rows count; Madison rows and the mostly-Madison well 4 do not.
        self.assertEqual(o['priorOil'], 210000, 'only Bakken-pool months before the overlap date count')
        self.assertEqual(o['priorBoe'], 220000)
        self.assertEqual(o['sides'][0]['wellsBefore'], 1)
        self.assertEqual(r['summary']['nonBakkenWells'], 1)
        self.assertAlmostEqual(o['imbalance'], 0.5, places=3)
        self.assertEqual((o['lineWells'], o['lineBoe']), (1, 100000))
        self.assertEqual(o['dryShareOfLineBoe'], 50000)
        self.assertEqual(o['coverage'], 1.0)


if __name__ == '__main__':
    unittest.main()
