"""Portable synthetic GIS checks; no private datasets or fixed snapshot required."""
import contextlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest

sys.dont_write_bytecode=True
try:
    import geopandas as gpd
    import numpy as np
    import pyogrio
    import shapely
    from pyproj import Transformer
    from shapely.geometry import LineString, MultiPolygon, Polygon, mapping
except ImportError:
    raise unittest.SkipTest('Footage preprocessing tests require requirements-footage.txt.')

REPO=pathlib.Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('public_prepare_footage',REPO/'prepare_footage.py')
preparer=importlib.util.module_from_spec(spec);spec.loader.exec_module(preparer)
helpers=preparer.load_membership_helpers(REPO/'prepare_dsu_membership.py')
ORIGIN=[-103.0,48.0]


class ProjectionAndGeometryTests(unittest.TestCase):
    def test_inverse_roundtrip_across_north_dakota(self):
        rng=np.random.default_rng(72)
        geographic=np.column_stack((rng.uniform(-104.5,-96.5,300),rng.uniform(45.8,49.2,300)))
        forward=helpers.source_projection(ORIGIN)
        tangent=forward(geographic)
        restored=preparer.tangent_inverse(ORIGIN)(tangent)
        self.assertLess(float(np.abs(restored-geographic).max()),1e-11)
        self.assertLess(float(np.abs(forward(restored)-tangent).max()),1e-6)

    def test_equal_area_projection_matches_direct_nad83(self):
        geographic=np.asarray([[-104.0,48.9],[-102.0,47.0]])
        tangent=helpers.source_projection(ORIGIN)(geographic)
        tx=Transformer.from_crs(4269,5070,always_xy=True)
        x,y=tx.transform(geographic[:,0],geographic[:,1])
        np.testing.assert_allclose(preparer.viewer_projector(ORIGIN)(tangent),np.column_stack((x,y)),rtol=0,atol=1e-6)

    def test_hole_multipart_point_touch_and_exact_shared_paths(self):
        polygons=[Polygon([(0,0),(10,0),(10,10),(0,10)],holes=[[(4,4),(6,4),(6,6),(4,6)]]),
                  MultiPolygon([Polygon([(0,20),(2,20),(2,22),(0,22)]),Polygon([(8,20),(10,20),(10,22),(8,22)])]),
                  Polygon([(0,30),(10,30),(10,40),(0,40)])]
        branches=np.asarray([LineString([(-5,5),(15,5)]),LineString([(0,21),(10,21)]),LineString([(-1,29),(0,30)])],object)
        feet,counts,_,_=preparer.group_observations(polygons,branches,branches)
        np.testing.assert_allclose(feet,np.asarray([8,4,0])/.3048)
        self.assertEqual(counts.tolist(),[1,1,0])
        shared=helpers.merged_well_geometry([LineString([(0,0),(10,0),(5,0),(15,0)]),LineString([(5,0),(10,0)])])
        self.assertEqual(shared.length,15)

    def test_md_gap_excludes_unobserved_connecting_segment(self):
        stations=np.asarray([[0,0,0,4],[100,0,0,4],[1000,0,0,4],[1100,0,0,4]],float)
        line=helpers.lateral_geometry(stations,np.asarray([0,100,2000,2100]))
        self.assertEqual(line.length,200)
        gap=Polygon([(200,-1),(900,-1),(900,1),(200,1)])
        self.assertEqual(preparer.total_clipped_ft(np.asarray([line],object),gap),0)

    def test_township_identity_keeps_both_directions(self):
        west=preparer.township_identity({'TOWNSHIP':152,'TDIR':'N','RANGE':96,'RDIR':'W'})
        east=preparer.township_identity({'TOWNSHIP':152,'TDIR':'N','RANGE':96,'RDIR':'E'})
        self.assertEqual(west[0],'township-152N-096W')
        self.assertNotEqual(west[0],east[0])


class PortableBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='wellbore-footage-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)
        self.dataset=self.root/'dataset';self.dataset.mkdir()
        self.output=self.root/'derived'
        inverse=preparer.tangent_inverse(ORIGIN)
        def geographic_rectangle(x0,z0,x1,z1):
            return Polygon(inverse(np.asarray([(x0,z0),(x1,z0),(x1,z1),(x0,z1),(x0,z0)],float)))
        boundary=geographic_rectangle(-50,-100,1050,100)
        features=[{'type':'Feature','id':key,'properties':{'id':key,'label':key,'formation':formation},'geometry':mapping(boundary)}
                  for key,formation in [('base','Bakken'),('overlay','Bakken'),('unknown','unrecognized')]]
        self.dsu_data={'type':'FeatureCollection','metadata':{'sourceCRS':'EPSG:4269'},'features':features}
        self.dsufile=self.root/'dsus.geojson';self.dsufile.write_text(json.dumps(self.dsu_data),encoding='utf-8')
        # Two fragments with one full TR key must dissolve. A second township is
        # outside the supplied DSU mask and is retained with explicit zero metrics.
        frame=gpd.GeoDataFrame({'TOWNSHIP':[152,152,152],'TDIR':['N']*3,'RANGE':[96,96,97],'RDIR':['W']*3},
            geometry=[geographic_rectangle(-100,-200,500,200),geographic_rectangle(500,-200,1100,200),geographic_rectangle(2000,-200,3000,200)],crs=4269)
        self.township=self.root/'Townships.shp'
        frame.to_file(self.township,driver='ESRI Shapefile',engine='pyogrio')
        positions=np.asarray([[0,-1000,0,4],[500,-1000,0,4],[1000,-1000,0,4],
                              [1000,-1000,0,4],[500,-1000,0,4],[0,-1000,0,4],
                              [0,-1000,0,4],[10,-1000,0,4]],dtype='<f4')
        measurements=np.zeros((8,8),dtype='<f4');measurements[:,0]=[0,500,1000,0,500,1000,0,2000]
        positions.tofile(self.dataset/'tile.bin');measurements.tofile(self.dataset/'tile.metrics.bin')
        branches=[{'id':0,'permit':'1','api':'33000000010000','tile':'tile','offset':0,'count':3},
                  {'id':1,'permit':'1','api':'33000000010000','tile':'tile','offset':3,'count':3},
                  {'id':2,'permit':'2','api':'33000000020000','tile':'tile','offset':6,'count':2}]
        self.manifest={'version':1,'sourceCRS':'NAD83','origin':ORIGIN,'stations':8,'wells':branches,
                       'tiles':[{'id':'tile','file':'tile.bin','stations':8}],'sourceSnapshot':{'date':'2025-01-01'}}
        self.metrics={'stride':8,'stations':8,'branchCount':3,'fields':[{'index':0,'name':'mdFt','unit':'ft'}],
                      'tiles':[{'id':'tile','file':'tile.metrics.bin','count':8}],
                      'source':{'origin':ORIGIN,'sourceCRS':'NAD83'}}
        self.write_manifest_and_metrics()

    def write_manifest_and_metrics(self):
        path=self.dataset/'manifest.json'
        path.write_text(json.dumps(self.manifest),encoding='utf-8')
        self.metrics['source']['datasetManifestSHA256']=preparer.sha_file(path)
        (self.dataset/'metrics.json').write_text(json.dumps(self.metrics),encoding='utf-8')

    def build(self,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return preparer.build(self.dsufile,self.dataset,self.township,self.output,**kwargs)

    def test_tiny_end_to_end_build_retains_schema_and_preserves_inputs(self):
        inputs={path:preparer.sha_file(path) for path in self.root.rglob('*') if path.is_file()}
        expected=preparer.sha_file(self.dataset/'manifest.json')
        result,towns=self.build(expected_manifest_sha256=expected)
        self.assertEqual(result['version'],1)
        self.assertEqual(result['survey']['manifest_sha256'],expected)
        self.assertEqual(result['coverage']['usable_wells'],1)
        self.assertEqual(result['coverage']['unusable_wells'],1)
        base=result['dsus']['base'];overlay=result['dsus']['overlay'];unknown=result['dsus']['unknown']
        self.assertEqual(base['observed_wells'],1);self.assertEqual(base['observed_lateral_branches'],2)
        self.assertAlmostEqual(base['mapped_lateral_ft'],overlay['mapped_lateral_ft'])
        self.assertGreater(base['mapped_lateral_ft'],900);self.assertLess(base['mapped_lateral_ft'],1100)
        self.assertFalse(unknown['eligible'])
        self.assertTrue(all(unknown[k] is None for k in ('eligible_acres','mapped_lateral_ft','observed_wells','observed_lateral_branches')))
        supported=result['townships']['township-152N-096W'];outside=result['townships']['township-152N-097W']
        self.assertAlmostEqual(supported['eligible_acres'],base['eligible_acres'],places=6)
        self.assertAlmostEqual(supported['mapped_lateral_ft'],base['mapped_lateral_ft'],places=4)
        self.assertFalse(outside['eligible']);self.assertEqual(outside['eligibility_status'],'outside_dataset_mask')
        self.assertTrue(all(outside[k]==0 for k in ('eligible_acres','mapped_lateral_ft','observed_wells','observed_lateral_branches')))
        self.assertEqual(len(towns['features']),2)
        self.assertEqual(towns['metadata']['sourceCRS'],'EPSG:4269')
        self.assertEqual(result['source_hashes']['townships_geojson_sha256'],preparer.sha_file(self.output/'townships.geojson'))
        self.assertEqual(inputs,{path:preparer.sha_file(path) for path in inputs})

    def test_expected_snapshot_and_md_alignment_guards(self):
        with self.assertRaisesRegex(ValueError,'expected SHA256'):self.build(expected_manifest_sha256='0'*64)
        self.assertFalse(self.output.exists())
        self.metrics['source']['datasetManifestSHA256']='0'*64
        (self.dataset/'metrics.json').write_text(json.dumps(self.metrics),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'metric index'):self.build()
        self.assertFalse(self.output.exists())

    def test_output_cannot_overwrite_source_geojson(self):
        collision=self.root/'footage.json';collision.write_bytes(self.dsufile.read_bytes())
        original=preparer.sha_file(collision)
        with self.assertRaisesRegex(ValueError,'overwrite a source'):
            preparer.build(collision,self.dataset,self.township,self.root)
        self.assertEqual(preparer.sha_file(collision),original)

    def test_manifest_cannot_read_outside_dataset(self):
        self.manifest['tiles'][0]['file']='../outside.bin';self.write_manifest_and_metrics()
        with self.assertRaisesRegex(ValueError,'escapes'):self.build()

    def test_optional_membership_requires_both_snapshot_and_geometry(self):
        sidecar=self.root/'membership.json'
        source={'dsuGeometryAndIdsSha256':preparer.canonical_sha([[f['id'],f['geometry']] for f in self.dsu_data['features']]),
                'manifestSha256':preparer.sha_file(self.dataset/'manifest.json')}
        sidecar.write_text(json.dumps({'sourceHashes':source}),encoding='utf-8')
        result,_=self.build(membership_path=sidecar)
        self.assertEqual(result['source_hashes']['existing_membership_sha256'],preparer.sha_file(sidecar))
        source['manifestSha256']='0'*64;sidecar.write_text(json.dumps({'sourceHashes':source}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'Membership sidecar'):self.build(membership_path=sidecar)


if __name__=='__main__':unittest.main()
