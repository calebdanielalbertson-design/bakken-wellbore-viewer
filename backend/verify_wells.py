"""Safe real-database/API checks, runnable only inside private staging.

Prints counts and verification outcomes; never connection strings or credentials.
"""
from __future__ import annotations
import json
from decimal import Decimal
from pathlib import Path


def verify():
    import psycopg
    from backend import handle_api
    from import_snapshot import _reader_configuration,_reader_permissions
    from wells_backend import connect,json_value
    from wells_store import TABLES
    _,url=_reader_configuration()
    with psycopg.connect(url,connect_timeout=10) as c:
        user,readonly=c.execute("SELECT current_user,current_setting('transaction_read_only')").fetchone()
        if user!='forward_reader' or readonly!='on': raise ValueError('Reader identity/default changed.')
        forward_permissions=_reader_permissions(c)
        for name in ['well_app','well_production_versions','well_production_identities','well_active','well_releases',*[v[0] for v in TABLES.values()]]:
            selected,writes=c.execute("SELECT has_table_privilege(current_user,%s,'SELECT'),has_table_privilege(current_user,%s,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",('public.'+name,)*2).fetchone()
            if not selected or writes: raise ValueError('Reader effective permissions changed.')
    status,metadata=handle_api('/api/wells/meta')
    if status!=200 or metadata['backend']['storage']!='postgresql': raise ValueError('Well metadata unavailable.')
    status,listing=handle_api('/api/wells',{'q':'','limit':'3'})
    if status!=200 or listing['total']!=metadata['counts']['wells']: raise ValueError('Well listing count mismatch.')
    with connect() as (db,release,data):
        rid=release['release_id'];pid=release['production_id']
        db.execute('SET LOCAL statement_timeout=120000')
        counts={key:db.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {'production_id' if key=='production' else 'release_id'}=?",(pid if key=='production' else rid,)).fetchone()['n'] for key,(table,_) in TABLES.items()}
        if any(counts[key]!=data['files'][key]['rows'] for key in TABLES): raise ValueError('Published counts mismatch.')
        totals=db.execute("SELECT COUNT(DISTINCT file_number) AS wells, COUNT(*) AS months, COALESCE(SUM(oil_bbl),0) AS oil, SUM(CASE WHEN quality='invalid' THEN 1 ELSE 0 END) AS invalid FROM well_production WHERE production_id=?",(pid,)).fetchone()
        expected=data.get('production',{}).get('summary',{})
        if expected.get('total_oil_bbl') is not None and Decimal(str(expected['total_oil_bbl']))!=totals['oil']:
            raise ValueError('Production sum differs from validated source bundle.')
        samples=db.execute("SELECT p.file_number,COUNT(*) AS n FROM well_production p WHERE p.production_id=? GROUP BY p.file_number ORDER BY n DESC,p.file_number LIMIT 3",(pid,)).fetchall()
        # Check zero, positive and invalid samples without printing raw records.
        conditions=["quality='reported' AND oil_bbl=0","quality='reported' AND oil_bbl>0","quality='invalid'"]
        checked=[]
        for condition in conditions:
            item=db.execute('SELECT file_number,month,oil_bbl FROM well_production WHERE production_id=? AND '+condition+' LIMIT 1',(pid,)).fetchone()
            if item:
                status,series=handle_api('/api/wells/'+item['file_number']+'/production')
                found=[m for m in series.get('months',[]) if m['month']==str(item['month'])[:7]]
                if status!=200 or len(found)!=1 or found[0]['oil_bbl']!=json_value(item['oil_bbl']): raise ValueError('Production API differs from SQL.')
                checked.append(condition)
        for item in samples:
            number=item['file_number']
            for route in ['/api/wells/'+number,'/api/wells/'+number+'/production','/api/wells/'+number+'/dsus']:
                if handle_api(route)[0]!=200: raise ValueError('Profile endpoint unavailable.')
        status,research=handle_api('/api/forward/meta')
        if status!=200 or research['counts']!={'orders':40,'notices':40}: raise ValueError('Prior research sample changed.')
    return json_value({'verified':True,'environment':'staging','release_id':rid,'counts':counts,
        'production':dict(totals),'reader':'forward_reader','read_only':True,
        'checks':['all relational counts','source oil total','search and profile API','production missing/zero semantics','DSU relationship API','previous Forward sample retained','reader privileges'],
        'sample_checks':checked,'forward_counts':research['counts']})


if __name__=='__main__':
    try: result=verify()
    except Exception: raise SystemExit('Staging well verification failed; provider output withheld.')
    print(json.dumps(result,separators=(',',':')))
