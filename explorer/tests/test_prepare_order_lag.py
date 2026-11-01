"""Order-to-drill lag: Kaplan-Meier, growth series, lead correlation and the event split."""
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
try:
    spec = importlib.util.spec_from_file_location('lag_builder', ROOT.parent / 'prepare_order_lag.py')
    builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
    import numpy as np
except ImportError:
    raise unittest.SkipTest('Lag tests require optional NumPy and Shapely.')


class UnitTests(unittest.TestCase):
    def test_kaplan_meier_keeps_censored_units_at_risk(self):
        # Drilled at 10 and 30 days; one unit undrilled after 20 days; one at 40.
        curve = builder.kaplan_meier([10, 20, 30, 40], [True, False, True, True])
        self.assertEqual([t for t, _ in curve], [10, 30, 40])
        self.assertAlmostEqual(curve[0][1], 0.75)
        self.assertAlmostEqual(curve[1][1], 0.375)  # two at risk after the censored unit leaves
        self.assertEqual(builder.survival_at(curve, 5), 1.0)

    def test_km_summary_median_and_shares(self):
        rows = [{'lagDays': d, 'observed': o} for d, o in [(0, True), (100, True), (400, True), (900, False)]]
        s = builder.km_summary(rows)
        self.assertEqual((s['events'], s['drilled'], s['atOnce']), (4, 3, 0.25))
        self.assertEqual(s['medianMonths'], round(100 / 30.44, 1))
        self.assertEqual(s['within6'], 0.5)

    def test_yoy_and_negative_lead(self):
        x = np.array([1.0] * 12 + [3.0] * 12)
        g = builder.yoy(x, smooth=1)
        self.assertTrue(np.isnan(g[11]))
        self.assertAlmostEqual(g[12], np.log(4) - np.log(2))
        a = np.sin(np.arange(60) / 4.0); b = np.roll(a, 3)  # b is a three months later
        self.assertAlmostEqual(builder.lead_corr(a, b, 3), 1.0, places=6)
        self.assertAlmostEqual(builder.lead_corr(b, a, -3), 1.0, places=6)

    def test_operator_name(self):
        self.assertEqual(builder.operator_name('Whiting Oil And Gas Corp.'), builder.operator_name('WHITING OIL & GAS CORP.'))
        self.assertEqual(builder.operator_name('Petro- Hunt, L.L.C.'), 'Petro-Hunt')
        self.assertEqual(builder.operator_name(None), 'Unknown')


class LagTests(unittest.TestCase):
    def test_spacing_and_density_lags(self):
        hist = [{'order': '14000', 'date': '2010-01-01', 'event': 'spacing', 'wells': 1},
                {'order': '20000', 'date': '2013-01-01', 'event': 'spacing', 'wells': 4},
                {'order': '25000', 'date': '2016-01-01', 'event': 'spacing', 'wells': 8}]
        orders = {'u': {'footprints': [{'pool': 'Test-Bakken', 'acres': 1280, 'history': hist}]},
                  'pre': {'footprints': [{'pool': 'Test-Bakken', 'history': [{'order': '15000', 'date': '2012-01-01', 'event': 'spacing', 'wells': 1}]}]}}
        spud = {'1': '2010-07-01', '2': '2014-01-01', 'old': '2008-01-01'}
        events, stats = builder.build_lag(orders, {'14000': 'EOG RESOURCES, INC.'}, {'u': ['1', '2'], 'pre': ['old']}, spud, {'2': 'HESS CORPORATION'}, '2026-10-01')
        self.assertEqual(stats['spacing_predrilled'], 1)
        spacing = [e for e in events if e['kind'] == 'spacing']
        density = [e for e in events if e['kind'] == 'density']
        self.assertEqual(len(spacing), 1)
        self.assertEqual((spacing[0]['lagDays'], spacing[0]['observed'], spacing[0]['operator']), (181, True, 'EOG Resources'))
        self.assertEqual([(e['date'], e['observed'], e['lagDays']) for e in density],
                         [('2013-01-01', True, 365), ('2016-01-01', False, 3926)])
        self.assertEqual(density[0]['operator'], 'Hess')


if __name__ == '__main__':
    unittest.main()
