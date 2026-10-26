"""Apply the approved branding to public pages; never copy the local prototype.

This prepares source files only. Sites source sync/save/deploy remain explicit.
"""
from pathlib import Path
import hashlib
import json
from branding import apply_branding

ROOT = Path(__file__).resolve().parent
import workspace_paths as wp
SITE = wp.SITE_DIST.parent
DIST = SITE / 'dist'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

baseline = {str(p.relative_to(DIST)): sha(p) for p in (DIST/'viewer').rglob('*') if p.is_file()}
for name, route in [('index.html', '/'), ('methodology/index.html', '/methodology/')]:
    page = DIST / name
    original = page.read_text(encoding='utf-8')
    if '/brand.css' in original:
        raise SystemExit('Public page already branded; refusing duplicate transform.')
    branded = apply_branding(original, route).replace('brand-preview ', 'brand-site ')
    branded = branded.replace('https://bakkensubsurface.com/favicon.svg',
                              'https://bakkensubsurface.com/assets/bakken-logo-original.png')
    assert '<link rel="canonical"' in branded
    assert 'noindex' not in branded and 'LOCAL PREVIEW' not in branded
    assert '/forward/' not in branded and '/setup/' not in branded
    page.write_text(branded, encoding='utf-8')
(DIST/'brand.css').write_text((ROOT/'brand.css').read_text(encoding='utf-8').replace('.brand-preview', '.brand-site'), encoding='utf-8')
for name in ('bakken-logo-original.png', 'brand-mark.svg'):
    (DIST/'assets'/name).write_bytes((ROOT/'assets'/name).read_bytes())
after = {str(p.relative_to(DIST)): sha(p) for p in (DIST/'viewer').rglob('*') if p.is_file()}
assert after == baseline, 'Viewer source or data changed unexpectedly.'
record = {'viewerFilesVerifiedUnchanged': len(baseline),
          'publicPages': ['/', '/methodology/'],
          'researchAndRailwayRemainStaging': True,
          'logoSHA256': sha(DIST/'assets/bakken-logo-original.png'),
          'viewerSHA256': baseline}
(ROOT/'branding-public-validation.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
print(json.dumps({k:v for k,v in record.items() if k != 'viewerSHA256'}))
