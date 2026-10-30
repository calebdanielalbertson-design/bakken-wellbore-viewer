"""Synthetic checks for linking order-atlas footprints to source DSUs."""
import importlib.util
import json
import pathlib
import tempfile
import unittest

try:
    import shapely  # noqa: F401
except ImportError:
    raise unittest.SkipTest('Order link tests require optional Shapely.')

ROOT=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('orders_builder',ROOT.parent/'prepare_dsu_orders.py')
builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


def rect(x0,y0,x1,y1):
    return {'type':'Polygon','coordinates':[[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}


def record(key,geometry,date,order,wells,event='spacing',clause='CURRENT_OPERATIVE:1:0',rid=None):
    return {'id':rid or f'{key}-{order}-{clause}','document_id':int(order),'order':str(order),'case':str(int(order)-2000),'date':date,
            'clause':clause,'pool':'Test-Bakken','zone':'Zone I','land':{'township':150,'range':100,'sections':[1,12]},
            'plssid':'X','well_count':wells,'qualifier':'stated' if wells else None,'acres':1280,'unit_key':key,
            'geometry':geometry,'allowance_event':event,'stated_well_count':wells,
            'allowance_source':{'method':'same_order_pool_zone','date':date} if wells else None,'spacing_order_references':[]}


def dsu(unit_id,geometry,inventory=None):
    return {'type':'Feature','geometry':geometry,'properties':{'id':unit_id,'acres':1280,'inventory':inventory}}


class OrderLinkTests(unittest.TestCase):
    def run_build(self,records,features):
        with tempfile.TemporaryDirectory() as folder:
            folder=pathlib.Path(folder)
            (folder/'atlas.json').write_text(json.dumps({'summary':{'built':'2026-10-29'},'records':records}))
            (folder/'dsus.geojson').write_text(json.dumps({'type':'FeatureCollection','metadata':{'sourceCRS':'EPSG:4269'},'features':features}))
            result=builder.build(folder/'atlas.json',folder/'dsus.geojson',folder/'out.json')
            self.assertTrue((folder/'out.audit.json').exists())
            return result

    def test_match_bands_link_close_review_and_unmatched(self):
        base=rect(0,0,1,2)
        result=self.run_build([
            record('exact',base,'2020-01-01',30000,8),
            record('close',rect(0,0,1,1.8),'2020-01-01',30001,6),   # IoU 0.90
            record('review',rect(0,0,1,1.3),'2020-01-01',30002,4),  # IoU 0.65
            record('far',rect(5,5,6,6),'2020-01-01',30003,2),
        ],[dsu('a',base)])
        links=result['units']['a']['footprints']
        self.assertEqual([l['footprint'] for l in links],['exact','close'])
        self.assertEqual([l['match'] for l in links],['exact','close'])
        self.assertEqual([r['footprint'] for r in result['review']],['review'])
        self.assertEqual(result['summary']['footprintMatch'],{'exact':1,'close':1,'review':1,'unmatched':1})

    def test_footprint_links_every_duplicate_dsu(self):
        base=rect(0,0,1,2)
        result=self.run_build([record('fp',base,'2020-01-01',30000,8)],[dsu('a',base),dsu('b',base)])
        self.assertEqual(sorted(result['units']),['a','b'])

    def test_latest_event_uses_date_then_order_and_keeps_history(self):
        base=rect(0,0,1,2)
        result=self.run_build([
            record('fp',base,'2011-05-01',15000,2),
            record('fp',base,'2011-05-01',15000,2,clause='CURRENT_OPERATIVE:2:1'),
            record('fp',base,'2014-03-01',23000,8),
            record('fp',base,'2014-03-01',22999,4),
        ],[dsu('a',base)])
        link=result['units']['a']['footprints'][0]
        self.assertEqual(link['latest']['order'],'23000')
        self.assertEqual(link['latest']['wells'],8)
        self.assertEqual([h['order'] for h in link['history']],['15000','22999','23000'])
        self.assertEqual(link['history'][0]['clauses'],['CURRENT_OPERATIVE:1:0','CURRENT_OPERATIVE:2:1'])
        self.assertEqual(result['units']['a']['allowance']['wells'],8)

    def test_unresolved_latest_event_is_not_backfilled(self):
        base=rect(0,0,1,2)
        result=self.run_build([
            record('fp',base,'2011-05-01',15000,4),
            record('fp',base,'2019-05-01',29000,None,event='conflict'),
        ],[dsu('a',base)])
        allowance=result['units']['a']['allowance']
        self.assertIsNone(allowance['wells'])
        self.assertEqual(allowance['order'],'29000')
        self.assertEqual(result['summary']['dsusWithAllowance'],0)

    def test_mixed_pools_on_same_dsu_are_flagged(self):
        base=rect(0,0,1,2)
        a=record('pool-a',base,'2012-01-01',16000,4)
        b=record('pool-b',base,'2015-01-01',25000,7); b['pool']='Other-Bakken'
        result=self.run_build([a,b],[dsu('a',base)])
        allowance=result['units']['a']['allowance']
        self.assertEqual((allowance['wells'],allowance['order'],allowance['mixed']),(7,'25000',True))

    def test_saved_model_comparison(self):
        base=rect(0,0,1,2)
        inv=lambda capacity:{'matched':True,'estimatedCapacity':capacity}
        result=self.run_build([record('fp',base,'2020-01-01',30000,8)],
                              [dsu('high',base,inv(2.7)),dsu('same',base,inv(8.2)),dsu('none',base)])
        self.assertEqual(result['summary']['allowanceVsSavedModel'],{'order_above_model':1,'order_matches_model':1,'no_saved_model':1})

    def test_conflicting_geometry_for_one_footprint_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_build([record('fp',rect(0,0,1,2),'2020-01-01',30000,8),record('fp',rect(0,0,1,1),'2021-01-01',31000,8)],
                           [dsu('a',rect(0,0,1,2))])


if __name__=='__main__': unittest.main()
