"""Density payoff: increases, first-year oil, vintage scores and the parent/child split."""
import csv
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
try:
    spec = importlib.util.spec_from_file_location('density_builder', ROOT.parent / 'prepare_density_payoff.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
except ImportError:
    raise unittest.SkipTest('Density tests require optional NumPy and Shapely.')


class UnitTests(unittest.TestCase):
    def test_increases_ignore_unchanged_and_lower_steps(self):
        t = {'steps': [('2010-01-01', 1), ('2011-01-01', 1), ('2012-01-01', 4), ('2013-01-01', None), ('2014-01-01', 3), ('2015-01-01', 8)]}
        self.assertEqual(builder.increases(t), [('2012-01-01', 1, 4), ('2015-01-01', 3, 8)])

    def test_first_year_oil_uses_twelve_calendar_months_from_first_production(self):
        months = {'2012-03': [0, 0], '2012-04': [100, 0], **{f'2012-{m:02}': [10, 0] for m in range(5, 13)},
                  **{f'2013-{m:02}': [10, 0] for m in range(1, 13)}}
        self.assertEqual(builder.first_year_oil(months), ('2012-04', 100 + 8 * 10 + 3 * 10))
        self.assertIsNone(builder.first_year_oil({'2012-01': [0, 5]}))

    def test_bucket(self):
        self.assertEqual([builder.bucket(n) for n in (2, 6, 12, 14)], ['1-4', '5-8', '9-12', '13+'])


class BuildTests(unittest.TestCase):
    def test_children_scored_against_their_vintage(self):
        with tempfile.TemporaryDirectory() as folder:
            f = pathlib.Path(folder)
            # Unit raised from 1 to 4 wells by an order dated 2013-01-01.
            hist = [{'order': '14000', 'date': '2010-01-01', 'event': 'spacing', 'wells': 1}, {'order': '20000', 'date': '2013-01-01', 'event': 'spacing', 'wells': 4}]
            (f / 'dsus.geojson').write_text(json.dumps({'features': [{'properties': {'id': 'u', 'acres': 1280}}]}))
            (f / 'orders.json').write_text(json.dumps({'units': {'u': {'footprints': [{'pool': 'Test-Bakken', 'history': hist}]}}}))
            # Parent 1 (2011) and child 2 (2014) in unit u; 10 peers per vintage elsewhere set the medians.
            members = {'u': [{'permit': '1', 'insideFt': 10000, 'totalFt': 10000, 'fraction': 1}, {'permit': '2', 'insideFt': 10000, 'totalFt': 10000, 'fraction': 1}]}
            peers = [(str(100 + i), 2011) for i in range(10)] + [(str(200 + i), 2014) for i in range(10)]
            # Each peer is the first well in its own unit, so the peers form the fresh-rock baseline.
            for p, _ in peers:
                members['unit-' + p] = [{'permit': p, 'insideFt': 10000, 'totalFt': 10000, 'fraction': 1}]
            (f / 'members.json').write_text(json.dumps({'units': members}))
            with open(f / 'WellIndex.csv', 'w', newline='') as h:
                w = csv.DictWriter(h, ['FileNo', 'SpudDate', 'CountyName', 'CurrentOperator']); w.writeheader()
                w.writerow({'FileNo': '1', 'SpudDate': '06/01/2011', 'CountyName': 'MCKENZIE', 'CurrentOperator': 'A'})
                w.writerow({'FileNo': '2', 'SpudDate': '06/01/2014', 'CountyName': 'MCKENZIE', 'CurrentOperator': 'B'})
                for p, y in peers:
                    w.writerow({'FileNo': p, 'SpudDate': f'01/01/{y}', 'CountyName': 'MCKENZIE', 'CurrentOperator': 'C'})
            with open(f / 'prod.csv', 'w', newline='') as h:
                w = csv.DictWriter(h, ['File No', 'Pool Name', 'RPT_DATE', 'BBLS_OIL_COND', 'MCF_GAS']); w.writeheader()
                # Peers: 2011 vintage 100,000 bbl, 2014 vintage 200,000 bbl in the first month.
                for p, y in peers:
                    w.writerow({'File No': p, 'Pool Name': 'BAKKEN', 'RPT_DATE': f'{y}-07-01', 'BBLS_OIL_COND': str(100000 if y == 2011 else 200000), 'MCF_GAS': '0'})
                w.writerow({'File No': '1', 'Pool Name': 'BAKKEN', 'RPT_DATE': '2011-07-01', 'BBLS_OIL_COND': '100000', 'MCF_GAS': '0'})
                w.writerow({'File No': '2', 'Pool Name': 'BAKKEN', 'RPT_DATE': '2014-07-01', 'BBLS_OIL_COND': '150000', 'MCF_GAS': '0'})
            r = builder.build(f / 'dsus.geojson', f / 'orders.json', f / 'members.json', f / 'WellIndex.csv', str(f / 'prod.csv'), f / 'out.json', last_month='2026-08')
        e = r['events'][0]
        self.assertEqual((e['from'], e['to'], e['parents'], e['children']), (1, 4, 1, 1))
        # The child made more oil than the parent, but 25% less than its own vintage: ratio 0.75.
        self.assertEqual((e['parentScore'], e['childScore'], e['ratio']), (1.0, 0.75, 0.75))
        self.assertEqual(r['summary']['shareChildrenBetter'], 0.0)


if __name__ == '__main__':
    unittest.main()
