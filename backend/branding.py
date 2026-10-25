"""Local-only branding layer. Never changes the hosted Site or viewer markup."""
import re

PAGE_CLASSES = {
    '/': 'brand-home', '/index.html': 'brand-home',
    '/forward': 'brand-research', '/forward/': 'brand-research',
    '/setup': 'brand-setup', '/setup/': 'brand-setup',
    '/methodology': 'brand-methodology', '/methodology/': 'brand-methodology',
    '/methodology/index.html': 'brand-methodology',
}

LOGO = '''<span class="brand-logo"><img src="/assets/bakken-logo-original.png" width="1536" height="1024" alt="Bakken Subsurface Analytics" decoding="async"></span>'''
BRAND_LINK = '<a class="brand" href="/" aria-label="Bakken Subsurface Analytics home">' + LOGO + '</a>'


def apply_branding(html, route):
    page_class = PAGE_CLASSES.get(route)
    if not page_class:
        return html
    # Public pages can already carry the approved brand after publication.
    # Reuse their content without duplicating styles or retaining a public class.
    html = re.sub(r'<link rel="stylesheet" href="/(?:brand\.css|forward/forward-brand\.css)">', '', html)
    html, count = re.subn(r'<a class="brand"[^>]*>.*?</a>', BRAND_LINK,
                          html, count=1, flags=re.S)
    if count != 1:
        raise ValueError('Expected one recognizable non-viewer header brand.')
    html = re.sub(r'<a class="footer-brand"[^>]*>.*?</a>',
                  '<a class="footer-brand" href="/" aria-label="Bakken Subsurface Analytics home">' + LOGO + '</a>',
                  html, count=1, flags=re.S)
    html = re.sub(r'<body(?: class="(?:brand-site|brand-preview) [^"]+")?>',
                  '<body class="brand-preview ' + page_class + '">', html, count=1)
    html = re.sub(r'<meta name="theme-color"[^>]*>', '<meta name="theme-color" content="#3f4549">', html)
    html = re.sub(r'<link rel="icon"[^>]*>', '<link rel="icon" type="image/svg+xml" href="/assets/brand-mark.svg">', html)
    links = '<link rel="stylesheet" href="/brand.css">'
    if page_class in {'brand-research', 'brand-setup'}:
        links += '<link rel="stylesheet" href="/forward/forward-brand.css">'
    html = html.replace('</head>', links + '</head>', 1)
    if page_class == 'brand-home':
        html = html.replace('<a class="button button-lime"', '<a class="button button-blue"', 1)
    return html
