"""Prepare an allowlisted private API/import bundle, never upload source stores."""
import argparse,hashlib,json,shutil
from pathlib import Path
from wells_store import bundle,sha_file
import workspace_paths as wp

BASE=Path(__file__).resolve().parent
FILES=['backend.py','import_snapshot.py','schema_postgres.sql','wells_backend.py','wells_store.py',
       'wells_schema.sql','verify_wells.py','staging_well_import.py','requirements.txt']
DOCKER='''FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 forward
COPY --chown=forward:forward *.py *.sql ./
COPY --chown=forward:forward data/ ./data/
USER forward
EXPOSE 8080
CMD ["sh", "-c", "exec gunicorn --bind \\\"0.0.0.0:${PORT:-8080}\\\" --workers 2 --threads 4 --timeout 30 --access-logfile - backend:application"]
'''


def prepare(release,destination):
    source,data,fingerprint=bundle(release)
    destination=Path(destination).resolve()
    allowed=wp.WORK/'connected-wells-deploy'
    if not destination.is_relative_to(allowed.resolve()) or destination==allowed.resolve() or destination.exists():
        raise ValueError('Choose a new folder beneath work/connected-wells-deploy.')
    contents={name:(BASE/name).read_bytes() for name in FILES}
    contents['Dockerfile']=DOCKER.encode()
    contents['.dockerignore']=b'__pycache__/\n*.sqlite*\n.env*\n.git/\n'
    contents['data/forward-snapshot.json']=(BASE/'data/forward-snapshot.json').read_bytes()
    destination.mkdir(parents=True,exist_ok=False)
    for name,raw in contents.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    for name in ['release.json',*[key+'.csv.gz' for key in data['files']]]:
        path=destination/'data/well-release'/name;path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/name,path)
    if bundle(destination/'data/well-release')[2]!=fingerprint: raise ValueError('Copied bundle integrity differs.')
    manifest={'purpose':'Private Railway staging API and one-time import only',
              'release_id':data['release_id'],'release_manifest_sha256':fingerprint,
              'files':{str(p.relative_to(destination)).replace('\\','/'):{'sha256':sha_file(p),'bytes':p.stat().st_size}
                       for p in destination.rglob('*') if p.is_file()}}
    (destination/'BUNDLE-MANIFEST.json').write_text(json.dumps(manifest,indent=2))
    return {'release_id':data['release_id'],'files':len(manifest['files']),
            'bytes':sum(v['bytes'] for v in manifest['files'].values()),'destination':str(destination)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('release',type=Path);p.add_argument('destination',type=Path)
    args=p.parse_args()
    print(json.dumps(prepare(args.release,args.destination)))
