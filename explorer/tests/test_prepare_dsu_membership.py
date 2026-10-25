"""Synthetic topology tests and independent checks against current survey files."""
import collections
import importlib.util
import json
import math
import pathlib
import random
import unittest

try:
    import numpy as np
    import shapely
    from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, shape
except ImportError:
    raise unittest.SkipTest('Membership preprocessing tests require optional NumPy and Shapely.')

ROOT=pathlib.Path(__file__).resolve().parent
WORKSPACE=ROOT.parent.parent
spec=importlib.util.spec_from_file_location('membership_builder',ROOT.parent/'prepare_dsu_membership.py')
builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class TopologyTests(unittest.TestCase):
    def test_polygon_hole_removes_interior_line(self):
        polygon=Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(4,4),(6,4),(6,6),(4,6)]])
        line=LineString([(-5,5),(15,5)])
        self.assertAlmostEqual(builder.exact_positive_length(line,polygon),8)

    def test_multipart_gap_does_not_create_membership(self):
        polygon=MultiPolygon([Polygon([(0,0),(2,0),(2,2),(0,2)]),Polygon([(8,0),(10,0),(10,2),(8,2)])])
        self.assertEqual(builder.exact_positive_length(LineString([(0,1),(10,1)]),polygon),4)
        self.assertEqual(builder.exact_positive_length(LineString([(4,1),(6,1)]),polygon),0)

    def test_cross_boundary_clips_instead_of_assigning_whole_length(self):
        polygon=Polygon([(0,0),(10,0),(10,10),(0,10)])
        line=LineString([(-10,5),(20,5)])
        self.assertEqual(builder.exact_positive_length(line,polygon),10)
        self.assertAlmostEqual(builder.exact_positive_length(line,polygon)/line.length,1/3)

    def test_point_touches_never_create_membership(self):
        polygon=Polygon([(0,0),(10,0),(10,10),(0,10)])
        self.assertEqual(builder.exact_positive_length(LineString([(-5,-5),(0,0)]),polygon),0)
        # The closed source polygon includes a coincident boundary segment.
        self.assertEqual(builder.exact_positive_length(LineString([(0,0),(10,0)]),polygon),10)

    def test_shared_branch_linework_counts_once(self):
        lines=[LineString([(0,0),(10,0)]),LineString([(0,0),(5,0),(10,0)]),LineString([(5,0),(15,0)])]
        union=builder.merged_well_geometry(lines)
        self.assertEqual(union.length,15)
        polygon=Polygon([(-1,-1),(7,-1),(7,1),(-1,1)])
        clips=[shapely.intersection(line,polygon) for line in lines]
        self.assertEqual(builder.merged_well_geometry(clips).length,7)

    def test_retraced_linework_within_one_branch_counts_once(self):
        retraced=LineString([(0,0),(10,0),(5,0),(15,0)])
        self.assertEqual(retraced.length,25)
        self.assertEqual(builder.merged_well_geometry([retraced]).length,15)

    def test_large_md_gap_is_not_connected(self):
        stations=np.asarray([[0,0,0,4],[100,0,0,4],[1000,0,0,4],[1100,0,0,4]],dtype=float)
        counters=collections.Counter()
        line=builder.lateral_geometry(stations,np.asarray([0,100,2000,2100]),counters)
        self.assertEqual(line.length,200)
        self.assertEqual(len(line.geoms),2)
        self.assertEqual(counters['excludedMDGapsOver1000Ft'],1)
        polygon=Polygon([(200,-1),(900,-1),(900,1),(200,1)])
        self.assertEqual(builder.exact_positive_length(line,polygon),0)

    def test_missing_and_nonincreasing_md_are_excluded(self):
        stations=np.asarray([[0,0,0,4],[10,0,0,4],[20,0,0,4],[30,0,0,4]],dtype=float)
        self.assertIsNone(builder.lateral_geometry(stations,np.asarray([0,np.nan,20,20])))

    def test_nonlateral_sections_are_not_bridged(self):
        stations=np.asarray([[0,0,0,2],[10,0,0,4],[20,0,0,2],[30,0,0,4]],dtype=float)
        line=builder.lateral_geometry(stations,np.asarray([0,10,20,30]))
        self.assertEqual(line.length,20)
        self.assertEqual(len(line.geoms),2)

    def test_nonfinite_xyz_and_zero_plan_length_are_excluded(self):
        stations=np.asarray([[0,0,0,4],[0,-10,0,4],[10,-20,0,4],[20,np.nan,0,4]],dtype=float)
        counters=collections.Counter()
        line=builder.lateral_geometry(stations,np.asarray([0,10,20,30]),counters)
        self.assertEqual(line.length,10)
        self.assertEqual(counters['excludedZeroHorizontalLength'],1)
        self.assertEqual(counters['excludedNonfiniteCoordinates'],1)

    def test_identity_is_permit_and_api10_not_completion_suffix(self):
        a=builder.well_identity({'permit':'00123','api':'33-011-00391-00-00'})
        b=builder.well_identity({'permit':'123','api':'33011003919999'})
        self.assertEqual(a,b)
        self.assertEqual(a,('123|3301100391','123','3301100391'))



if __name__=='__main__': unittest.main()
