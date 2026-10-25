"""Bounded, read-only connected-well API for immutable staging releases."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date,datetime
from decimal import Decimal
import json
import os
import re
import sqlite3
from urllib.parse import quote,urlencode,urlsplit

from backend import InvalidInput,Unavailable,ReadConnection,_scalar,_number,_error,search_text
from wells_store import DEFAULT_DB,APPLICATION_ID,APP,VERSION


def json_value(value):
    if isinstance(value,(datetime,date)): return value.isoformat()
    if isinstance(value,Decimal): return int(value) if value==value.to_integral_value() else float(value)
    if isinstance(value,dict): return {k:json_value(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [json_value(v) for v in value]
    return value


def unpack(value):
    return json.loads(value) if isinstance(value,str) else value


@contextmanager
def connect():
    connection=None
    try:
        url=os.environ.get('DATABASE_URL','').strip()
        if url:
            if urlsplit(url).scheme not in {'postgres','postgresql'}: raise Unavailable()
            import psycopg
            from psycopg.rows import dict_row
            connection=psycopg.connect(url,connect_timeout=5,row_factory=dict_row,options='-c default_transaction_read_only=on -c statement_timeout=5000 -c search_path=public')
            connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            storage='postgresql'
        else:
            from pathlib import Path
            path=Path(os.environ.get('BAKKEN_WELLS_DB_PATH',str(DEFAULT_DB))).expanduser().resolve()
            connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)
            connection.row_factory=sqlite3.Row
            connection.execute('PRAGMA query_only=ON');connection.execute('BEGIN')
            if connection.execute('PRAGMA application_id').fetchone()[0]!=APPLICATION_ID: raise Unavailable()
            storage='sqlite'
        db=ReadConnection(connection,storage)
        marker=db.execute('SELECT app_name,schema_version FROM well_app WHERE id=1').fetchone()
        if not marker or marker['app_name']!=APP or marker['schema_version']!=VERSION: raise Unavailable()
        release=db.execute('SELECT r.release_id,r.production_id,r.manifest_sha256,r.imported_at,r.payload FROM well_active a JOIN well_releases r ON r.release_id=a.release_id WHERE a.id=1').fetchone()
        if not release or not re.fullmatch(r'[a-f0-9]{64}',release['manifest_sha256']): raise Unavailable()
        yield db,dict(release),unpack(release['payload'])
    finally:
        if connection is not None: connection.close()


def public_release(release,metadata):
    return {'id':release['release_id'],'label':metadata.get('label','Staging GIS and historical production'),
            'source_date':metadata.get('source_date'),'sha256':release['manifest_sha256'],
            'imported_at':release['imported_at']}


def production_metadata(metadata):
    # API bindings are an importer integrity input, not repeated profile payload.
    return {key:value for key,value in metadata.get('production',{}).items()
            if key not in {'identities','identity_sha256','validation_samples'}}


def public_well(row):
    result=unpack(row['payload']) or {}
    result.update({key:row[key] for key in ('file_number','api','well_name','operator','status')})
    for key in ('branch_count','has_production'):
        if key in row.keys(): result[key]=row[key]
    return result


def coverage(db,production_id,file_number):
    row=db.execute("SELECT COUNT(*) AS observed, SUM(CASE WHEN quality='reported' THEN 1 ELSE 0 END) AS reported, MIN(month) AS first_month, MAX(month) AS last_month FROM well_production WHERE production_id=? AND file_number=?",(production_id,file_number)).fetchone()
    return {'observed_months':row['observed'],'reported_months':row['reported'] or 0,
            'invalid_months':row['observed']-(row['reported'] or 0),
            'first_month':str(row['first_month'])[:7] if row['first_month'] else None,
            'last_month':str(row['last_month'])[:7] if row['last_month'] else None,
            'note':'Historical whole-well oil only. Missing reports are unknown; current survey branches do not date historical production.'}


def memberships(db,release_id,file_number,metadata):
    rows=db.execute('SELECT m.dsu_id,m.api,m.overlap_ft,m.overlap_share,m.payload AS membership_payload,d.formation,d.nominal_acres,d.measured_acres,d.payload AS dsu_payload FROM well_memberships m JOIN well_dsus d ON d.release_id=m.release_id AND d.dsu_id=m.dsu_id WHERE m.release_id=? AND m.file_number=? ORDER BY m.overlap_ft DESC,m.dsu_id LIMIT 201',(release_id,file_number)).fetchall()
    total=db.execute('SELECT COUNT(*) AS n FROM well_memberships WHERE release_id=? AND file_number=?',(release_id,file_number)).fetchone()['n']
    result=[]
    for row in rows[:200]:
        dsu=unpack(row['dsu_payload'])
        label=dsu.get('label') or row['dsu_id']
        if '\ufffd' in label:
            parts=[row['formation']]
            if row['nominal_acres'] is not None: parts.append(f"{float(row['nominal_acres']):,.0f} acres")
            if dsu.get('spacingType'): parts.append(dsu['spacingType'])
            label=' · '.join(str(part) for part in parts if part) or row['dsu_id']
        result.append({'dsu_id':row['dsu_id'],'label':label,
                       'api':row['api'],'formation':row['formation'],'nominal_acres':row['nominal_acres'],
                       'measured_acres':row['measured_acres'],'relationship':'Geometric lateral overlap',
                       'overlap_ft':row['overlap_ft'],'overlap_share':row['overlap_share'],
                       'source_date':metadata.get('source_date'),'details':unpack(row['membership_payload'])})
    return {'rows':result,'coverage':{'total':total,'returned':len(result),'truncated':total>200},
            'provenance':{'release_id':release_id,'note':'Original GIS footprints with positive surveyed lateral overlap. This is not a legal assignment, ownership or production allocation. Overlapping DSU totals are not additive.'}}


def handle_api(path,query=None):
    query={} if query is None else query
    try:
        if not isinstance(query,dict): raise InvalidInput('Invalid query.')
        listing=path=='/api/wells'
        meta=path=='/api/wells/meta'
        match=re.fullmatch(r'/api/wells/([1-9][0-9]{0,8})(?:/(production|dsus))?',path)
        if not listing and not meta and not match: return _error(404,'not_found','Well endpoint not found.')
        term='';offset=0;limit=20
        if listing:
            if set(query)-{'q','offset','limit'}: raise InvalidInput('Unsupported query parameter.')
            term=search_text(_scalar(query,'q',maximum=200))
            offset=_number(query,'offset',0,100_000);limit=_number(query,'limit',20,50)
        elif query: raise InvalidInput('This endpoint does not accept query parameters.')
        with connect() as (db,release,metadata):
            rid=release['release_id'];pid=release['production_id'];pub=public_release(release,metadata)
            if meta:
                counts={key:item['rows'] for key,item in metadata['files'].items()}
                counts.update(metadata.get('counts',{}))
                return 200,json_value({'release':pub,'counts':counts,'production':production_metadata(metadata),
                    'classifier':metadata.get('classifier',{}),'sources':metadata.get('sources',{}),
                    'limitations':metadata.get('limitations',[]),'backend':{'storage':db.storage,'mode':'read-only','environment':'staging'}})
            if listing:
                where='w.release_id=?';params=[rid]
                if term:
                    where+=" AND w.search_text LIKE ? ESCAPE '\\'"
                    params.append('%'+term.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
                total=db.execute('SELECT COUNT(*) AS n FROM well_registry w WHERE '+where,tuple(params)).fetchone()['n']
                rows=db.execute('SELECT w.*, (SELECT COUNT(*) FROM well_branches b WHERE b.release_id=w.release_id AND b.file_number=w.file_number) AS branch_count, EXISTS(SELECT 1 FROM well_production p WHERE p.production_id=(SELECT production_id FROM well_releases WHERE release_id=w.release_id) AND p.file_number=w.file_number) AS has_production FROM well_registry w WHERE '+where+' ORDER BY w.well_name,w.file_number LIMIT ? OFFSET ?',(*params,limit,offset)).fetchall()
                return 200,json_value({'rows':[public_well(row) for row in rows],'total':total,'offset':offset,'limit':limit,'release':pub})
            file_number,section=match.groups()
            row=db.execute('SELECT * FROM well_registry WHERE release_id=? AND file_number=?',(rid,file_number)).fetchone()
            if not row: return _error(404,'not_found','This well is not present in the selected source release.')
            if section=='dsus': return 200,json_value(memberships(db,rid,file_number,metadata))
            production_coverage=coverage(db,pid,file_number)
            if section=='production':
                rows=db.execute('SELECT month,oil_bbl,quality,payload FROM well_production WHERE production_id=? AND file_number=? ORDER BY month',(pid,file_number)).fetchall()
                indexed={str(item['month'])[:7]:item for item in rows}
                months=sorted(set(metadata.get('production',{}).get('months',[]))|set(indexed))
                values=[{'month':month,'oil_bbl':indexed[month]['oil_bbl'] if month in indexed else None,'quality':indexed[month]['quality'] if month in indexed else 'missing'} for month in months]
                production_coverage['total_months']=len(months)
                return 200,json_value({'months':values,'units':'bbl','coverage':production_coverage,
                    'provenance':{'release_id':rid,'source':production_metadata(metadata),
                      'note':'Distinct reported pools summed once at whole-well level. No interpolation. Missing/invalid is not zero. Production is not allocated to DSUs or branches.'}})
            branches=db.execute('SELECT branch_id,api,payload FROM well_branches WHERE release_id=? AND file_number=? ORDER BY branch_id',(rid,file_number)).fetchall()
            well=public_well(row)
            details=[]
            for item in branches:
                payload=unpack(item['payload']);payload.update({'id':item['branch_id'],'api':item['api']});details.append(payload)
            # A file-only viewer selection must not silently choose conflicting APIs.
            apis={item['api'] for item in branches}
            viewer_url='/viewer/?'+urlencode({'dataset':'full','well':file_number,'api':next(iter(apis))}) if len(apis)==1 else None
            return 200,json_value({'well':well,'branches':details,'viewer_url':viewer_url,'production_coverage':production_coverage,
                'dsus':memberships(db,rid,file_number,metadata)['rows'],
                'provenance':{'release':pub,'sources':metadata.get('sources',{}),'classifier':metadata.get('classifier',{}),
                   'note':'GIS reported operator/status describe the source snapshot. Branches are mapped surveys, not proof of completed or currently producing intervals.'}})
    except InvalidInput as exc:
        return _error(400,'invalid_request',str(exc))
    except Exception:
        return _error(503,'wells_unavailable','The validated well release is unavailable. The last successful release has not been replaced by missing data.')
