"""Local-only survey viewer with on-demand read-only LAS gamma and cement-bond amplitude extraction."""
from pathlib import Path
import argparse, functools, http.server, json, sys, threading, urllib.parse

PACKAGE=Path(__file__).resolve().parent
sys.path.insert(0,str(PACKAGE/'gamma-data'))
from gamma_service import GammaStore
from cbl_service import CBLStore
from averaging import get_averaged_well

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-browser',action='store_true');parser.add_argument('--port',type=int,default=0);parser.add_argument('--log',choices=['gamma','cbl'],default='gamma');args=parser.parse_args()
    stores={'gamma':GammaStore(),'cbl':CBLStore()}
    catalogs={kind:(PACKAGE/'gamma-data'/filename).read_bytes() for kind,filename in [('gamma','catalog-client.json'),('cbl','cbl-catalog-client.json')]}
    extraction_lock=threading.RLock()
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self,*a,**kw):super().__init__(*a,directory=str(PACKAGE),**kw)
        def log_message(self,fmt,*args):
            if args and str(args[1] if len(args)>1 else '').startswith(('4','5')):super().log_message(fmt,*args)
        def end_headers(self):
            self.send_header('Cache-Control','no-cache')
            self.send_header('X-Content-Type-Options','nosniff')
            super().end_headers()
        def json_response(self,value,status=200):
            body=value if isinstance(value,bytes) else json.dumps(value,separators=(',',':'),allow_nan=False).encode('utf8')
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            request=urllib.parse.urlsplit(self.path)
            route=request.path.strip('/').split('/')
            if len(route)==3 and route[0]=='api' and route[1] in stores:
                store=stores[route[1]];endpoint=route[2]
                try:
                    if endpoint=='catalog':return self.json_response(catalogs[route[1]])
                    query=urllib.parse.parse_qs(request.query);permit=query.get('permit',[''])[0]
                    if not permit.isdigit():return self.json_response({'error':'A numeric FileNo is required.'},400)
                    if endpoint=='sources':
                        value=store.get_sources(permit)
                        return self.json_response(value if value else {'error':'FileNo is not in this log catalog.'},200 if value else 404)
                    if endpoint=='well':
                        source=query.get('source',[None])[0]
                        average=float(query.get('average',['0'])[0])
                        if average not in (0,100):raise ValueError('Average interval must be 0 (detailed) or 100 ft.')
                        with extraction_lock:
                            value=get_averaged_well(store,permit,source_id=source,interval_ft=100) if average else store.get_well(permit,source_id=source,step=5 if route[1]=='cbl' else 10)
                        return self.json_response(value)
                    return self.json_response({'error':'Unknown log endpoint.'},404)
                except (ValueError,KeyError,FileNotFoundError) as error:return self.json_response({'error':str(error)},422)
                except Exception as error:return self.json_response({'error':'Log extraction failed: '+str(error)},500)
            # Serving is restricted to the prepared viewer and data assets.
            if request.path=='/':
                self.send_response(302);self.send_header('Location','/viewer/?dataset=full&gamma=1');self.end_headers();return
            target=(PACKAGE/urllib.parse.unquote(request.path).lstrip('/')).resolve()
            allowed=any(target.is_relative_to((PACKAGE/name).resolve()) for name in ('viewer','full-dataset'))
            if not allowed:
                self.send_error(404);return
            return super().do_GET()
    server=http.server.ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    url=f'http://127.0.0.1:{server.server_port}/viewer/?dataset=full&gamma=1'+('&log=cbl' if args.log=='cbl' else '')
    print('Well log viewer: '+url,flush=True)
    if not args.no_browser:
        import webbrowser
        webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:server.server_close()

if __name__=='__main__':main()
