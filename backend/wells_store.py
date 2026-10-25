"""Explicit, append-only well-release import. No web request invokes this module.

The active pointer changes only after all content hashes, counts and foreign keys
pass in one transaction. Existing releases and Forward's research sample survive.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

APP = 'bakken-well-profiles'
VERSION = 1
APPLICATION_ID = 0x424B574C
DEFAULT_DB = Path(__file__).parent / 'data/wells.sqlite3'
TABLES = {
    'wells': ('well_registry', ('file_number','api','well_name','operator','status','search_text','payload')),
    'branches': ('well_branches', ('branch_id','file_number','api','payload')),
    'dsus': ('well_dsus', ('dsu_id','formation','nominal_acres','measured_acres','payload')),
    'memberships': ('well_memberships', ('dsu_id','file_number','api','overlap_ft','overlap_share','payload')),
    'production': ('well_production', ('file_number','month','oil_bbl','quality','payload')),
    'issues': ('well_issues', ('issue_id','kind','file_number','payload')),
}


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',',':'), sort_keys=True)


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def bundle(path):
    """Read only fixed named inputs; reject partial, changed or arbitrary packages."""
    root = Path(path).resolve()
    manifest_path = root / 'release.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('A complete immutable release.json is required.')
    raw = manifest_path.read_bytes()
    if len(raw)>8*1024*1024:
        raise ValueError('Oversized release manifest.')
    data = json.loads(raw)
    release_id = data.get('release_id','')
    if not isinstance(release_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{12,100}',release_id):
        raise ValueError('Invalid release identity.')
    files = data.get('files',{})
    if set(files) != set(TABLES):
        raise ValueError('Release must contain every expected table.')
    for key in TABLES:
        item = files[key]
        target = root / (key+'.csv.gz')
        if target.is_symlink() or not target.is_file() or target.stat().st_size>1024*1024*1024:
            raise ValueError('Missing, linked or oversized release table.')
        if item.get('sha256') != sha_file(target):
            raise ValueError('Release table fingerprint changed: '+key)
        if type(item.get('rows')) is not int or not 0<=item['rows']<=20_000_000:
            raise ValueError('Invalid release row count.')
    if files['wells']['rows']<1 or files['dsus']['rows']<1:
        raise ValueError('Refusing an empty core GIS release.')
    return root,data,hashlib.sha256(raw).hexdigest()


def read_rows(root,key):
    expected = len(TABLES[key][1])
    csv.field_size_limit(32*1024*1024)
    with gzip.open(root/(key+'.csv.gz'),'rt',encoding='utf-8',newline='') as stream:
        for row in csv.reader(stream):
            if len(row)!=expected:
                raise ValueError('Unexpected column count: '+key)
            row = [None if value=='\\N' else value[1:] if re.fullmatch(r'\\{2,}N',value) else value for value in row]
            # Ensure JSON is valid and finite before either SQL adapter accepts it.
            json.loads(row[-1],parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            yield row


def production_identity(data):
    identities=data.get('production',{}).get('identities')
    if not isinstance(identities,dict): raise ValueError('Production API bindings are required.')
    for number,api in identities.items():
        if not re.fullmatch(r'[1-9][0-9]{0,8}',number) or not isinstance(api,str) or not re.fullmatch(r'33[0-9]{12}',api):
            raise ValueError('Invalid production file/API binding.')
    production_id=hashlib.sha256(dump({'csv_sha256':data['files']['production']['sha256'],'identities':identities}).encode()).hexdigest()
    return production_id,identities


def sqlite_schema():
    # Equivalent portable constraints for loopback preview and integration tests.
    return '''
    CREATE TABLE well_app(id INTEGER PRIMARY KEY CHECK(id=1),app_name TEXT NOT NULL,schema_version INTEGER NOT NULL);
    INSERT INTO well_app VALUES(1,'bakken-well-profiles',1);
    CREATE TABLE well_production_versions(production_id TEXT PRIMARY KEY,row_count INTEGER NOT NULL CHECK(row_count>=0),payload TEXT NOT NULL);
    CREATE TABLE well_production_identities(production_id TEXT NOT NULL REFERENCES well_production_versions(production_id),file_number TEXT NOT NULL,api TEXT NOT NULL,PRIMARY KEY(production_id,file_number));
    CREATE TABLE well_releases(release_id TEXT PRIMARY KEY,imported_at TEXT DEFAULT CURRENT_TIMESTAMP,manifest_sha256 TEXT NOT NULL,production_id TEXT NOT NULL REFERENCES well_production_versions(production_id),payload TEXT NOT NULL);
    CREATE TABLE well_active(id INTEGER PRIMARY KEY CHECK(id=1),release_id TEXT NOT NULL REFERENCES well_releases);
    CREATE TABLE well_registry(release_id TEXT NOT NULL REFERENCES well_releases,file_number TEXT NOT NULL,api TEXT,well_name TEXT,operator TEXT,status TEXT,search_text TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(release_id,file_number));
    CREATE INDEX well_registry_name ON well_registry(release_id,well_name,file_number);
    CREATE TABLE well_branches(release_id TEXT NOT NULL,branch_id TEXT NOT NULL,file_number TEXT NOT NULL,api TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(release_id,branch_id),FOREIGN KEY(release_id,file_number) REFERENCES well_registry(release_id,file_number));
    CREATE INDEX well_branches_file ON well_branches(release_id,file_number);
    CREATE TABLE well_dsus(release_id TEXT NOT NULL REFERENCES well_releases,dsu_id TEXT NOT NULL,formation TEXT,nominal_acres NUMERIC CHECK(nominal_acres IS NULL OR nominal_acres>=0),measured_acres NUMERIC CHECK(measured_acres IS NULL OR measured_acres>=0),payload TEXT NOT NULL,PRIMARY KEY(release_id,dsu_id));
    CREATE TABLE well_memberships(release_id TEXT NOT NULL,dsu_id TEXT NOT NULL,file_number TEXT NOT NULL,api TEXT NOT NULL,overlap_ft REAL NOT NULL CHECK(overlap_ft>0),overlap_share REAL NOT NULL CHECK(overlap_share>0 AND overlap_share<=1.000001),payload TEXT NOT NULL,PRIMARY KEY(release_id,dsu_id,file_number,api),FOREIGN KEY(release_id,dsu_id) REFERENCES well_dsus(release_id,dsu_id),FOREIGN KEY(release_id,file_number) REFERENCES well_registry(release_id,file_number));
    CREATE INDEX well_memberships_file ON well_memberships(release_id,file_number);
    CREATE TABLE well_production(production_id TEXT NOT NULL REFERENCES well_production_versions(production_id),file_number TEXT NOT NULL,month TEXT NOT NULL,oil_bbl NUMERIC,quality TEXT NOT NULL CHECK(quality IN ('reported','invalid')),payload TEXT NOT NULL,PRIMARY KEY(production_id,file_number,month),FOREIGN KEY(production_id,file_number) REFERENCES well_production_identities(production_id,file_number),CHECK((quality='reported' AND oil_bbl IS NOT NULL AND oil_bbl>=0) OR (quality='invalid' AND oil_bbl IS NULL)));
    CREATE TABLE well_issues(release_id TEXT NOT NULL REFERENCES well_releases,issue_id TEXT NOT NULL,kind TEXT NOT NULL,file_number TEXT,payload TEXT NOT NULL,PRIMARY KEY(release_id,issue_id));
    '''


def assert_marker(connection,postgres=False):
    row = connection.execute('SELECT app_name,schema_version FROM well_app WHERE id=1').fetchone()
    if tuple(row or ())!=(APP,VERSION):
        raise ValueError('Unexpected well-profile database ownership marker.')


def import_sqlite(path,target=DEFAULT_DB):
    root,data,fingerprint = bundle(path)
    production_id,identities=production_identity(data)
    target_input = Path(target).expanduser()
    if target_input.is_symlink():
        raise ValueError('Database target must not be a symlink.')
    target = target_input.resolve()
    if target.is_relative_to(root):
        raise ValueError('Database must be separate from the immutable bundle.')
    existed = target.exists()
    target.parent.mkdir(parents=True,exist_ok=True)
    connection = sqlite3.connect(target)
    try:
        connection.execute('PRAGMA foreign_keys=ON')
        if existed:
            if connection.execute('PRAGMA application_id').fetchone()[0]!=APPLICATION_ID:
                raise ValueError('Refusing to alter an unrelated SQLite file.')
            assert_marker(connection)
        else:
            connection.executescript(sqlite_schema())
            connection.execute(f'PRAGMA application_id={APPLICATION_ID}')
            connection.commit()
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            previous = connection.execute('SELECT manifest_sha256 FROM well_releases WHERE release_id=?',(data['release_id'],)).fetchone()
            if previous:
                if previous[0]!=fingerprint:
                    raise ValueError('Release ID reused with different content.')
            else:
                production_exists=connection.execute('SELECT row_count FROM well_production_versions WHERE production_id=?',(production_id,)).fetchone()
                if production_exists and production_exists[0]!=data['files']['production']['rows']:
                    raise ValueError('Existing production version count differs.')
                if not production_exists:
                    connection.execute('INSERT INTO well_production_versions VALUES(?,?,?)',(production_id,data['files']['production']['rows'],dump(data.get('production',{}))))
                    connection.executemany('INSERT INTO well_production_identities VALUES(?,?,?)',[(production_id,n,a) for n,a in identities.items()])
                connection.execute('INSERT INTO well_releases(release_id,manifest_sha256,production_id,payload) VALUES(?,?,?,?)',(data['release_id'],fingerprint,production_id,dump(data)))
                for key,(table,columns) in TABLES.items():
                    if key=='production' and production_exists: continue
                    version_column='production_id' if key=='production' else 'release_id'
                    version_id=production_id if key=='production' else data['release_id']
                    sql = f"INSERT INTO {table}({version_column},{','.join(columns)}) VALUES({','.join('?' for _ in range(len(columns)+1))})"
                    count,batch = 0,[]
                    for row in read_rows(root,key):
                        batch.append((version_id,*row));count+=1
                        if len(batch)==5000:
                            connection.executemany(sql,batch);batch=[]
                    if batch: connection.executemany(sql,batch)
                    if count!=data['files'][key]['rows']:
                        raise ValueError('Row count differs: '+key)
            if bundle(root)[2]!=fingerprint: raise ValueError('Bundle changed during import.')
            orphan=connection.execute('SELECT 1 FROM well_production_identities p LEFT JOIN well_registry w ON w.release_id=? AND w.file_number=p.file_number AND w.api=p.api WHERE p.production_id=? AND w.file_number IS NULL LIMIT 1',(data['release_id'],production_id)).fetchone()
            if orphan: raise ValueError('Production identity absent from release registry.')
            connection.execute('INSERT INTO well_active VALUES(1,?) ON CONFLICT(id) DO UPDATE SET release_id=excluded.release_id',(data['release_id'],))
        return {'release_id':data['release_id'],'counts':{k:v['rows'] for k,v in data['files'].items()},'storage':'sqlite'}
    finally:
        connection.close()


def import_postgres(path,url,*,initialize=False,grant_reader=False):
    import psycopg
    from psycopg import sql
    root,data,fingerprint = bundle(path)
    production_id,identities=production_identity(data)
    with psycopg.connect(url,connect_timeout=10,options='-c search_path=public -c statement_timeout=0 -c lock_timeout=10000') as connection:
        current_user,readonly=connection.execute("SELECT current_user,current_setting('transaction_read_only')").fetchone()
        if current_user=='forward_reader' or readonly!='off':
            raise ValueError('A separate writable import connection is required.')
        # Serialize importers; API readers remain on their repeatable-read release.
        connection.execute('SELECT pg_advisory_xact_lock(6060171701)')
        present = connection.execute("SELECT to_regclass('public.well_app')").fetchone()[0]
        if not present:
            if not initialize:
                raise ValueError('Explicit --initialize is required for new well tables.')
            names = ['well_app','well_production_versions','well_production_identities','well_releases','well_active',*[v[0] for v in TABLES.values()]]
            for name in names:
                if connection.execute('SELECT to_regclass(%s)',('public.'+name,)).fetchone()[0]:
                    raise ValueError('Refusing a partial or unrelated well schema.')
            connection.execute(Path(__file__).with_name('wells_schema.sql').read_text())
        assert_marker(connection,True)
        previous = connection.execute('SELECT manifest_sha256 FROM well_releases WHERE release_id=%s',(data['release_id'],)).fetchone()
        if previous:
            if previous[0]!=fingerprint:
                raise ValueError('Release ID reused with different content.')
        else:
            production_exists=connection.execute('SELECT row_count FROM well_production_versions WHERE production_id=%s',(production_id,)).fetchone()
            if production_exists and production_exists[0]!=data['files']['production']['rows']:
                raise ValueError('Existing production version count differs.')
            if not production_exists:
                connection.execute('INSERT INTO well_production_versions VALUES(%s,%s,%s::jsonb)',(production_id,data['files']['production']['rows'],dump(data.get('production',{}))))
                with connection.cursor().copy('COPY well_production_identities(production_id,file_number,api) FROM STDIN') as copy:
                    for number,api in identities.items(): copy.write_row((production_id,number,api))
            connection.execute('INSERT INTO well_releases(release_id,manifest_sha256,production_id,payload) VALUES(%s,%s,%s,%s::jsonb)',(data['release_id'],fingerprint,production_id,dump(data)))
            for key,(table,columns) in TABLES.items():
                if key=='production' and production_exists: continue
                version_column='production_id' if key=='production' else 'release_id'
                version_id=production_id if key=='production' else data['release_id']
                statement = sql.SQL('COPY {} ({}) FROM STDIN').format(sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,(version_column,*columns))))
                count=0
                with connection.cursor().copy(statement) as copy:
                    for row in read_rows(root,key):
                        copy.write_row((version_id,*row));count+=1
                if count!=data['files'][key]['rows']:
                    raise ValueError('Row count differs: '+key)
                stored=connection.execute(sql.SQL('SELECT COUNT(*) FROM {} WHERE {}=%s').format(sql.Identifier(table),sql.Identifier(version_column)),(version_id,)).fetchone()[0]
                if stored!=count: raise ValueError('PostgreSQL count differs: '+key)
        if grant_reader:
            marker=connection.execute("SELECT shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname='forward_reader'").fetchone()
            if marker!=('bakken-forward-preview dedicated read-only role v1',):
                raise ValueError('Expected dedicated staging reader is absent.')
            names = ['well_app','well_production_versions','well_production_identities','well_releases','well_active',*[v[0] for v in TABLES.values()]]
            connection.execute(sql.SQL('GRANT SELECT ON {} TO forward_reader').format(sql.SQL(',').join(map(sql.Identifier,names))))
            for name in names:
                allowed,write=connection.execute("SELECT has_table_privilege('forward_reader',%s,'SELECT'),has_table_privilege('forward_reader',%s,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",('public.'+name,)*2).fetchone()
                if not allowed or write: raise ValueError('Unexpected reader table privileges.')
        if bundle(root)[2]!=fingerprint: raise ValueError('Bundle changed during import.')
        orphan=connection.execute('SELECT 1 FROM well_production_identities p LEFT JOIN well_registry w ON w.release_id=%s AND w.file_number=p.file_number AND w.api=p.api WHERE p.production_id=%s AND w.file_number IS NULL LIMIT 1',(data['release_id'],production_id)).fetchone()
        if orphan: raise ValueError('Production identity absent from release registry.')
        connection.execute('INSERT INTO well_active VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET release_id=excluded.release_id',(data['release_id'],))
    return {'release_id':data['release_id'],'counts':{k:v['rows'] for k,v in data['files'].items()},'storage':'postgresql'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle',type=Path)
    parser.add_argument('--db',type=Path,default=DEFAULT_DB)
    parser.add_argument('--postgres',action='store_true')
    parser.add_argument('--initialize',action='store_true')
    parser.add_argument('--grant-reader',action='store_true')
    parser.add_argument('--confirm-staging-import',action='store_true')
    args=parser.parse_args()
    try:
        if args.postgres:
            if not args.confirm_staging_import or os.environ.get('RAILWAY_ENVIRONMENT_NAME')!='staging':
                raise ValueError('PostgreSQL import requires explicit staging environment and confirmation.')
            url=os.environ.get('BAKKEN_IMPORT_DATABASE_URL','')
            if not url: raise ValueError('A separate import connection is required.')
            result=import_postgres(args.bundle,url,initialize=args.initialize,grant_reader=args.grant_reader)
        else:
            if args.initialize or args.grant_reader or args.confirm_staging_import:
                raise ValueError('PostgreSQL flags require --postgres.')
            result=import_sqlite(args.bundle,args.db)
    except Exception:
        parser.exit(1,'Well import failed; active release preserved. Inspect local validation/configuration. Database provider output is withheld.\n')
    print(dump(result))


if __name__=='__main__': main()
