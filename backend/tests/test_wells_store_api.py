"""Integration contracts: release rollback, provenance, missingness, read boundaries."""
from pathlib import Path
import csv,gzip,hashlib,io,json,os,sqlite3,sys,tempfile,unittest
from unittest.mock import patch
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import backend
import wells_store as store
import wells_backend as api


def fixture(root,rid='release_fixture_001',*,bad_fk=False):
    root.mkdir()
    payload=lambda v: json.dumps(v,separators=(',',':'))
    tables={
        'wells':[['1','33001000010000','A_B 100% Well','Operator','A','a_b 100% well operator 1 33001000010000',payload({'source_date':'2026-10-17'})],
                 ['2','33001000020000','Other',None,None,'other 2 33001000020000','{}']],
        'branches':[['stable_branch','1','33001000010000',payload({'branch':'LAT1','station_count':20,'max_md_ft':20000,'max_tvd_ft':10000})]],
        'dsus':[['dsu_1','Bakken','1280','1271.5',payload({'geometry':{'type':'Polygon','coordinates':[]},'label':'1280 example'})]],
        'memberships':[['dsu_1','999' if bad_fk else '1','33001000010000','10000','0.95','{}']],
        'production':[['1','2024-01-01','0','reported',payload({'source_ids':[0]})],['1','2024-03-01','1201','reported','{}'],['1','2024-04-01',None,'invalid','{}']],
        'issues':[['issue_1','source_identity_not_matched','999',payload({'unknown_is_not_zero':True})]],
    }
    files={}
    for key,rows in tables.items():
        path=root/(key+'.csv.gz')
        with path.open('wb') as raw, gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as compressed:
            with io.TextIOWrapper(compressed,encoding='utf-8',newline='') as stream:
                csv.writer(stream).writerows([[r'\N' if v is None else v for v in row] for row in rows])
        files[key]={'sha256':store.sha_file(path),'rows':len(rows)}
    meta={'release_id':rid,'files':files,'source_date':'2026-10-17','production':{'identities':{'1':'33001000010000'},'months':['2024-01','2024-02','2024-03','2024-04']},'limitations':['Test source only']}
    (root/'release.json').write_text(json.dumps(meta))
    return root


class WellReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.source=fixture(self.root/'first');self.db=self.root/'wells.sqlite3'
        store.import_sqlite(self.source,self.db)
        self.env=patch.dict(os.environ,{'DATABASE_URL':'','BAKKEN_WELLS_DB_PATH':str(self.db)})
        self.env.start()

    def tearDown(self): self.env.stop();self.temp.cleanup()

    def test_meta_and_name_api_file_search(self):
        code,meta=backend.handle_api('/api/wells/meta')
        self.assertEqual(code,200);self.assertEqual(meta['counts']['wells'],2)
        self.assertEqual(meta['backend']['storage'],'sqlite')
        self.assertNotIn('identities',meta['production'])
        for text in ['100%','A_B','33001000010000']:
            code,result=backend.handle_api('/api/wells',{'q':text})
            self.assertEqual(code,200);self.assertEqual([r['file_number'] for r in result['rows']],['1'])
        self.assertEqual(backend.handle_api('/api/wells',{'q':"' OR 1=1 --"})[1]['total'],0)

    def test_detail_branch_does_not_duplicate_production(self):
        status,result=api.handle_api('/api/wells/1')
        self.assertEqual(status,200)
        self.assertEqual(len(result['branches']),1)
        self.assertIn('well=1',result['viewer_url'])
        self.assertEqual(result['production_coverage']['reported_months'],2)
        self.assertEqual(api.handle_api('/api/wells/2')[1]['viewer_url'],None)

    def test_production_zero_missing_invalid_separate(self):
        status,result=api.handle_api('/api/wells/1/production')
        self.assertEqual(status,200)
        self.assertEqual([r['oil_bbl'] for r in result['months']],[0,None,1201,None])
        self.assertEqual([r['quality'] for r in result['months']],['reported','missing','reported','invalid'])
        self.assertEqual(api.handle_api('/api/wells/2/production')[1]['coverage']['observed_months'],0)

    def test_dsu_relation_keeps_legal_caveat(self):
        status,result=api.handle_api('/api/wells/1/dsus')
        self.assertEqual(status,200);self.assertEqual(result['rows'][0]['overlap_ft'],10000)
        self.assertIn('not a legal',result['provenance']['note'])

    def test_failed_import_retains_active_release(self):
        second=fixture(self.root/'second','release_fixture_002',bad_fk=True)
        with self.assertRaises(sqlite3.IntegrityError): store.import_sqlite(second,self.db)
        self.assertEqual(api.handle_api('/api/wells/meta')[1]['release']['id'],'release_fixture_001')
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM well_releases').fetchone()[0],1)

    def test_previous_releases_and_idempotency(self):
        store.import_sqlite(self.source,self.db)
        second=fixture(self.root/'second','release_fixture_002')
        store.import_sqlite(second,self.db)
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM well_releases').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM well_production').fetchone()[0],3)

    def test_reused_production_requires_same_complete_api_binding(self):
        second=fixture(self.root/'second','release_fixture_002')
        path=second/'wells.csv.gz'
        with gzip.open(path,'rt') as stream: changed=stream.read().replace('33001000010000','33001099990000')
        with gzip.open(path,'wt') as stream: stream.write(changed)
        meta=json.loads((second/'release.json').read_text())
        meta['files']['wells']['sha256']=store.sha_file(path)
        (second/'release.json').write_text(json.dumps(meta))
        with self.assertRaises(ValueError): store.import_sqlite(second,self.db)
        self.assertEqual(api.handle_api('/api/wells/meta')[1]['release']['id'],'release_fixture_001')

    def test_file_change_during_import_is_not_activated(self):
        second=fixture(self.root/'second','release_fixture_002')
        original=store.read_rows
        def mutate_after_read(root,key):
            yield from original(root,key)
            if key=='issues': (root/'issues.csv.gz').write_bytes(b'changed during import')
        with patch.object(store,'read_rows',mutate_after_read), self.assertRaises(ValueError):
            store.import_sqlite(second,self.db)
        self.assertEqual(api.handle_api('/api/wells/meta')[1]['release']['id'],'release_fixture_001')

    def test_hash_failure_before_database_mutation(self):
        second=fixture(self.root/'second','release_fixture_002')
        (second/'wells.csv.gz').write_bytes(b'changed')
        with self.assertRaises(ValueError): store.import_sqlite(second,self.db)
        self.assertEqual(api.handle_api('/api/wells/meta')[1]['release']['id'],'release_fixture_001')

    def test_row_count_failure_rolls_back(self):
        second=fixture(self.root/'second','release_fixture_002')
        meta=json.loads((second/'release.json').read_text());meta['files']['production']['rows']=4
        (second/'release.json').write_text(json.dumps(meta))
        with self.assertRaises(ValueError): store.import_sqlite(second,self.db)
        self.assertEqual(api.handle_api('/api/wells/meta')[1]['release']['id'],'release_fixture_001')

    def test_bad_queries_and_missing_wells(self):
        for query in [{'limit':'51'},{'limit':'-1'},{'q':['a','b']},{'unexpected':'x'}]:
            self.assertEqual(api.handle_api('/api/wells',query)[0],400)
        self.assertEqual(api.handle_api('/api/wells/999')[0],404)
        self.assertEqual(api.handle_api('/api/wells/01')[0],404)
        self.assertEqual(api.handle_api('/api/wells/1',{'q':'x'})[0],400)

    def test_unavailable_database_does_not_create_zero_release(self):
        missing=self.root/'missing.sqlite'
        with patch.dict(os.environ,{'BAKKEN_WELLS_DB_PATH':str(missing)}):
            self.assertEqual(api.handle_api('/api/wells/meta')[0],503)
        self.assertFalse(missing.exists())

    def test_mutations_rejected_at_wsgi(self):
        from wsgiref.util import setup_testing_defaults
        environ={};setup_testing_defaults(environ)
        environ.update(REQUEST_METHOD='POST',PATH_INFO='/api/wells')
        result={}
        body=backend.application(environ,lambda status,headers:result.update(status=status))
        self.assertTrue(result['status'].startswith('405'))

    def test_unrelated_sqlite_file_preserved(self):
        other=self.root/'other.sqlite'
        with closing(sqlite3.connect(other)) as c:c.execute('CREATE TABLE important(value TEXT)');c.execute("INSERT INTO important VALUES('retained')");c.commit()
        with self.assertRaises(ValueError):store.import_sqlite(self.source,other)
        with closing(sqlite3.connect(other)) as c:self.assertEqual(c.execute('SELECT value FROM important').fetchone()[0],'retained')


if __name__=='__main__': unittest.main()
