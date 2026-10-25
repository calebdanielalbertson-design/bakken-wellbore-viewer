"""Loopback profile preview; token stays in the server process, never the browser."""
import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from serve import page_bytes


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def serve(origin, token, port=58529):
    if not re.fullmatch(r'https://[a-z0-9-]+\.up\.railway\.app',origin):
        raise ValueError('Expected staging Railway HTTPS hostname.')
    opener = build_opener(NoRedirect)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def send(self,status,body,kind='application/json'):
            self.send_response(status)
            for k,v in [('Content-Type',kind),('Content-Length',str(len(body))),('Cache-Control','no-store'),('X-Robots-Tag','noindex, nofollow'),('X-Content-Type-Options','nosniff')]:
                self.send_header(k,v)
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            expected=f'127.0.0.1:{port}'
            if self.headers.get('Host') != expected or self.headers.get('Origin',f'http://{expected}') != f'http://{expected}' or self.headers.get('Sec-Fetch-Site','none') not in {'none','same-origin'}:
                return self.send(403,b'{"error":{"message":"Local preview only."}}')
            path=urlsplit(self.path).path
            if path.startswith('/api/'):
                if len(self.path)>4096 or not re.fullmatch(r'/api/wells(?:/(?:meta|[0-9]{1,8})(?:/(?:production|dsus))?)?',path):
                    return self.send(404,b'{"error":{"message":"This dataset is not connected to Railway staging."}}')
                try:
                    request=Request(origin+self.path,headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
                    with opener.open(request,timeout=25) as result:
                        body=result.read(8_000_001)
                        if len(body)>8_000_000: raise ValueError('Oversized response')
                        json.loads(body)
                        return self.send(result.status,body)
                except HTTPError as error:
                    return self.send(error.code,b'{"error":{"message":"Staging API request could not be completed."}}')
                except Exception:
                    return self.send(503,b'{"error":{"message":"Railway staging is unavailable. No local data fallback was used."}}')
            if path=='/': path='/profiles/'
            content=page_bytes(path)
            if content is None: return self.send(404,b'Not found','text/plain')
            body,kind=content
            if path=='/profiles/':
                body=body.replace(b'LOCAL STAGING PREVIEW',b'RAILWAY STAGING PREVIEW').replace(b'Saved well records \xc2\xb7 not a live feed',b'Connected to PostgreSQL \xc2\xb7 historical imported records').replace(b'local read-only API',b'Railway read-only API')
            if path=='/profiles/profiles.js':
                body=body.replace(b'The local FracFocus snapshot could not be loaded. Treatment coverage is unavailable.',b'FracFocus is not connected to Railway staging yet. Treatment coverage is unavailable here.').replace(b'The local well API is not ready.',b'The Railway staging API is not ready.')
            return self.send(200,body,kind)
    print(f'Local: http://127.0.0.1:{port}/profiles/',flush=True)
    ThreadingHTTPServer(('127.0.0.1',port),Handler).serve_forever()
