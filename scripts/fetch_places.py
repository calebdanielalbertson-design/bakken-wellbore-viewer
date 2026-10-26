"""Refresh the town labels on the 3D map from public Census and USGS sources.

    python scripts/fetch_places.py

Fetches the internal point of each incorporated place or Census-designated
place in NAMES from Census TIGERweb, and official GNIS locations for the few
communities Census does not list. It writes the same places.geojson to both
viewers (site/dist/viewer/data/reference and explorer/viewer/data/reference)
and records the exact queries and response hashes in
docs/places-provenance.json. Nothing is written unless every name is found.

To add a town: add it to NAMES (and PRIORITY if it should show at the
statewide zoom), run this script, check the map, and open a pull request.
Needs internet access; uses only the Python standard library.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGETS = [REPO / 'site' / 'dist' / 'viewer' / 'data' / 'reference', REPO / 'explorer' / 'viewer' / 'data' / 'reference']
RAW = REPO / 'work' / 'places'          # raw responses (git-ignored scratch)
PROVENANCE = REPO / 'docs' / 'places-provenance.json'

# Orientation points across the Bakken and Three Forks play, in display order.
NAMES = [
    # regional cities
    'Williston', 'Dickinson', 'Minot', 'Bismarck',
    # oilfield towns
    'Watford City', 'Stanley', 'Tioga', 'Powers Lake', 'Alexander', 'Cartwright', 'New Town', 'Killdeer',
    'Ray', 'Crosby', 'Parshall', 'Belfield', 'Arnegard', 'Mandaree', 'Keene',
    'Portal', 'Epping', 'Grenora', 'Columbus', 'Lignite', 'Bowbells', 'Kenmare', 'Fortuna', 'Wildrose',
    'White Earth', 'Ross', 'Plaza', 'Halliday', 'Dunn Center', 'South Heart',
    'Trenton', 'Alamo', 'Ambrose', 'Noonan', 'Tolley', 'Mohall', 'Berthold', 'Ryder', 'Makoti',
    'Four Bears Village', 'Twin Buttes', 'Taylor', 'Zahl', 'Grassy Butte', 'Manning',
]
# Higher priority labels win when labels would overlap; zooming in makes room for the rest.
PRIORITY = {
    **dict.fromkeys(['Williston', 'Dickinson', 'Minot', 'Bismarck'], 100),
    **dict.fromkeys(['Watford City', 'Stanley', 'Tioga', 'Powers Lake', 'Alexander', 'Arnegard', 'Cartwright',
                     'Ray', 'Crosby', 'Portal'], 90),
    **dict.fromkeys(['New Town', 'Killdeer', 'Parshall', 'Kenmare', 'Epping', 'Keene', 'Mandaree'], 70),
}
DEFAULT_PRIORITY = 50
# Communities with no Census place record; located from USGS GNIS (county checked).
GNIS_ONLY = {'Cartwright': 'McKenzie', 'Keene': 'McKenzie', 'Zahl': 'Williams', 'Grassy Butte': 'McKenzie',
             'Manning': 'Dunn', 'Twin Buttes': 'Dunn'}

CENSUS = 'https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer'
GNIS = 'https://carto.nationalmap.gov/arcgis/rest/services/geonames/MapServer/3'
ND_BOX = (-104.1, 45.9, -96.5, 49.1)


def query(layer: str, params: dict, filename: str, sources: list) -> list:
    url = layer + '/query?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'User-Agent': 'BakkenSubsurfaceAnalytics-map-reference-refresh/1.1'})
    raw = urllib.request.urlopen(request, timeout=60).read()
    result = json.loads(raw)
    if result.get('error') or result.get('exceededTransferLimit'):
        raise RuntimeError(f'{layer} returned {result}')
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / filename).write_bytes(raw)
    sources.append({'sourceLayer': layer, 'query': url, 'rawResponse': filename,
                    'sha256': hashlib.sha256(raw).hexdigest(), 'featureCount': len(result['features'])})
    return result['features']


def census_places(names: list[str], sources: list) -> dict:
    features = {}
    where = "STATE='38' AND BASENAME IN (" + ','.join("'" + n.replace("'", "''") + "'" for n in names) + ')'
    for layer_id, label in [(4, 'Incorporated Places'), (5, 'Census Designated Places')]:
        layer = f'{CENSUS}/{layer_id}'
        params = {'where': where, 'outFields': 'NAME,BASENAME,STATE,GEOID,INTPTLAT,INTPTLON', 'returnGeometry': 'false', 'f': 'json'}
        for record in query(layer, params, f'census-layer-{layer_id}.json', sources):
            attrs = record['attributes']
            name = attrs['BASENAME']
            if name in features:
                raise ValueError(f'{name} matched more than one Census place; make the name unambiguous')
            attrs.update({'name': name, 'pointType': 'Census internal point', 'source': 'U.S. Census Bureau, TIGERweb',
                          'sourceLayer': layer, 'placeType': label})
            point = [float(attrs['INTPTLON']), float(attrs['INTPTLAT'])]
            features[name] = {'type': 'Feature', 'properties': attrs, 'geometry': {'type': 'Point', 'coordinates': point}}
    return features


def gnis_place(name: str, county: str, sources: list) -> dict:
    params = {'where': f"gaz_name='{name}' AND state_alpha='ND'",
              'outFields': 'gaz_id,gaz_name,gaz_featureclass,state_alpha,county_name,isunknowncoords',
              'returnGeometry': 'true', 'outSR': '4269', 'f': 'json'}
    records = [r for r in query(GNIS, params, f'gnis-{name.lower().replace(" ", "-")}.json', sources)
               if r['attributes']['gaz_featureclass'] == 'Populated Place' and r['attributes']['county_name'] == county]
    if len(records) != 1:
        raise ValueError(f'GNIS returned {len(records)} populated places named {name} in {county} County')
    attrs, points = records[0]['attributes'], records[0]['geometry']['points']
    return {'type': 'Feature',
            'properties': {'NAME': name, 'BASENAME': name, 'STATE': '38', 'GEOID': None, 'name': name,
                           'pointType': 'GNIS official feature location', 'GNIS_ID': str(attrs['gaz_id']),
                           'source': 'USGS, Geographic Names Information System', 'sourceLayer': GNIS,
                           'placeType': attrs['gaz_featureclass'], 'county': attrs['county_name']},
            'geometry': {'type': 'Point', 'coordinates': points[0]}}


def update_metadata(provenance: dict, sources: list) -> None:
    """Keep the places section of each viewer's reference metadata.json in step with places.geojson."""
    gnis = ', '.join(GNIS_ONLY)
    census_count = len(NAMES) - len(GNIS_ONLY)
    for target in TARGETS:
        path = target / 'metadata.json'
        if not path.exists():
            continue
        metadata = json.loads(path.read_text(encoding='utf-8'))
        metadata['attribution'] = (f'State boundary and Census place internal points: U.S. Census Bureau, TIGERweb. '
                                   f'{gnis} populated-place locations: USGS GNIS. State geometry generalized for display.')
        metadata['places'].update({
            'retrievedAt': provenance['retrievedAt'], 'featureCount': provenance['featureCount'], 'names': NAMES,
            'positioning': (f'Census internal points for {census_count} communities; GNIS official feature locations for {gnis}. '
                            'These are orientation references, not surveyed landmarks or municipal boundaries.'),
            'sources': [{k: s[k] for k in ('sourceLayer', 'query', 'sha256', 'featureCount')} for s in sources],
            'sha256': provenance['sha256']})
        path.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')


def main() -> int:
    if len(set(NAMES)) != len(NAMES):
        raise SystemExit('NAMES contains duplicates')
    sources: list = []
    features = census_places([n for n in NAMES if n not in GNIS_ONLY], sources)
    for name, county in GNIS_ONLY.items():
        features[name] = gnis_place(name, county, sources)
    missing = [n for n in NAMES if n not in features]
    if missing:
        print('Not found (nothing was written): ' + ', '.join(missing), file=sys.stderr)
        print('Check the spelling, or add the community to GNIS_ONLY with its county.', file=sys.stderr)
        return 1
    for name, feature in features.items():
        lon, lat = feature['geometry']['coordinates']
        if not (ND_BOX[0] < lon < ND_BOX[2] and ND_BOX[1] < lat < ND_BOX[3]):
            raise ValueError(f'{name} at {lon}, {lat} is outside North Dakota')
        feature['properties']['labelPriority'] = PRIORITY.get(name, DEFAULT_PRIORITY)
    geojson = {'type': 'FeatureCollection', 'crs': {'type': 'name', 'properties': {'name': 'EPSG:4269'}},
               'features': [features[n] for n in NAMES]}
    raw = (json.dumps(geojson, separators=(',', ':')) + '\n').encode('utf-8')
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        (target / 'places.geojson').write_bytes(raw)
    provenance = {
        'retrievedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'coordinateReferenceSystem': 'EPSG:4269 (NAD83), longitude/latitude',
        'sources': sources, 'featureCount': len(features), 'names': NAMES,
        'sha256': hashlib.sha256(raw).hexdigest(),
        'notes': ['Census INTPTLON/INTPTLAT are internal points, not surveyed city-center landmarks.',
                  'Communities in GNIS_ONLY have no matching Census place and use GNIS official populated-place locations in NAD83.',
                  'Points are for geographic orientation; no municipal or oil-field boundaries are implied.']}
    PROVENANCE.write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
    update_metadata(provenance, sources)
    print(f'Wrote {len(features)} places to {len(TARGETS)} viewers; provenance in {PROVENANCE.relative_to(REPO)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
