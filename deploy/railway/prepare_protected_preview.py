import hashlib,json,secrets
from well_operations import ROOT,TARGET,invoke,probe,graphql,SERVICE,ENV,wp
state=probe()
if state['checks']['owner_reference_present']: raise SystemExit('Unexpected owner access.')
folder=wp.WORK/'connected-wells-deploy/20261022-protected-preview'
manifest=json.loads((folder/'BUNDLE-MANIFEST.json').read_text())
raw=(folder/'staging_gateway.py').read_bytes()
manifest['files']['staging_gateway.py']={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
(folder/'BUNDLE-MANIFEST.json').write_text(json.dumps(manifest,indent=2))
invoke(['variable','set',*TARGET,'--skip-deploys','--stdin','BAKKEN_PREVIEW_TOKEN'],stdin=secrets.token_urlsafe(48))
command="sh -c 'python verify_wells.py && exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 2 --threads 4 --timeout 30 --access-logfile - staging_gateway:application'"
graphql('mutation($service:String!,$environment:String!,$input:ServiceInstanceUpdateInput!){serviceInstanceUpdate(serviceId:$service,environmentId:$environment,input:$input)}',{'service':SERVICE,'environment':ENV,'input':{'startCommand':command}})
print('{"protected_preview_prepared":true}')
