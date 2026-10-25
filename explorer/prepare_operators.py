"""Join the public ND DMR wells DBF to an existing survey dataset.

Usage: python prepare_operators.py WELLS.dbf DATASET_DIR --source-date YYYY-MM-DD
Only the operators sidecar is written; survey geometry and manifests stay untouched.
The source DBF is memory mapped read-only and no third-party packages are needed.
"""
import argparse
from collections import Counter, defaultdict
import colorsys
from datetime import date, datetime, timezone
import hashlib
import json
import mmap
from pathlib import Path
import re
import struct


SOURCE_URL = 'https://gis.dmr.nd.gov/gisdownload.asp'
UNKNOWN = ('unknown', 'Unknown', '#80909d')


def normalized_name(value):
    """Case/punctuation insensitive company tokens, with word boundaries retained."""
    return ' '.join(re.findall(r'[A-Z0-9]+', str(value).upper()))


# These are display aliases requested for the legend, not ownership assertions.
# A narrower Petro-Hunt Dakota match must precede the generic Petro-Hunt match.
ALIASES = [
    ('chord', 'Chord / Enerplus / Oasis / Whiting', '#0087ed',
     ('CHORD', 'ENERPLUS', 'OASIS', 'WHITING')),
    ('continental', 'Continental Resources', '#e6ce14', ('CONTINENTAL RESOURCES',)),
    ('burlington-marathon', 'Burlington / Marathon', '#ed0000', ('BURLINGTON', 'MARATHON')),
    ('hess-chevron', 'Hess / Chevron', '#5dca1b', ('HESS', 'CHEVRON')),
    ('devon', 'Devon Energy', '#e67a40', ('DEVON',)),
    ('kraken-neptune-zavanna', 'Kraken / Neptune / Zavanna', '#849475', ('KRAKEN', 'NEPTUNE', 'ZAVANNA')),
    ('xto', 'XTO Energy', '#ffb000', ('XTO',)),
    ('eog', 'EOG Resources', '#ff0092', ('EOG',)),
    ('petro-hunt-dakota', 'Petro-Hunt Dakota', '#04abd2', ('PETRO HUNT DAKOTA',)),
    ('petro-hunt', 'Petro-Hunt', '#04abd2', ('PETRO HUNT',)),
    ('slawson', 'Slawson', '#96968f', ('SLAWSON',)),
    ('denbury', 'Denbury', '#ea2ac3', ('DENBURY',)),
    ('lime-rock-iii-a', 'Lime Rock III-A', '#87dfa2', ('LIME ROCK RESOURCES III A', 'LIME ROCK III A')),
    ('formentera', 'Formentera', '#cd3f79', ('FORMENTERA',)),
    ('hunt-oil', 'Hunt Oil', '#2608ff', ('HUNT OIL',)),
    ('silver-hill', 'Silver Hill Energy', '#ffffff', ('SILVER HILL',)),
    ('murex', 'Murex Petroleum', '#7050de', ('MUREX',)),
    ('phoenix', 'Phoenix', '#91e7be', ('PHOENIX',)),
    ('morningstar', 'Morningstar', '#59cdd0', ('MORNINGSTAR',)),
    ('cobra', 'Cobra Oil & Gas', '#9bca78', ('COBRA',)),
    ('foundation', 'Foundation Energy', '#b35ad8', ('FOUNDATION',)),
    ('fulcrum', 'Fulcrum Energy', '#e88042', ('FULCRUM',)),
    ('sogc', 'SOGC', '#5c3dcd', ('SOGC',)),
    ('scout', 'Scout Energy', '#dfc36d', ('SCOUT',)),
    ('white-rock', 'White Rock Oil & Gas', '#d14d4d', ('WHITE ROCK',)),
]


def group_for(raw_name):
    name = normalized_name(raw_name)
    if not name:
        return UNKNOWN
    padded = ' ' + name + ' '
    for key, label, color, aliases in ALIASES:
        if any(' ' + alias + ' ' in padded for alias in aliases):
            return key, label, color
    # Keep unlisted operators separate. Use a digest rather than Python's salted
    # hash so the same name retains its color/key between runs and platforms.
    digest = hashlib.sha256(name.encode('utf8')).hexdigest()
    hue = int(digest[:8], 16) / 0xffffffff
    saturation = .66 + int(digest[8:10], 16) / 255 * .16
    lightness = .60 + int(digest[10:12], 16) / 255 * .08
    rgb = colorsys.hls_to_rgb(hue, lightness, saturation)
    color = '#' + ''.join(f'{round(v * 255):02x}' for v in rgb)
    return 'operator-' + digest[:16], raw_name, color


def normalized_permit(value):
    text = str(value or '').strip()
    # DBF fileno is an integer numeric field. Accept its harmless .0 formatting
    # but never merge punctuation or arbitrary embedded digits in identifiers.
    if not re.fullmatch(r'\d+(?:\.0+)?', text):
        return ''
    return str(int(text.split('.')[0]))


def normalized_api10(value):
    text = str(value or '').strip()
    if not text:
        return ''
    # Formatted API values can contain standard separators; reject other text.
    if not re.fullmatch(r'[\d\s-]+', text):
        return ''
    digits = re.sub(r'\D', '', text)
    return digits[:10] if len(digits) in (10, 12, 14) else ''


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read_wells(path):
    """Read only required fields through a read-only mmap of the DBF records."""
    path = Path(path)
    records = []
    audit = Counter()
    with path.open('rb') as stream:
        header = stream.read(32)
        if len(header) != 32:
            raise ValueError('Truncated DBF header')
        count = struct.unpack_from('<I', header, 4)[0]
        start, step = struct.unpack_from('<HH', header, 8)
        fields, offset = {}, 1
        while stream.tell() < start:
            first = stream.read(1)
            if first == b'\r':
                break
            descriptor = first + stream.read(31)
            if len(descriptor) != 32:
                raise ValueError('Truncated DBF field descriptor')
            name = descriptor[:11].split(b'\0')[0].decode('ascii').lower()
            length = descriptor[16]
            fields[name] = (offset, length)
            offset += length
        if offset != step or start + count * step > path.stat().st_size:
            raise ValueError('Unsupported or truncated DBF record layout')
        for field in ('fileno', 'api', 'operator'):
            if field not in fields:
                raise ValueError('Missing required DBF field: ' + field)
        audit['sourceRecords'] = count
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            def value(pos, name):
                field_offset, length = fields[name]
                return mapped[pos + field_offset:pos + field_offset + length].decode('cp1252').strip(' \x00')
            for index in range(count):
                pos = start + index * step
                if mapped[pos:pos + 1] == b'*':
                    audit['deletedSourceRecords'] += 1
                    continue
                permit = normalized_permit(value(pos, 'fileno'))
                if not permit:
                    audit['invalidSourcePermits'] += 1
                    continue
                records.append({'permit':permit, 'api':normalized_api10(value(pos, 'api')),
                                'operator':value(pos, 'operator')})
                audit['activeSourceRecords'] += 1
    return records, dict(audit)


def resolve_operator(branch, by_permit):
    permit = normalized_permit(branch.get('permit'))
    api = normalized_api10(branch.get('api'))
    if not permit:
        return '', 'invalidPermit'
    candidates = by_permit.get(permit, [])
    if not candidates:
        return '', 'permitAbsent'
    exact = [row for row in candidates if api and row['api'] == api]
    if exact:
        names = {row['operator'] for row in exact}
        if len(names) != 1:
            return '', 'ambiguousOperator'
        name = next(iter(names))
        return (name, 'matchedPermitAPI') if name else ('', 'operatorAbsent')
    # Permit fallback requires exactly one source record and an absent API on
    # one side. Two present but different API values can never use this route.
    if len(candidates) == 1 and (not api or not candidates[0]['api']):
        name = candidates[0]['operator']
        return (name, 'matchedUniquePermitMissingAPI') if name else ('', 'operatorAbsent')
    if api and any(row['api'] for row in candidates):
        return '', 'apiMismatch'
    return '', 'ambiguousPermit'


def build_sidecar(manifest, records, provenance, source_audit=None):
    by_permit = defaultdict(list)
    for row in records:
        by_permit[row['permit']].append(row)
    branch_names, branch_keys = [], []
    models = {UNKNOWN[0]:{'key':UNKNOWN[0], 'label':UNKNOWN[1], 'color':UNKNOWN[2],
                           'identities':set(), 'rawNames':set(), 'branchCount':0}}
    audit = Counter()
    for index, branch in enumerate(manifest['wells']):
        name, reason = resolve_operator(branch, by_permit)
        audit[reason] += 1
        key, label, color = group_for(name)
        item = models.setdefault(key, {'key':key, 'label':label, 'color':color,
                                      'identities':set(), 'rawNames':set(), 'branchCount':0})
        # Make labels independent of source traversal if an unlisted name has
        # several punctuation/case variants, while preserving every raw name.
        if key.startswith('operator-'):
            item['label'] = min(item['label'], name)
        permit, api = normalized_permit(branch.get('permit')), normalized_api10(branch.get('api'))
        identity = (permit, api) if permit or api else ('invalid-branch', index)
        item['identities'].add(identity)
        if name:
            item['rawNames'].add(name)
        item['branchCount'] += 1
        branch_names.append(name)
        branch_keys.append(key)
    groups = []
    for group in sorted(models.values(), key=lambda item:(-len(item['identities']), item['key'])):
        groups.append({'id':len(groups), 'key':group['key'], 'label':group['label'], 'color':group['color'],
                       'wellCount':len(group['identities']), 'branchCount':group['branchCount'],
                       'rawNames':sorted(group['rawNames'])})
    group_ids = {group['key']:group['id'] for group in groups}
    names = sorted(set(branch_names))
    name_ids = {name:index for index, name in enumerate(names)}
    branch_count = len(manifest['wells'])
    matched = audit['matchedPermitAPI'] + audit['matchedUniquePermitMissingAPI']
    stats = dict(source_audit or {})
    stats.update({'datasetBranches':branch_count, 'matchedBranches':matched,
                  'unknownBranches':branch_count-matched, 'byReason':dict(sorted(audit.items())),
                  'sourcePermitsWithMultipleRecords':sum(len(v)>1 for v in by_permit.values()),
                  'datasetUniqueWellIdentities':len({(normalized_permit(w.get('permit')), normalized_api10(w.get('api')))
                                                   for w in manifest['wells']})})
    return {
        'version':1,
        'survey':{'branchCount':branch_count, 'stations':manifest['stations'],
                  'overviewSegments':manifest['overviewSegments'], 'sourceCRS':manifest['sourceCRS'],
                  'origin':manifest['origin']},
        'groups':groups, 'names':names,
        'branchGroups':[group_ids[key] for key in branch_keys],
        'branchNames':[name_ids[name] for name in branch_names],
        'provenance':provenance, 'joinStats':stats,
        'notes':[
            'Operator names are retained exactly from the downloaded wells DBF, excluding DBF field padding.',
            'Legend aliases are display conveniences requested by the viewer owner; they do not assert legal ownership or reconstruct historical ownership.',
            'Join requires matching normalized permit and API10 (first ten API digits). Unique-record permit fallback is allowed only when an API is absent; API mismatches and ambiguous operators remain Unknown.',
            'Operator metadata describes this download, not the operator at each historical production month.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wells_dbf', type=Path)
    parser.add_argument('dataset_dir', type=Path)
    parser.add_argument('--source-date', required=True, type=date.fromisoformat)
    parser.add_argument('--out', type=Path, help='Default: DATASET_DIR/operators.json')
    parser.add_argument('--retrieved-at', help='Download time in ISO 8601; default is source file modification time UTC')
    args = parser.parse_args()
    manifest_path = args.dataset_dir / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    records, source_audit = read_wells(args.wells_dbf)
    retrieved = args.retrieved_at or datetime.fromtimestamp(args.wells_dbf.stat().st_mtime, timezone.utc).isoformat()
    provenance = {'sourceURL':SOURCE_URL, 'sourceDate':args.source_date.isoformat(), 'retrievedAt':retrieved,
                  'wellSourceFile':args.wells_dbf.name, 'wellSourceSHA256':sha256(args.wells_dbf)}
    result = build_sidecar(manifest, records, provenance, source_audit)
    output = args.out or args.dataset_dir / 'operators.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False), encoding='utf8')
    print(json.dumps({'output':str(output.resolve()), 'groups':len(result['groups']),
                      'bytes':output.stat().st_size, **result['joinStats']}, indent=2))


if __name__ == '__main__':
    main()
