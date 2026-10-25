"""Authenticated, bounded staging HTTP boundary. Database stays private."""
import hmac
import os
import threading
from backend import application as backend

slots = threading.BoundedSemaphore(4)


def reply(start, code, message):
    body = ('{"error":{"message":"' + message + '"}}').encode()
    start(code, [('Content-Type','application/json'),('Content-Length',str(len(body))),
                 ('Cache-Control','no-store'),('X-Robots-Tag','noindex, nofollow')])
    return [body]


def application(environ, start_response):
    path = environ.get('PATH_INFO','')
    if path == '/health':
        # Public readiness contains no records, release IDs or connection details.
        from backend import handle_api
        status, _ = handle_api('/health')
        return reply(start_response, '200 OK' if status == 200 else '503 Service Unavailable',
                     'ready' if status == 200 else 'unavailable')
    token = os.environ.get('BAKKEN_PREVIEW_TOKEN','')
    supplied = environ.get('HTTP_AUTHORIZATION','')
    if len(token) < 40:
        return reply(start_response,'503 Service Unavailable','Preview access is not configured.')
    if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        return reply(start_response,'401 Unauthorized','Preview authorization required.')
    if environ.get('REQUEST_METHOD') != 'GET':
        return reply(start_response,'405 Method Not Allowed','Only GET is supported.')
    if not (path == '/api/wells' or path.startswith('/api/wells/')):
        return reply(start_response,'404 Not Found','Endpoint not available in this preview.')
    if not slots.acquire(blocking=False):
        return reply(start_response,'429 Too Many Requests','Please try again shortly.')
    try:
        return backend(environ,start_response)
    finally:
        slots.release()
