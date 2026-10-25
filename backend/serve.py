"""Loopback-only preview: proposed pages + read-only SQL API + existing viewer.

Never modifies the published checkout or starts a collector. The only viewer
changes are in-memory navigation/selection hooks served for this preview.
"""
from __future__ import annotations
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import mimetypes
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit, urlencode

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
SITE = WORKSPACE / 'sites' / 'bakken-subsurface' / 'dist'
MANIFEST = WORKSPACE / 'outputs' / 'wellbore-viewer' / 'full-dataset' / 'manifest.json'
from backend import handle_api
from branding import apply_branding
sys.path.insert(0, str(ROOT / 'viewer'))


def viewer_registry():
    records = json.loads(MANIFEST.read_text(encoding='utf-8'))['wells']
    registry = {}
    for well in records:
        registry.setdefault(str(well['permit']), set()).add(str(well['api']))
    return registry


def normalized_api(value):
    value = re.sub(r'\D', '', value)
    return value + '0000' if len(value) == 10 else value


def well_link(query, registry):
    permit = (query.get('permit') or [''])[0].strip()
    raw_api = (query.get('api') or [''])[0].strip()
    api = normalized_api(raw_api)
    if not re.fullmatch(r'\d{1,8}', permit):
        return 400, {'error': {'code': 'invalid_permit', 'message': 'A numeric well file number is required.'}}
    if raw_api and (len(api) != 14 or not re.fullmatch(r'[\d\s-]+', raw_api)):
        return 200, {'matched': False, 'reason': 'The saved API is malformed. No map link has been inferred.'}
    choices = registry.get(permit, set())
    if not choices:
        return 200, {'matched': False, 'reason': 'This file number has no horizontal geometry in the October 17 viewer snapshot. A permit notice does not establish a drilled lateral.'}
    if api and api not in choices:
        return 200, {'matched': False, 'reason': 'The saved API does not match the viewer identity. No map link has been inferred.'}
    if not api and len(choices) != 1:
        return 200, {'matched': False, 'reason': 'More than one API identity uses this file number. A confirmed API is needed before selecting a path.'}
    api = api or next(iter(choices))
    return 200, {'matched': True, 'url': '/viewer/?' + urlencode({'dataset': 'full', 'well': permit, 'api': api}), 'note': 'Matched to the October 17 viewer by file number' + (' and the saved API.' if (query.get('api') or [''])[0] else ' with one unique full API identity. The notice and geometry have different source dates.')}


def page_bytes(route):
    """Resolve only public assets; never expose the source tree or SQL files."""
    if route in ('/', '/index.html'):
        target = ROOT / 'index.html'
    elif route in ('/forward', '/forward/'):
        target = ROOT / 'forward/index.html'
    elif route in ('/setup', '/setup/'):
        target = ROOT / 'setup.html'
    elif route in ('/profiles', '/profiles/'):
        target = ROOT / 'profiles/index.html'
    elif route in ('/profiles/profiles.css', '/profiles/profiles.js'):
        target = ROOT / route.lstrip('/')
    elif route in ('/viewer/production.js', '/viewer/activity-model.js', '/viewer/activity.css'):
        target = ROOT / route.lstrip('/')
    elif route == '/viewer/activity.json':
        target = ROOT / 'data/activity-snapshot.json'
    elif route in ('/forward/forward.css', '/forward/forward.js', '/forward/forward-brand.css', '/brand.css', '/assets/bakken-logo-original.png', '/assets/brand-mark.svg'):
        target = ROOT / route.lstrip('/')
    else:
        target = (SITE / route.lstrip('/')).resolve()
        if not target.is_relative_to(SITE.resolve()):
            return None
        if target.is_dir():
            target /= 'index.html'
        if target.suffix.lower() not in {'.html', '.css', '.js', '.json', '.geojson', '.bin', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.txt', '.xml', '.woff', '.woff2'}:
            return None
    # Preserve the earlier local comparison after its checked implementation is
    # promoted into the publishing checkout. The guarded hooks need that exact
    # pre-promotion source, not an already transformed public file.
    baseline_names = {'/viewer/': 'index.html', '/viewer/index.html': 'index.html',
                      '/viewer/app.js': 'app.js', '/viewer/sidebar.js': 'sidebar.js',
                      '/viewer/mobile-controls.js': 'mobile-controls.js',
                      '/viewer/public-assets-index.json': 'public-assets-index.json'}
    if route in baseline_names:
        baseline = ROOT.parent / 'fracfocus-release/baseline/viewer' / baseline_names[route]
        if baseline.is_file():
            target = baseline
    if not target.is_file():
        return None
    raw = target.read_bytes()
    if target.suffix.lower() == '.html':
        raw = apply_branding(raw.decode('utf-8'), route).encode('utf-8')
        if route not in ('/profiles', '/profiles/', '/viewer/', '/viewer/index.html'):
            text = raw.decode('utf-8')
            if '<nav class="primary-nav"' in text:
                text = text.replace('</nav>', '<a href="/profiles/">Well profiles</a></nav>', 1)
            raw = text.encode('utf-8')
    if route == '/viewer/app.js':
        hook = "const requestedColor=new URLSearchParams(location.search).get('color');"
        bridge = "const previewQuery=new URLSearchParams(location.search);const previewPermit=previewQuery.get('well'),previewAPI=previewQuery.get('api');if(previewPermit&&previewAPI){const previewRow=wellSearch?.search(previewAPI).rows.find(r=>r.well.permit===previewPermit&&r.well.api===previewAPI);if(previewRow)await select(previewRow.well,true);}"
        from preview_hooks import transform_app
        text = transform_app(raw.decode('utf-8'))
        if text.count(hook) != 1:
            raise ValueError('The local viewer selection hook no longer matches this source version.')
        raw = text.replace(hook, bridge + hook, 1).encode('utf-8')
    if route in ('/viewer/', '/viewer/index.html'):
        text = raw.decode('utf-8')
        text = text.replace('<h2>Monthly oil</h2>', '<h2>Production &amp; activity</h2>', 1)
        text = text.replace('<div id="productionPanelBody">', '<div id="productionPanelBody"><label class="field" for="timelineMode">Timeline data</label><select id="timelineMode"><option value="oil">Monthly oil</option><option value="activity">Spud &amp; frac activity</option></select><div id="activityOptions" hidden><p class="activity-note">Current well paths appear from their spud month. Blue lateral width shows reported frac water in the treatment’s completion month.</p><label class="legend-row"><input id="activityUnknown" type="checkbox"><span>Include wells with unknown spud dates</span></label></div>', 1)
        text = text.replace('Size laterals by production', 'Show timeline on map', 1)
        text = text.replace('<p class="caption">Display width ∝', '<p id="timelineWidthNote" class="caption">Display width ∝', 1)
        text = text.replace('Production sources and coverage', 'Timeline sources &amp; timing', 1)
        text = text.replace('Pools are summed per well; branches share the well’s value.', 'Branches share their well’s value; summaries count each well once.', 1)
        text = text.replace('Monthly production playback', 'Monthly oil or frac activity playback').replace('Monthly production timeline', 'Monthly timeline').replace('Production month', 'Timeline month')
        text = text.replace('</head>', '<link rel="stylesheet" href="activity.css"></head>', 1)
        text = text.replace('<div class="header-actions">', '<div class="header-actions"><a class="button forward-back" href="/forward/">Research ↗</a>', 1)
        text = text.replace('</head>', '<meta name="robots" content="noindex,nofollow"><style>.header-actions #sample,.header-actions>label.button{display:none}.header-actions .forward-back{display:inline-flex;align-items:center;min-height:44px;padding:8px 10px;font-size:12px;text-decoration:none}</style></head>', 1)
        raw = text.encode('utf-8')
    if route == '/viewer/sidebar.js':
        text = raw.decode('utf-8').replace('Compare reported monthly oil and follow its changes over time.', 'Follow the same date slider through oil production or spud and frac activity.')
        text = text.replace("'Oil overlay on'", "'Timeline on'")
        text = text.replace("['1','on','true'].includes(params.get('production'))?'production'", "(params.get('timeline')==='activity'||['1','on','true'].includes(params.get('production')))?'production'")
        raw = text.encode('utf-8')
    if route == '/viewer/mobile-controls.js':
        text = raw.decode('utf-8').replace('Show production', 'Show timeline').replace('Hide production', 'Hide timeline').replace('production playback', 'timeline playback')
        raw = text.encode('utf-8')
    return raw, mimetypes.guess_type(str(target))[0] or 'application/octet-stream'


class PreviewHandler(SimpleHTTPRequestHandler):
    registry = viewer_registry()

    def do_GET(self):
        self.respond()

    def do_HEAD(self):
        self.respond(head=True)

    def do_POST(self):
        self.send_payload(405, b'{"error":{"code":"method_not_allowed","message":"Only GET is supported."}}', 'application/json', False)

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST

    def respond(self, head=False):
        parsed = urlsplit(self.path)
        route = unquote(parsed.path)
        try:
            if len(parsed.query) > 4096:
                raise ValueError('Query too long')
            query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=20)
        except ValueError:
            return self.send_payload(400, b'{"error":{"code":"invalid_request","message":"Invalid query string."}}', 'application/json', head)
        if route == '/api/forward/well-link':
            status, payload = well_link(query, self.registry)
            return self.send_payload(status, json.dumps(payload).encode('utf-8'), 'application/json', head)
        if re.fullmatch(r'/api/wells/[^/]+/fracfocus', route):
            # Local prototype only: no FracFocus route is added to Railway WSGI.
            from fracfocus_backend import handle_api as handle_fracfocus
            status, payload = handle_fracfocus(route, query)
            return self.send_payload(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'), 'application/json', head)
        if route.startswith('/api/') or route == '/health':
            status, payload = handle_api(route, query)
            return self.send_payload(status, json.dumps(payload, ensure_ascii=False).encode('utf-8'), 'application/json', head)
        if route == '/robots.txt':
            return self.send_payload(200, b'User-agent: *\nDisallow: /\n', 'text/plain', head)
        try:
            content = page_bytes(route)
        except (OSError, ValueError):
            content = None
        if content is None:
            return self.send_payload(404, b'Local preview resource not found.', 'text/plain', head)
        return self.send_payload(200, content[0], content[1], head)

    def send_payload(self, status, raw, content_type, head):
        self.send_response(status)
        self.send_header('Content-Type', content_type + ('; charset=utf-8' if content_type.startswith('text/') or content_type == 'application/json' else ''))
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Robots-Tag', 'noindex, nofollow')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        if not head:
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=58519)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), PreviewHandler)
    print(f'Bakken Forward local preview: http://127.0.0.1:{args.port}/forward/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
