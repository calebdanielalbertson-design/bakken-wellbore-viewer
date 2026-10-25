"""Geometry and preservation checks for the display-only DSU import helper."""
import contextlib
import copy
import importlib.util
import io
import json
import math
from pathlib import Path
import tempfile
import unittest

try:
    from pyproj import Transformer
    from shapely.geometry import MultiPolygon, Point, Polygon, box, mapping, shape
    from shapely.ops import transform
except ImportError:
    raise unittest.SkipTest('Display preprocessing tests require optional Shapely and pyproj.')

spec = importlib.util.spec_from_file_location("display", Path(__file__).resolve().parents[1] / "prepare_dsu_display.py")
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)


class DisplayTests(unittest.TestCase):
    def test_fixed_lanes_interpolation_and_large_units(self):
        for size, inset in display.INSET_ANCHORS:
            self.assertEqual(display.inset_feet(size), inset)
        self.assertEqual(display.inset_feet(3200), 400)
        self.assertEqual(display.inset_feet(10240), 700)
        for value in (None, -100, float("nan"), float("inf")):
            self.assertEqual(display.inset_feet(value), 0)

    def test_bands_are_hollow_inside_source_and_source_is_unchanged(self):
        source = box(0, 0, 1609, 3218)
        before = source.wkb
        outer, band, fallback = display.display_geometry(source, 1280)
        self.assertFalse(fallback)
        self.assertTrue(source.covers(outer))
        self.assertTrue(source.covers(band))
        self.assertTrue(outer.is_valid and band.is_valid)
        self.assertFalse(band.covers(Point(800, 1600)))
        self.assertAlmostEqual(outer.bounds[0], 100 * .3048)
        self.assertEqual(source.wkb, before)
        expected_inner = source.buffer(-150 * .3048, join_style=2)
        self.assertAlmostEqual(band.area, outer.area - expected_inner.area)

    def test_shared_perimeters_have_separate_filter_stable_lanes(self):
        source = box(0, 0, 4000, 4000)
        bounds = []
        for size in (1280, 1920, 2560, 3840):
            outer, band, fallback = display.display_geometry(source, size)
            self.assertFalse(fallback)
            bounds.append(outer.bounds[0])
        self.assertEqual(bounds, sorted(bounds))
        alone = display.display_geometry(source, 2560)[0]
        self.assertEqual(alone.bounds[0], bounds[2])
        for left, right in zip(bounds, bounds[1:]):
            self.assertGreater(right - left, 50 * .3048)

    def test_holes_and_multipart_units_remain_hollow(self):
        donut = Polygon(box(0, 0, 3000, 3000).exterior, [box(1000, 1000, 2000, 2000).exterior])
        other = box(5000, 0, 8000, 3000)
        source = MultiPolygon([donut, other])
        outer, band, fallback = display.display_geometry(source, 1280)
        self.assertFalse(fallback)
        self.assertEqual(len(outer.geoms), 2)
        self.assertFalse(outer.covers(Point(1500, 1500)))
        self.assertFalse(band.covers(Point(1500, 1500)))
        self.assertFalse(band.covers(Point(6500, 1500)))

    def test_any_erased_component_falls_back_for_entire_feature(self):
        wide = box(0, 0, 2000, 2000)
        narrow = box(5000, 0, 5080, 2000)
        # 100 ft erosion survives, but the additional 50 ft erases this part.
        self.assertFalse(narrow.buffer(-100 * .3048, join_style=2).is_empty)
        self.assertTrue(narrow.buffer(-150 * .3048, join_style=2).is_empty)
        source = MultiPolygon([wide, narrow])
        outer, band, fallback = display.display_geometry(source, 1280)
        self.assertTrue(fallback)
        self.assertTrue(outer.equals_exact(source, 0))
        self.assertIsNone(band)

    def test_invalid_geometries_and_band_width_are_rejected(self):
        source = box(0, 0, 2000, 2000)
        for width in (0, -1, math.inf, math.nan):
            with self.assertRaises(ValueError):
                display.display_geometry(source, 1280, width)
        crossed = Polygon([(0, 0), (1000, 1000), (0, 1000), (1000, 0), (0, 0)])
        with self.assertRaises(ValueError):
            display.display_geometry(crossed, 1280)

    def test_geojson_adds_only_display_and_keeps_source_and_zone(self):
        to_geo = Transformer.from_crs(5070, 4269, always_xy=True).transform
        source = transform(to_geo, box(-500000, 2700000, -498000, 2703000))
        feature = {"type": "Feature", "id": "unchanged-id", "properties": {
            "id": "unchanged-id", "acres": 1280, "source": {"dssize": 1280, "orderno": 1},
            "zone": {"topFt": 9000, "bottomFt": 10000}, "inventory": {"remaining": None}},
            "geometry": mapping(source)}
        data = {"type": "FeatureCollection", "metadata": {"sourceCRS": "EPSG:4269", "sourceNote": "retained"}, "features": [feature]}
        with tempfile.TemporaryDirectory() as folder:
            input_path, output_path = Path(folder) / "in.geojson", Path(folder) / "out.geojson"
            input_path.write_text(json.dumps(data), encoding="utf-8")
            input_bytes = input_path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                output, audit = display.prepare(input_path, output_path)
            original = json.loads(input_path.read_text(encoding="utf-8"))
            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(display.without_display(result["features"][0]), original["features"][0])
            self.assertEqual(input_path.read_bytes(), input_bytes)
            self.assertTrue(audit["allOriginalFeatureContentPreserved"])
            self.assertTrue(audit["allStableIdsPreserved"])
            self.assertEqual(result["metadata"]["sourceNote"], "retained")
            self.assertTrue(shape(result["features"][0]["properties"]["display"]["bandGeometry"]).is_valid)
            with self.assertRaises(ValueError):
                display.prepare(input_path, input_path)


if __name__ == "__main__":
    unittest.main()
