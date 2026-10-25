"""Stage a private one-time recovery deployment; never persist credentials."""
import hashlib
import json
import secrets
from well_operations import ROOT,TARGET,invoke,probe,set_hook,graphql,SERVICE,ENV

state=probe()
if state['checks']['owner_reference_present'] or state['instance']['preDeployCommand']:
    raise SystemExit('Unexpected existing recovery settings.')
bundle=ROOT/'work/connected-wells-deploy/20261022-recovery'
manifest=json.loads((bundle/'BUNDLE-MANIFEST.json').read_text())
raw=(bundle/'staging_rotate_reader.py').read_bytes()
manifest['files']['staging_rotate_reader.py']={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
(bundle/'BUNDLE-MANIFEST.json').write_text(json.dumps(manifest,indent=2))
password=secrets.token_urlsafe(48)
invoke(['variable','set',*TARGET,'--skip-deploys','--stdin','PGPASSWORD'],stdin=password)
password=None
invoke(['variable','set',*TARGET,'--skip-deploys','BAKKEN_IMPORT_DATABASE_URL=${{Postgres.DATABASE_URL}}'])
set_hook('python staging_rotate_reader.py')
command="sh -c 'python verify_wells.py && exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 30 --access-logfile - backend:application'"
graphql('mutation($service:String!,$environment:String!,$input:ServiceInstanceUpdateInput!){serviceInstanceUpdate(serviceId:$service,environmentId:$environment,input:$input)}',{'service':SERVICE,'environment':ENV,'input':{'startCommand':command}})
print(json.dumps({'prepared':True,'staging_only':True,'temporary_owner_reference_requires_cleanup':True}))
