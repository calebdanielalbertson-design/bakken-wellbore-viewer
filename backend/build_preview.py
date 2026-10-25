"""Create a local homepage variation without touching the hosted Site."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
import workspace_paths as wp
SITE = wp.SITE_DIST
html = (SITE/'index.html').read_text(encoding='utf-8')
html = html.replace('<a href="#explore">Capabilities</a>', '<a href="/forward/">Bakken Forward</a>', 1)
html = html.replace('<body>', '<body><div class="local-preview-note"><div class="page-width"><strong>LOCAL PREVIEW</strong><span>A possible Bakken Forward addition · the public website is unchanged</span></div></div>', 1)
html = html.replace('</head>', '<meta name="robots" content="noindex,nofollow"><style>.local-preview-note{background:#e6ebdf;color:#4e6242;font-size:10px;border-bottom:1px solid #d1dbcb}.local-preview-note>.page-width{display:flex;gap:15px;align-items:center;min-height:34px}.local-preview-note strong{font-size:9px;letter-spacing:.12em;white-space:nowrap}.forward-introduction{background:#e8eddf;border-bottom:1px solid #d3dece}.forward-introduction>.page-width{display:grid;grid-template-columns:1fr 1fr;gap:70px;align-items:center;padding-block:54px}.forward-introduction .eyebrow{color:#6d7e51;font-size:9px;margin-bottom:15px}.forward-introduction h2{font-size:40px}.forward-introduction p:not(.eyebrow){font-size:13px;color:#52634f;line-height:1.85;max-width:530px}.forward-introduction .text-link{margin-top:22px;font-size:12px}.primary-nav{flex-wrap:wrap;row-gap:9px}@media(max-width:800px){.forward-introduction>.page-width{grid-template-columns:1fr;gap:22px}.local-preview-note span{font-size:8px}.forward-introduction h2{font-size:35px}}@media(max-width:480px){.primary-nav{gap:12px;font-size:9px}.primary-nav .nav-cta{font-size:9px;padding:8px}.local-preview-note>.page-width{gap:9px;min-height:40px}.local-preview-note strong{font-size:8px}}</style></head>', 1)
html = re.sub(r'<link rel="canonical"[^>]+>', '', html)
section = '''<section class="forward-introduction"><div class="page-width"><div><p class="eyebrow">A possible next chapter / Bakken Forward</p><h2>The activity above.<br>The evidence behind it.</h2></div><div><p>Connect the spatial perspective with reported well activity and historical regulatory evidence. A research desk keeps source dates, coverage, and review status in view.</p><a class="text-link" href="/forward/">Explore the local research preview <span aria-hidden="true">↗</span></a></div></div></section>'''
html = html.replace('<section class="explore-section', section+'\n<section class="explore-section', 1)
(ROOT/'index.html').write_text(html, encoding='utf-8')
print('Local homepage variation prepared. Hosted source unchanged.')
