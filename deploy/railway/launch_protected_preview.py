"""Launch local preview after validating staging authorization; no secret output."""
import json,sys
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError
from well_operations import ROOT,invoke,TARGET
sys.path.insert(0,str(ROOT/'work/bakken-forward-preview'))
from railway_preview import serve,NoRedirect

origin=sys.argv[1]
if not origin.startswith('https://') or not origin.endswith('.up.railway.app'):
    raise SystemExit('Expected verified Railway staging origin.')
variables=json.loads(invoke(['variable','list',*TARGET,'--json']))
token=variables['BAKKEN_PREVIEW_TOKEN']
if variables.get('BAKKEN_IMPORT_DATABASE_URL'):
    raise SystemExit('Unexpected owner access.')
variables=None
opener=build_opener(NoRedirect)
def get(path,key=None):
    try:
        request=Request(origin+path,headers={'Authorization':'Bearer '+key} if key else {})
        with opener.open(request,timeout=30) as result:
            return result.status,json.loads(result.read())
    except HTTPError as error:
        return error.code,None

for key in [None,'invalid-preview-token']:
    if get('/api/wells/meta',key)[0]!=401:
        raise SystemExit('Unauthenticated API rejection failed.')
status,meta=get('/api/wells/meta',token)
if status!=200 or meta['backend']['storage']!='postgresql':
    raise SystemExit('Live PostgreSQL metadata failed.')
for path in ['/api/wells?q=CHLOE&limit=3','/api/wells?q=35721&limit=3','/api/wells/19033','/api/wells/19033/production','/api/wells/19033/dsus']:
    if get(path,token)[0]!=200: raise SystemExit('Live profile endpoint failed.')
print(json.dumps({'verified_live_https':True,'unauthorized_denied':True,'storage':'postgresql','counts':meta['counts']}),flush=True)
serve(origin,token)
