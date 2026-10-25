"""Offline checks for depth-source priority, distance limits and missing-data rules."""
import collections
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("zone", Path(__file__).resolve().parents[1] / "prepare_dsu_zone.py")
zone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(zone)


class ZoneTests(unittest.TestCase):
    def estimate(self, tops=(), bottoms=(), pairs=(), laterals=()):
        indexes = [zone.PointIndex(list(points), 100) for points in (tops, bottoms, pairs, laterals)]
        return zone.estimate(0, 0, indexes, 5, 100, "2026-10-17", collections.Counter())

    def point(self, depth, x=0):
        return {"x": x, "z": 0, "depth": depth, "file": "1"}

    def test_prefers_same_well_paired_tops(self):
        pair = {"x": 0, "z": 0, "top": 9000, "bottom": 10000, "file": "1"}
        result = self.estimate([self.point(8500)], pairs=[pair])
        self.assertEqual((result["topFt"], result["bottomFt"], result["method"]), (9000, 10000, "local_paired_tops"))

    def test_separate_local_base_requires_plausible_order(self):
        result = self.estimate([self.point(9000)], [self.point(10100)])
        self.assertEqual((result["bottomFt"], result["method"]), (10100, "local_separate_tops"))
        invalid = self.estimate([self.point(9000)], [self.point(8900)])
        self.assertEqual((invalid["bottomFt"], invalid["method"]), (9800, "lodgepole_plus_800ft"))

    def test_remote_top_is_not_used_as_local_control(self):
        result = self.estimate([self.point(9000, x=101)], laterals=[self.point(11000, x=200)])
        self.assertEqual((result["topFt"], result["bottomFt"], result["method"]), (10200, 11200, "lateral_minus800_plus200"))
        self.assertEqual(result["sourceDate"], "2026-10-17")

    def test_empty_controls_use_explicit_regional_fallback(self):
        result = self.estimate()
        self.assertEqual((result["topFt"], result["bottomFt"], result["method"]), (9000, 10000, "regional_9000_10000"))
        self.assertEqual(result["nSamples"], 0)
        self.assertIsNone(result["sourceDate"])
        self.assertIsNone(result["nearestKm"])

    def test_neighbours_are_distance_ordered_and_radius_limited(self):
        points = [self.point(10000, x=x) for x in (101, 5, 100, -40, 2)]
        found = zone.PointIndex(points, 100).nearest(0, 0, 3, radius=100)
        self.assertEqual([entry[0] for entry in found], [2, 5, 40])

    def test_projection_has_exact_shared_origin(self):
        manifest = {"origin": [-102.99897097700921, 47.91137672734358], "sourceCRS": "NAD83"}
        x, z = zone.project_reference(*manifest["origin"], manifest)
        self.assertAlmostEqual(x, 0, places=9)
        self.assertAlmostEqual(z, 0, places=9)
        east = zone.project_reference(manifest["origin"][0] + .01, manifest["origin"][1], manifest)
        north = zone.project_reference(manifest["origin"][0], manifest["origin"][1] + .01, manifest)
        self.assertGreater(east[0], 0)
        self.assertLess(north[1], 0)


if __name__ == "__main__":
    unittest.main()
