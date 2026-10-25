"""Stream OGD DBF into a disk-backed sort, then export spatial chunks for the viewer.
Usage: python prepare_data.py input.dbf output_folder --tvd-sign positive
Depths are assumed feet. Choose the source CRS explicitly; no elevation correction.
Requires numpy, pandas. No changes are made to the input files.
"""
import argparse, json, math, sqlite3, struct, tempfile
from pathlib import Path
import numpy as np
import pandas as pd
from dataclasses import asdict
from classifier import classify as classify_v2, Settings

LABELS=['Vertical','Directional','Curve','Drillback','Lateral','Unknown']

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path); p.add_argument('output',type=Path)
    p.add_argument('--tvd-sign',choices=['positive','negative'],required=True)
    p.add_argument('--source-crs',choices=['NAD83','WGS84'],default='NAD83')
    p.add_argument('--origin',nargs=2,type=float,metavar=('LONGITUDE','LATITUDE'),help='Fixed tangent-plane origin in source geographic datum; retain when refreshing an existing dataset.')
    p.add_argument('--preserve-sections',action='store_true',help='Preserve supplied section labels instead of applying the new classifier.')
    p.add_argument('--classifier-config',type=Path,help='Optional JSON threshold overrides; see classifier.py Settings.')
    args=p.parse_args(); out=args.output
    if args.origin and not (-180<=args.origin[0]<=180 and -89<=args.origin[1]<=89):
        p.error('--origin requires longitude [-180,180] and latitude [-89,89].')
    cfg=Settings(**(json.loads(args.classifier_config.read_text()) if args.classifier_config else {}))
    out.mkdir(parents=True,exist_ok=True)
    if (out/'manifest.json').exists(): raise SystemExit('Output already contains a dataset. Choose a new directory.')
    with args.input.open('rb') as f:
        h=f.read(32); count=struct.unpack_from('<I',h,4)[0]; start,step=struct.unpack_from('<HH',h,8)
        fields=[]
        for _ in range((start-33)//32):
            d=f.read(32); fields.append((d[:11].split(b'\0')[0].decode().lower(),'S'+str(d[16])))
    dtype=np.dtype([('_deleted','S1')]+fields)
    if dtype.itemsize!=step: raise ValueError('Unsupported DBF record layout')
    rows=np.memmap(args.input,dtype=dtype,mode='r',offset=start,shape=(count,))
    required=['wl_permit','api_wellno','well_sub','long','lat','measdpth','inclinatio','azimuth','tvd']
    for k in required:
        if k not in rows.dtype.names: raise ValueError('Missing DBF field: '+k)
    skipped=0; unknown=0; duplicate=0
    with tempfile.TemporaryDirectory(prefix='well-sort-') as tmp:
        db=sqlite3.connect(str(Path(tmp)/'sort.sqlite'))
        db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA synchronous=OFF');db.execute('PRAGMA temp_store=FILE')
        db.execute('CREATE TABLE s (permit TEXT,api TEXT,branch TEXT,lon REAL,lat REAL,md REAL,inc REAL,azi REAL,tvd REAL,section TEXT)')
        for n in range(0,count,100000):
            block=rows[n:n+100000]; cols={k:np.char.strip(block[k].astype('U')) for k in required}
            df=pd.DataFrame(cols); df['section']=np.char.strip(block['section'].astype('U')) if 'section' in rows.dtype.names else ''
            for k in required[3:]:df[k]=pd.to_numeric(df[k],errors='coerce')
            valid=(block['_deleted']!=b'*')&np.isfinite(df[required[3:]]).all(axis=1)&df['long'].between(-180,180)&df['lat'].between(-89,89)&df['inclinatio'].between(0,180)&(df['measdpth']>=0)&(df['wl_permit']!='')
            valid &= df['tvd']>=0 if args.tvd_sign=='positive' else df['tvd']<=0
            skipped+=int((~valid).sum());df=df[valid].copy();df['well_sub']=df['well_sub'].replace('','MAIN')
            db.executemany('INSERT INTO s VALUES (?,?,?,?,?,?,?,?,?,?)',df.itertuples(index=False,name=None));db.commit()
            print(f'Imported {min(n+100000,count):,}/{count:,}',flush=True)
        db.execute('CREATE INDEX ord ON s(permit,api,branch,md)')
        lon0,lat0=db.execute('SELECT AVG(lon),AVG(lat) FROM s').fetchone()
        if lon0 is None:raise ValueError('No valid survey stations. Check TVD sign and input.')
        if args.origin: lon0,lat0=args.origin
        # Ellipsoidal ECEF projected onto the tangent east/north plane at the dataset center.
        # Original geographic datum is retained; Z is relative TVD, not ellipsoidal height.
        a=6378137.;f=1/(298.257222101 if args.source_crs=='NAD83' else 298.257223563);e2=f*(2-f)
        lo,la=math.radians(lon0),math.radians(lat0)
        nn=a/math.sqrt(1-e2*math.sin(la)**2); origin=np.array([nn*math.cos(la)*math.cos(lo),nn*math.cos(la)*math.sin(lo),nn*(1-e2)*math.sin(la)])
        east=np.array([-math.sin(lo),math.cos(lo),0]);north=np.array([-math.sin(la)*math.cos(lo),-math.sin(la)*math.sin(lo),math.cos(la)])
        manifest={'version':1,'source':args.input.name,'sourceCRS':args.source_crs,'depthUnits':'ft','depthReference':'Relative TVD; no reference elevations applied','tvdSign':args.tvd_sign,'origin':[lon0,lat0],'labels':LABELS,'tiles':[],'wells':[],'classifier':{'name':'Vertical-aware section classifier','version':'2.0','parameters':asdict(cfg),'sectionSource':'preserved when supplied' if args.preserve_sections else 'recomputed','drillbackMeaning':'Pronounced sustained sideways deviation within the upper, mostly vertical interval; geometric candidates.'}}
        tiles={}; handles={}; overview=[]; bounds=[float('inf')]*3+[-float('inf')]*3
        def emit(group):
            nonlocal duplicate,unknown
            if not group:return
            df=pd.DataFrame(group,columns=['permit','api','branch','lon','lat','md','inc','azi','tvd','section'])
            before=len(df);df=df.drop_duplicates('md',keep='last');duplicate+=before-len(df)
            if len(df)<2:return
            lon=np.radians(df.lon.to_numpy());lat=np.radians(df.lat.to_numpy());N=a/np.sqrt(1-e2*np.sin(lat)**2)
            xyz=np.stack([N*np.cos(lat)*np.cos(lon),N*np.cos(lat)*np.sin(lon),N*(1-e2)*np.sin(lat)],axis=1)-origin
            x=xyz@east/.3048;z=-(xyz@north)/.3048;y=-np.abs(df.tvd.to_numpy())
            sec,intervals=classify_v2(df[['md','inc','azi']].to_numpy(),np.column_stack([x,z]),cfg)
            supplied=df.section.str.strip().str.title(); lookup={v:i for i,v in enumerate(LABELS)}
            if args.preserve_sections and (supplied!='').any():
                sec=supplied.map(lookup).fillna(5).to_numpy(dtype=int);unknown+=int((sec==5).sum());intervals=[]
            coords=np.stack([x,y,z,sec],axis=1).astype('<f4');key=f'{math.floor(float(x[0])/50000)}_{math.floor(float(z[0])/50000)}'
            if key not in tiles:
                tiles[key]={'id':key,'file':key+'.bin','stations':0,'wells':0,'bounds':[float('inf')]*3+[-float('inf')]*3};handles[key]=(out/(key+'.bin')).open('wb')
            tile=tiles[key];idx=len(manifest['wells']);first=df.iloc[0]
            well={'id':idx,'permit':str(first.permit),'api':str(first.api),'branch':str(first.branch),'tile':key,'offset':tile['stations'],'count':len(df),'maxTVD':round(float(np.abs(df.tvd).max()),1),'maxMD':round(float(df.md.max()),1)}
            well['drillbackIntervals']=intervals
            mn=coords[:,:3].min(axis=0).tolist();mx=coords[:,:3].max(axis=0).tolist();well['bounds']=mn+mx
            manifest['wells'].append(well);tile['stations']+=len(df);tile['wells']+=1
            for j in range(3):
                bounds[j]=min(bounds[j],mn[j]);bounds[j+3]=max(bounds[j+3],mx[j]);tile['bounds'][j]=min(tile['bounds'][j],mn[j]);tile['bounds'][j+3]=max(tile['bounds'][j+3],mx[j])
            handles[key].write(coords.tobytes())
            # Keep section transitions and regularly sampled stations for overview.
            keep=sorted(set([0,len(df)-1]+list(range(0,len(df),12))+[k for j in range(1,len(sec)) if sec[j]!=sec[j-1] for k in (j-1,j)]))
            for i,j in zip(keep,keep[1:]):overview.append([*coords[i,:3],*coords[j,:3],int(sec[j]),idx])
        group=[];previous=None
        for row in db.execute('SELECT * FROM s ORDER BY permit,api,branch,md,rowid'):
            key=row[:3]
            if key!=previous:emit(group);group=[];previous=key
            group.append(row)
        emit(group)
        for h in handles.values():h.close()
        np.asarray(overview,dtype='<f4').tofile(out/'overview.bin')
        manifest.update(tiles=list(tiles.values()),bounds=bounds,stations=sum(t['stations'] for t in tiles.values()),overviewSegments=len(overview),skipped=skipped,duplicateMD=duplicate,unknownSections=unknown)
        (out/'manifest.json').write_text(json.dumps(manifest,separators=(',',':')),encoding='utf8')
        db.close();print(json.dumps({k:manifest[k] for k in ['stations','skipped','duplicateMD','overviewSegments']}),flush=True)

if __name__=='__main__':main()
