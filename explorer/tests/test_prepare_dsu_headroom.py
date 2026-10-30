"""Synthetic checks for remaining permitted wells per DSU and statewide rollups."""
import csv
import hashlib
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest

try:
    import shapely  # noqa: F401
except ImportError:
    raise unittest.SkipTest('Headroom tests require optional Shapely.')

ROOT=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('headroom_builder',ROOT.parent/'prepare_dsu_headroom.py')
builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)

FIELDS=['FileNo','CurrentOperator','CountyName','Township','Range','Section','ProducedPools','Wellbore','WellStatus','Latitude','Longitude']


def rect(x0,y0,x1,y1):
    return {'type':'Polygon','coordinates':[[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}


def member(permit,inside,fraction,branches):
    return {'key':f'{permit}|33000{permit:0>5}','permit':str(permit),'api10':f'33000{permit:0>5}','branchIds':branches,
            'intersectingBranchIds':branches,'insideFt':inside,'totalFt':inside/fraction,'fraction':fraction}


def link(wells,order='30000',mixed=False,township=150,sections=(1,12)):
    return {'allowance':{'wells':wells,'order':order,'case':'1','date':'2020-01-01','qualifier':'stated','mixed':mixed,'footprints':1},
            'footprints':[{'footprint':'fp-'+order,'pool':'Test-Bakken','zone':'Zone I','acres':1280,'iou':1,'match':'exact',
                           'land':{'township':township,'range':100,'sections':list(sections)},'latest':{},'history':[]}]}


class HeadroomTests(unittest.TestCase):
    def run_build(self,dsus,orders,members,index_rows,branches=8,groups=None,applicants=None,membership_ids_hash=None,manifest_branches=None):
        ids=[d[0] for d in dsus]; ids_hash=hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            f=pathlib.Path(folder); (f/'dataset').mkdir()
            (f/'dsus.geojson').write_text(json.dumps({'type':'FeatureCollection','metadata':{'sourceCRS':'EPSG:4269'},'features':[
                {'type':'Feature','geometry':g,'properties':{'id':i,'acres':a}} for i,g,a in dsus]}))
            (f/'orders.json').write_text(json.dumps({'version':1,'dsu':{'idsSha256':ids_hash},'units':orders}))
            (f/'membership.json').write_text(json.dumps({'version':1,'survey':{'branchCount':branches,'sourceDate':'2026-10-17'},
                                                       'dsu':{'idsSha256':membership_ids_hash or ids_hash},'units':{i:members.get(i,[]) for i in ids}}))
            (f/'dataset'/'manifest.json').write_text(json.dumps({'wells':[{'id':b,'permit':str(100+b)} for b in range(manifest_branches or branches)]}))
            groups=groups or [{'id':0,'label':'Group A','rawNames':['ALPHA OIL INC.']}]
            (f/'dataset'/'operators.json').write_text(json.dumps({'survey':{'branchCount':branches},'groups':groups,'names':['ALPHA OIL INC.'],
                                                                  'branchGroups':[0]*branches,'branchNames':[0]*branches}))
            out=io.StringIO(); w=csv.DictWriter(out,FIELDS); w.writeheader()
            for r in index_rows: w.writerow({k:r.get(k,'') for k in FIELDS})
            (f/'WellIndex.csv').write_text(out.getvalue())
            (f/'atlas.json').write_text(json.dumps({'records':[{'order':o,'case':'1','applicant':n} for o,n in (applicants or {}).items()],'cases':[]}))
            return builder.build(f/'orders.json',f/'membership.json',f/'dsus.geojson',f/'dataset',f/'WellIndex.csv',f/'atlas.json',f/'out.json')

    def test_balance_counts_bakken_wells_over_660_ft(self):
        result=self.run_build([('a',rect(0,0,1,2),1280)],{'a':link(4)},
            {'a':[member(1,9000,1,[0]),member(2,500,1,[1]),member(3,9000,1,[2])]},
            [{'FileNo':'1','ProducedPools':'BAKKEN'},{'FileNo':'3','ProducedPools':'MADISON'},
             {'FileNo':'9','CountyName':'MCKENZIE','Township':'150 N','Range':'100 W','Section':'1'}])
        u=result['units']['a']
        self.assertEqual((u['wellsInside'],u['balance'],u['assignedBalance']),(1,3,3))
        self.assertEqual(u['county'],'McKenzie')
        self.assertEqual(result['counts']['wellsPool_other'],1)

    def test_shared_well_is_assigned_once_to_smaller_unit_on_tie(self):
        small=rect(0,0,1,2); large=rect(0,0,2,2)
        result=self.run_build([('small',small,1280),('large',large,2560)],{'small':link(4,'1'),'large':link(4,'2')},
            {'small':[member(1,9000,1,[0])],'large':[member(1,9000,1,[0]),member(2,9000,1,[1])]},[])
        self.assertEqual(result['units']['small']['wellsInside'],1)
        self.assertEqual(result['units']['large']['wellsInside'],2)
        self.assertEqual(result['units']['small']['assignedWells'],1)
        self.assertEqual(result['units']['large']['assignedWells'],1)
        self.assertEqual(result['totals']['assignedWells'],2)
        self.assertEqual(result['totals']['remaining'],6)
        self.assertEqual(result['totals']['remainingConservative'],5)

    def test_allowance_unit_takes_precedence_over_overlap_without_one(self):
        result=self.run_build([('governed',rect(0,0,2,2),2560),('plain',rect(0,0,1,2),1280)],{'governed':link(1)},
            {'governed':[member(1,9000,1,[0]),member(2,9000,1,[1])],'plain':[member(1,9000,1,[0]),member(2,9000,1,[1])]},[])
        u=result['units']['governed']
        self.assertEqual((u['assignedWells'],u['assignedBalance'],u['review']),(2,-1,'overlapping_unit_small_allowance'))
        self.assertEqual(result['totals']['wellsAssignedToUnitsWithoutAllowance'],0)

    def test_mixed_or_missing_allowance_is_omitted(self):
        result=self.run_build([('a',rect(0,0,1,2),1280),('b',rect(3,0,4,2),1280)],{'a':link(4,mixed=True),'b':link(None)},{},[])
        self.assertEqual(result['units'],{})
        self.assertEqual(result['counts']['skippedNoSingleAllowance'],2)

    def test_pending_permits_placed_by_surface_location(self):
        rows=[{'FileNo':'500','WellStatus':'LOC','Wellbore':'HORIZONTAL','Latitude':'1','Longitude':'0.5'},
              {'FileNo':'501','WellStatus':'Confidential','Wellbore':'Confidential','Latitude':'1','Longitude':'0.5'},
              {'FileNo':'502','WellStatus':'LOC','Wellbore':'VERTICAL','Latitude':'1','Longitude':'0.5'},
              {'FileNo':'101','WellStatus':'DRL','Wellbore':'HORIZONTAL','Latitude':'1','Longitude':'0.5'},
              {'FileNo':'503','WellStatus':'LOC','Wellbore':'HORIZONTAL','Latitude':'9','Longitude':'9'}]
        result=self.run_build([('a',rect(0,0,1,2),1280)],{'a':link(3)},{},rows)
        self.assertEqual(result['units']['a']['pending'],2)
        self.assertEqual(result['counts']['pendingAlreadySurveyed'],1)
        self.assertEqual(result['counts']['pendingOutsideDSUs'],1)
        self.assertEqual(result['totals']['remainingAfterPending'],1)

    def test_holder_from_wells_else_order_applicant(self):
        result=self.run_build([('drilled',rect(0,0,1,2),1280),('empty',rect(3,0,4,2),1280)],
            {'drilled':link(4,'1'),'empty':link(4,'2')},{'drilled':[member(1,9000,1,[0])]},[],
            applicants={'2':'Alpha Oil, Inc.'})
        self.assertEqual((result['units']['drilled']['holder'],result['units']['drilled']['holderSource']),('Group A','wells'))
        self.assertEqual((result['units']['empty']['holder'],result['units']['empty']['holderSource']),('Group A','order applicant'))
        names=[r['name'] for r in result['rollups']['operator']]
        self.assertEqual(names,['Group A'])
        self.assertEqual(result['rollups']['operator'][0]['remaining'],7)

    def test_dsu_snapshot_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'different DSU snapshots'):
            self.run_build([('a',rect(0,0,1,2),1280)],{'a':link(3)},{},[],membership_ids_hash='stale')

    def test_survey_snapshot_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'different survey snapshots'):
            self.run_build([('a',rect(0,0,1,2),1280)],{'a':link(3)},{},[],manifest_branches=7)


if __name__=='__main__': unittest.main()
