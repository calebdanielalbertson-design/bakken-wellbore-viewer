"""Stage the Bakken Subsurface 3D viewer (the LAS catalog project's map3d/ page) under site/dist/3d/.

    python scripts/prepare_3d_viewer.py "<path to the catalog's map3d folder>"            # public edition
    python scripts/prepare_3d_viewer.py "<map3d folder>" --edition full                   # internal preview only

The source page fetches its float arrays as base64 text because Claude artifacts serve text only. This script writes
a site edition instead:

- dist/3d/index.html: the page with a document skeleton and a loader that reads gzip objects from data/ and inflates
  them in the browser (DecompressionStream, the same requirement the survey viewer's transport already makes).
- dist/3d/data/<name>.gz.bin: meta.json and every <name>.b64.txt decoded back to bytes and stored as one deterministic
  gzip object each. The folder is git-ignored (data/); publish it with scripts/datasets.py pack/push as site-3d-data.
- dist/3d/release.json: edition, build date, well count, source and stored sizes and SHA-256s (tracked in Git).

Public edition ("level 1", the default). The NDIC subscription agreement bars practices that substantially duplicate
the Division's subscription services, so the public copy keeps the picture and drops the subscription-only numbers:
- Disposal wells: the per-well yearly injection volumes, rates and wellhead pressures are replaced by a size class
  (five classes of water disposed to date) with the ring radius scaled to the class value; basin totals per year
  are precomputed for the timeline (meta.swd_year) from the real series, which never leaves this script.
- Lateral log values (median gamma ray, total gas, gas wetness per path point) are stored as 16 colour levels over
  each colour mode's range, so the colouring is unchanged and the per-point readings are gone; the card's numeric
  log lines are removed.
- Cement study: the categorical classes stay (they drive the colour modes); the numeric cement top, offset to the
  Inyan Kara and good-bond share are nulled and their colour modes removed from the menu.
- The card's per-well Inyan Kara top is removed; casing shoe depths are rounded to 100 ft.
- A provenance paragraph is added to "About the data".
Production, completion, geometry and the gridded models are public-source or derived and are kept as they are.

Nothing in the source folder is modified. Existing files in dist/3d/ are overwritten by name, never deleted.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import gzip
import hashlib
import json
import math
import re
import sys
from array import array
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DIST = REPO / 'site' / 'dist'
DATA_FILES = ['meta.json', 'paths.b64.txt', 'surfaces.b64.txt', 'years.b64.txt', 'depl.b64.txt',
              'future.b64.txt', 'inj.b64.txt', 'plume.b64.txt']
REQUIRED = {'index.html', 'meta.json', 'paths.b64.txt', 'surfaces.b64.txt'}

# Public edition: colour-mode ranges of the per-point log columns in map3d/index.html (MODES gr / gas / wet)
LOG_LEVELS = 16
LOG_COLS = {3: (20.0, 200.0, False), 4: (10.0, 3000.0, True), 5: (20.0, 80.0, False)}
STRIDE = 9
# Disposal volume classes (MMbbl of water disposed to date): upper edges and the value each class is drawn at
SWD_EDGES = [1.0, 5.0, 20.0, 50.0]
SWD_REP = [0.5, 2.5, 10.0, 30.0, 65.0]
SWD_CLASSES = ['under 1 MMbbl', '1 to 5 MMbbl', '5 to 20 MMbbl', '20 to 50 MMbbl', 'over 50 MMbbl']
NULLED_WELL_FIELDS = ('cem_top', 'cem_ik', 'bond_good')

# Exact-text patches to the page. Each must match once, so a changed map3d/index.html fails here instead of shipping
# a half-patched copy. (old, new) pairs; a regex patch is (pattern, replacement, 'regex').
LOADER_PATCHES = [
    (
        "    const f32 = (name) => fetch(name, { cache: 'no-cache' }).then((r) => { if (!r.ok) throw new Error(name + ' ' + r.status); return r.text(); })\n"
        "      .then((t) => { const s = atob(t.trim()), u = new Uint8Array(s.length); for (let i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return u.buffer; });\n",
        "    // bakkensubsurface.com edition (scripts/prepare_3d_viewer.py): the data files ship as gzip objects under data/ and\n"
        "    // are inflated in the browser, as the site's survey viewer does; cache: 'no-cache' keeps the revalidation behaviour\n"
        "    const inflate = (path) => fetch(path, { cache: 'no-cache' }).then((r) => {\n"
        "      if (!r.ok) throw new Error(path + ' ' + r.status);\n"
        "      if (typeof DecompressionStream !== 'function') throw new Error('this viewer needs a current browser with gzip DecompressionStream support');\n"
        "      return new Response(r.body.pipeThrough(new DecompressionStream('gzip')));\n"
        "    });\n"
        "    const f32 = (name) => inflate('data/' + name.replace(/\\.b64\\.txt$/, '.gz.bin')).then((r) => r.arrayBuffer());\n",
    ),
    (
        "      fetch('meta.json', { cache: 'no-cache' }).then((r) => { if (!r.ok) throw new Error('meta ' + r.status); return r.json(); }),\n",
        "      inflate('data/meta.gz.bin').then((r) => r.json()),\n",
    ),
]
PROVENANCE = (
    '    <p class="prov">Public edition. Sources: North Dakota Industrial Commission, Oil and Gas Division (well index, '
    'directional surveys and spacing units from the public GIS, monthly production reports to January 2026, formation '
    'tops and digital well logs under the Division\'s subscription service), FracFocus (March 2026) and USGS 3DEP. '
    'Everything shown is derived or modelled from those records: log readings appear as colour classes, cement and bond '
    'results as classes, disposal volumes as size classes, and the Dakota injection plane is a model. No NDIC logs, well '
    'files, tops tables or production or injection tables are redistributed here; the records are at '
    '<a href="https://www.dmr.nd.gov/oilgas/" rel="noopener">dmr.nd.gov/oilgas</a>. Free to use, no warranty.</p>\n'
)
PUBLIC_PATCHES = [
    (
        "      const cum = s.cum[yi], on = cum !== null && cum > 0, rr = on && s.r[yi] ? s.r[yi] : 0;\n",
        "      const cum = s.cumc[yi], on = cum !== null && cum > 0, rr = on && s.r[yi] ? s.r[yi] : 0;\n",
    ),
    (
        "Colour and ring: water disposed to date; the ring radius",
        "Colour and ring: water disposed to date, in five size classes; the ring radius",
    ),
    (
        "`<span><i class=\"sw\" style=\"background:#${(cumColor(cum, c), c.getHexString())}\"></i>${esc(s.name || s.w)} · ${cum.toFixed(1)} MMbbl · r ${fmt.format(s.r[yi] || 0)} ft${s.psi[yi] ? ' · ' + fmt.format(s.psi[yi]) + ' psi wellhead' : ''}</span>`",
        "`<span><i class=\"sw\" style=\"background:#${(cumColor(cum, c), c.getHexString())}\"></i>${esc(s.name || s.w)} · ${esc((meta.swd_classes || [])[s.cls[yi] - 1] || '')} · r ${fmt.format(s.r[yi] || 0)} ft</span>`",
    ),
    (
        "      let mm = 0, n = 0;\n"
        "      for (const s of meta.swd) { const c = s.cum[yi], p = yi > 0 ? s.cum[yi - 1] : null; if (c !== null) { mm += c - (p || 0); if (c - (p || 0) > 0) n++; } }\n"
        "      parts.push(`<span><b>${mm.toFixed(0)} MMbbl</b> into the Dakota this year, ${n} disposal wells</span>`);\n",
        "      const sy = meta.swd_year || {}, mm = (sy.mmbbl || [])[yi], n = (sy.wells || [])[yi];  // basin totals, precomputed\n"
        "      if (mm !== undefined && mm !== null) parts.push(`<span><b>${mm.toFixed(0)} MMbbl</b> into the Dakota this year, ${n} disposal wells</span>`);\n",
    ),
    (
        "        <dt>Inyan Kara top (subsea)</dt><dd>${d(ikTop, (x) => fmt.format(x) + ' ft')}</dd>\n",
        "",
    ),
    (r"\n[ \t]*<dt>Lateral gamma ray, median</dt>.*?<dt>Lateral gas wetness, median</dt><dd>.*?</dd>", "", 'regex'),
    (r"\n[ \t]*<option value=\"bond_good\">[^\n]*</option>", "", 'regex'),
    (r"\n[ \t]*<option value=\"cem_ik\">[^\n]*</option>", "", 'regex'),
    (r"\n[ \t]*<option value=\"cem_top\">[^\n]*</option>", "", 'regex'),
    ('    <div id="foot"></div>\n', '    <div id="foot"></div>\n' + PROVENANCE),
]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stored_name(name: str) -> str:
    stem = name[:-len('.b64.txt')] if name.endswith('.b64.txt') else name[:-len('.json')]
    return stem + '.gz.bin'


def apply_patches(html: str, patches: list) -> str:
    for patch in patches:
        if len(patch) == 3:
            pattern, repl, _ = patch
            if len(re.findall(pattern, html, flags=re.S)) != 1:
                raise SystemExit(f'page patch pattern did not match exactly once: {pattern[:70]}')
            html = re.sub(pattern, repl, html, count=1, flags=re.S)
        else:
            old, new = patch
            if html.count(old) != 1:
                raise SystemExit(f'page patch text did not match exactly once: {old[:70]!r}')
            html = html.replace(old, new)
    return html


def patch_page(html: str, public: bool) -> str:
    if html.lstrip().lower().startswith('<!doctype'):
        raise SystemExit('index.html already has a document skeleton; expected the artifact-style page')
    html = apply_patches(html, LOADER_PATCHES)
    if "fetch('meta.json'" in html:
        raise SystemExit('an unpatched meta.json fetch remains in index.html')
    if public:
        html = apply_patches(html, PUBLIC_PATCHES)
    return '<!doctype html>\n<html lang="en">\n' + html.rstrip('\n') + '\n</html>\n'


# ------------------------------------------------------------------ public edition data filter

def quantize(v: float, lo: float, hi: float, log: bool) -> float:
    if v != v:  # NaN stays "not logged"
        return v
    if log:
        x = 0.0 if v <= 0 else (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
    else:
        x = (v - lo) / (hi - lo)
    i = min(LOG_LEVELS - 1, max(0, math.floor(x * LOG_LEVELS)))
    centre = (i + 0.5) / LOG_LEVELS
    return lo * (hi / lo) ** centre if log else lo + centre * (hi - lo)


def filter_paths(payload: bytes, stride: int) -> bytes:
    a = array('f')
    a.frombytes(payload)
    if len(a) % stride:
        raise SystemExit(f'paths.bin length is not a multiple of the stride {stride}')
    for col, (lo, hi, log) in LOG_COLS.items():
        for i in range(col, len(a), stride):
            a[i] = quantize(a[i], lo, hi, log)
    return a.tobytes()


def swd_class(cum: float) -> int:
    for k, edge in enumerate(SWD_EDGES):
        if cum < edge:
            return k + 1
    return len(SWD_EDGES) + 1


def filter_meta(meta: dict) -> dict:
    wells = meta['wells']
    for key in NULLED_WELL_FIELDS:
        if key in wells:
            wells[key] = [None] * len(wells[key])
    if wells.get('shoes'):
        for sh in wells['shoes']:
            if sh:
                for e in sh:  # [type, md, od, reported, x, y, z]
                    e[1] = int(round(e[1] / 100.0) * 100)
                    if len(e) > 6 and e[6] is not None:
                        e[6] = int(round(e[6] / 100.0) * 100)
    swd = meta.get('swd') or []
    if swd:
        ny = len(swd[0]['cum'])
        mmbbl, nwells = [0.0] * ny, [0] * ny
        for s in swd:
            cum = s['cum']
            prev = 0.0
            for yi in range(ny):
                c = cum[yi]
                if c is not None:
                    delta = c - prev
                    mmbbl[yi] += delta
                    if delta > 0:
                        nwells[yi] += 1
                    prev = c
        meta['swd_year'] = {'mmbbl': [round(v, 1) for v in mmbbl], 'wells': nwells}
        meta['swd_classes'] = SWD_CLASSES
        for s in swd:
            cls, cumc, rr = [], [], []
            for c, r in zip(s['cum'], s['r']):
                if c is None:
                    cls.append(None); cumc.append(None); rr.append(None)
                elif c <= 0:
                    cls.append(0); cumc.append(0); rr.append(0)
                else:
                    k = swd_class(c)
                    rep = SWD_REP[k - 1]
                    cls.append(k); cumc.append(rep)
                    rr.append(int(round(r * math.sqrt(rep / c))) if r else 0)  # ring area scales with volume
            for key in ('cum', 'rate', 'psi'):
                s.pop(key, None)
            s['cls'], s['cumc'], s['r'] = cls, cumc, rr
    meta['edition'] = 'public-level-1'
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', type=Path, help="the catalog project's map3d folder")
    parser.add_argument('--dist', type=Path, default=DEFAULT_DIST, help='site dist folder (default site/dist)')
    parser.add_argument('--slug', default='3d', help='folder under dist (default 3d)')
    parser.add_argument('--edition', choices=('public', 'full'), default='public',
                        help='public (default): level-1 filter described above; full: unfiltered, internal previews only')
    args = parser.parse_args(argv)
    source: Path = args.source
    public = args.edition == 'public'
    missing = sorted(n for n in REQUIRED if not (source / n).is_file())
    if missing:
        raise SystemExit(f'{source} is missing {", ".join(missing)}')
    out = args.dist / args.slug
    data_dir = out / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)

    page = patch_page((source / 'index.html').read_text(encoding='utf-8'), public)
    (out / 'index.html').write_text(page, encoding='utf-8', newline='\n')
    page_bytes = page.encode('utf-8')

    meta = json.loads((source / 'meta.json').read_text(encoding='utf-8'))
    stride = int(meta.get('stride') or STRIDE)
    if public:
        meta = filter_meta(meta)
    entries: dict[str, dict] = {}
    for name in DATA_FILES:
        path = source / name
        if not path.is_file():
            print(f'- skip  {name} (not in source; the page treats it as optional)')
            continue
        raw = path.read_bytes()
        if name == 'meta.json':
            payload = json.dumps(meta, separators=(',', ':'), allow_nan=False).encode('utf-8') if public else raw
        else:
            payload = base64.b64decode(raw.strip(), validate=True)
            sibling = source / (name[:-len('.b64.txt')] + '.bin')
            if sibling.is_file() and sibling.read_bytes() != payload:
                print(f'- note  {sibling.name} differs from {name}; the base64 copy (what the page reads) was used')
            if public and name == 'paths.b64.txt':
                payload = filter_paths(payload, stride)
        stored = gzip.compress(payload, compresslevel=9, mtime=0)
        target = data_dir / stored_name(name)
        target.write_bytes(stored)
        entries[stored_name(name)] = {'source': name, 'bytes': len(payload), 'sha256': sha(payload),
                                      'storedBytes': len(stored), 'storedSHA256': sha(stored)}
        print(f'- wrote {target.relative_to(args.dist).as_posix():28s} {len(payload)/1e6:7.2f} MB -> {len(stored)/1e6:6.2f} MB')

    release = {
        'kind': 'bakken-subsurface-3d',
        'version': 2,
        'edition': 'public-level-1' if public else 'full',
        'built': meta.get('built'),
        'prepared': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
        'wells': meta.get('n_wells') or len(meta['wells']['w']),
        'vertices': meta.get('n_vertices'),
        'layers': len(meta.get('layers') or []),
        'years': [meta['years'][0], meta['years'][-1]] if meta.get('years') else None,
        'transport': 'one gzip object per data file under data/, inflated in the browser with DecompressionStream',
        'page': {'bytes': len(page_bytes), 'sha256': sha(page_bytes)},
        'data': entries,
    }
    if public:
        release['public_filter'] = [
            f'disposal wells: per-well volumes, rates and pressures replaced by {len(SWD_CLASSES)} size classes '
            f'({", ".join(SWD_CLASSES)}); ring radius scaled to the class value; basin totals per year precomputed',
            f'lateral log values (gamma ray, total gas, gas wetness) stored as {LOG_LEVELS} colour levels per mode range',
            'cement study: numeric cement top, offset to the Inyan Kara and good-bond share nulled; classes kept',
            'card: per-well Inyan Kara top and numeric log lines removed; casing shoe depths rounded to 100 ft',
            'provenance paragraph in About the data',
        ]
    (out / 'release.json').write_text(json.dumps(release, indent=2) + '\n', encoding='utf-8', newline='\n')
    total = sum(e['storedBytes'] for e in entries.values()) + len(page_bytes)
    print(f"- {args.slug}/ ({release['edition']}): {release['wells']:,} wellbores, built {release['built']}, "
          f"{total/1e6:.2f} MB stored ({sum(e['bytes'] for e in entries.values())/1e6:.2f} MB of data)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
