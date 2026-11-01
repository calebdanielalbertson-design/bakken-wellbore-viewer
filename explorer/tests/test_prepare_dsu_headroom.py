"""Synthetic checks for remaining permitted wells per DSU and statewide rollups."""
import csv
import hashlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest

try:
    import shapely  # noqa: F401
except ImportError:
    raise unittest.SkipTest('Headroom tests require optional Shapely.')

ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
spec=importlib.util.spec_from_file_location('headroom_builder',ROOT.parent/'prepare_dsu_headroom.py')
builder=importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)

FIELDS=['FileNo','CurrentOperator','CountyName','Township','Range','Section','ProducedPools','Wellbore','WellStatus','Latitude','Longitude','SpudDate']


def rect(x0,y0,x1,y1):
    return {'type':'Polygon','coordinates':[[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}


def member(permit,inside,fraction,branches):
    return {'key':f'{permit}|33000{permit:0>5}','permit':str(permit),'api10':f'33000{permit:0>5}','branchIds':branches,
            'intersectingBranchIds':branches,'insideFt':inside,'totalFt':inside/fraction,'fraction':fraction}


def link(wells,order='30000',mixed=False,township=150,sections=(1,12),history=None,date='2020-01-01'):
    return {'allowance':{'wells':wells,'order':order,'case':'1','date':date,'qualifier':'stated','mixed':mixed,'footprints':1},
            'footprints':[{'footprint':'fp-'+order,'pool':'Test-Bakken','zone':'Zone I','acres':1280,'iou':1,'match':'exact',
                           'land':{'township':township,'range':100,'sections':list(sections)},'latest':{},'history':history or []}]}


def event(order,date,event='spacing',wells=None,verb='designated'):
    return {'order':str(order),'date':date,'event':event,'wells':wells,'verb':verb}


class HeadroomTests(unittest.TestCase):
    def run_build(self,dsus,orders,members,index_rows,branches=8,groups=None,applicants=None,membership_ids_hash=None,manifest_branches=None,production=None):
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
            glob=None
            if production is not None:
                with open(f/'prod.csv','w',newline='') as h:
                    pw=csv.DictWriter(h,['File No','Pool Name','RPT_DATE','BBLS_OIL_COND','MCF_GAS']); pw.writeheader()
                    for permit,pool,oil in production:
                        pw.writerow({'File No':permit,'Pool Name':pool,'RPT_DATE':'2015-01-01','BBLS_OIL_COND':str(oil),'MCF_GAS':'0'})
                glob=str(f/'prod.csv')
            return builder.build(f/'orders.json',f/'membership.json',f/'dsus.geojson',f/'dataset',f/'WellIndex.csv',f/'atlas.json',f/'out.json',production_glob=glob)

    def test_balance_counts_bakken_wells_over_660_ft(self):
        result=self.run_build([('a',rect(0,0,1,2),1280)],{'a':link(4)},
            {'a':[member(1,9000,1,[0]),member(2,500,1,[1]),member(3,9000,1,[2])]},
            [{'FileNo':'1','ProducedPools':'BAKKEN'},{'FileNo':'3','ProducedPools':'MADISON'},
             {'FileNo':'9','CountyName':'MCKENZIE','Township':'150 N','Range':'100 W','Section':'1'}])
        u=result['units']['a']
        self.assertEqual((u['wellsInside'],u['balance'],u['assignedBalance']),(1,3,3))
        self.assertEqual(u['county'],'McKenzie')
        self.assertEqual(result['counts']['wellsPool_other'],1)

    def test_well_with_mostly_other_pool_production_is_not_counted(self):
        # Well 1 lists Bakken among its pools but produced mostly Madison; well 2 is a Bakken well.
        result=self.run_build([('a',rect(0,0,1,2),1280)],{'a':link(4)},
            {'a':[member(1,9000,1,[0]),member(2,9000,1,[1])]},
            [{'FileNo':'1','ProducedPools':'BAKKEN, MADISON'},{'FileNo':'2','ProducedPools':'BAKKEN'}],
            production=[('1','MADISON',90000),('1','BAKKEN',5000),('2','BAKKEN/THREE FORKS',80000),('2','MADISON',100)])
        u=result['units']['a']
        self.assertEqual((u['wellsInside'],u['balance']),(1,3))
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

    def test_timeline_and_allowance_in_force(self):
        t=builder.unit_timeline(link(8,history=[event(14000,'2010-03-10',wells=1,verb='established'),event(18000,'2012-05-01',wells=4),
                                                event(26000,'2016-01-01',wells=8,verb='established'),event(30000,'2020-01-01','zone')]))
        self.assertEqual(t['start'],'2010-03-10', 're-establishing the same land does not start a new unit')
        self.assertEqual(builder.allowance_at(t['steps'],'2011-06-01'),1)
        self.assertEqual(builder.allowance_at(t['steps'],'2013-06-01'),4)
        self.assertEqual(builder.allowance_at(t['steps'],'2021-06-01'),8)
        self.assertIsNone(builder.allowance_at(t['steps'],'2009-01-01'))
        ended=builder.unit_timeline(link(None,history=[event(14000,'2010-03-10',wells=2,verb='established'),event(15000,'2011-01-01','termination')]))
        self.assertIsNone(builder.allowance_at(ended['steps'],'2012-01-01'))

    def test_geometry_decides_even_against_an_allowance_unit(self):
        small=rect(0,0,1,2); large=rect(0,0,2,2)
        # The well lies wholly in the small unit, which has no allowance; the overlapping large unit has one.
        orders={'large':link(1,'2',history=[event(2,'2015-01-01',wells=1,verb='established')],date='2015-01-01')}
        members={'small':[member(1,9000,1,[0])],'large':[member(1,9000,1,[0])]}
        result=self.run_build([('small',small,1280),('large',large,2560)],orders,members,[])
        self.assertEqual(result['units']['large']['assignedWells'],0)
        self.assertEqual(result['counts']['wellsAssignedDifferentlyThanAllowanceFirst'],1)

    def test_timing_flags_and_review_tags(self):
        orders={'a':link(1,'14000',history=[event(14000,'2010-03-10',wells=1,verb='established')],date='2010-03-10')}
        members={'a':[member(n,9000,1,[n-1]) for n in (1,2,3)]}
        rows=[{'FileNo':str(n),'SpudDate':d} for n,d in ((1,'05/01/2011'),(2,'05/01/2014'),(3,'05/01/2018'))]
        u=self.run_build([('a',rect(0,0,1,2),1280)],orders,members,rows)['units']['a']
        self.assertEqual((u['wellsAfterLatestOrder'],u['drilledBeyondOrderInForce'],u['review']),(3,2,'later_order_likely_missing'))
        orders={'a':link(1,'30000',history=[event(30000,'2020-01-01',wells=1,verb='established')])}
        u=self.run_build([('a',rect(0,0,1,2),1280)],orders,members,rows)['units']['a']
        self.assertEqual((u['wellsBeforeFirstOrder'],u['review']),(3,'wells_predate_linked_orders'))

    def test_answer_key_scores_both_rules(self):
        score=builder.score_attribution([{'permit':'1','dsu':'old'},{'permit':'9','dsu':'x'}],{'1|33000000001':'old'},{'1|33000000001':'new'})
        self.assertEqual(score,{'wells':1,'geometry':1,'allowanceFirst':0})

    def test_dsu_snapshot_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'different DSU snapshots'):
            self.run_build([('a',rect(0,0,1,2),1280)],{'a':link(3)},{},[],membership_ids_hash='stale')

    def test_survey_snapshot_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'different survey snapshots'):
            self.run_build([('a',rect(0,0,1,2),1280)],{'a':link(3)},{},[],manifest_branches=7)


if __name__=='__main__': unittest.main()
