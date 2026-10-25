"""Prepare optional, hash-bound well-name metadata without changing a survey.

Usage: python prepare_well_names.py OGD_Wells.dbf DATASET_DIR --source-date YYYY-MM-DD
Uses Python's standard library. Only well-names.json is written. Names describe
the supplied Wells snapshot; they are not historical well-name observations.
"""
import argparse
import codecs
from collections import Counter, defaultdict
from datetime import date
import hashlib
import json
import math
import mmap
from pathlib import Path
import re
import struct


SOURCE_URL = 'https://gis.dmr.nd.gov/downloads/oilgas/shapefile/OGD_Wells.zip'


def normalized_permit(value):
    text = str(value if value is not None else '').strip()
    if not re.fullmatch(r'\d+(?:\.0+)?', text):
        return ''
    number = int(text.split('.')[0])
    return str(number) if number > 0 else ''


def normalized_api(value):
    text = str(value if value is not None else '').strip()
    if not re.fullmatch(r'[\d\s-]+', text):
        return ''
    digits = re.sub(r'\D', '', text)
    return digits if len(digits) in (10, 12, 14) else ''


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def source_encoding(path, override=None):
    if override:
        return codecs.lookup(override).name, 'explicit'
    cpg = Path(path).with_suffix('.cpg')
    if cpg.is_file():
        value = cpg.read_text(encoding='utf-8-sig').strip()
        value = {'65001': 'utf-8', '1252': 'cp1252'}.get(value, value)
        return codecs.lookup(value).name, 'CPG'
    return 'cp1252', 'default (CPG absent)'


def read_wells(path, encoding=None):
    """Read only fileno/api/well_name; skip deleted rows; never write the DBF."""
    path = Path(path)
    codec, codec_source = source_encoding(path, encoding)
    records, audit = [], Counter()
    with path.open('rb') as stream:
        header = stream.read(32)
        if len(header) != 32:
            raise ValueError('Truncated DBF header')
        count = struct.unpack_from('<I', header, 4)[0]
        start, step = struct.unpack_from('<HH', header, 8)
        if start < 33 or step < 2:
            raise ValueError('Invalid DBF header/record length')
        fields, offset, terminated = {}, 1, False
        while stream.tell() < start:
            first = stream.read(1)
            if first == b'\r':
                terminated = True
                break
            descriptor = first + stream.read(31)
            if len(descriptor) != 32:
                raise ValueError('Truncated DBF field descriptor')
            name = descriptor[:11].split(b'\0')[0].decode('ascii').lower()
            length = descriptor[16]
            if name in fields or not name or not length:
                raise ValueError('Duplicate or invalid DBF field')
            fields[name] = (offset, length)
            offset += length
        if not terminated or offset != step or start + count * step > path.stat().st_size:
            raise ValueError('Unsupported or truncated DBF record layout')
        for name in ('fileno', 'api', 'well_name'):
            if name not in fields:
                raise ValueError('Missing required DBF field: ' + name)
        audit['sourceRecords'] = count
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            def value(pos, name):
                field_offset, length = fields[name]
                return mapped[pos + field_offset:pos + field_offset + length].decode(codec).strip(' \0')
            for index in range(count):
                pos = start + index * step
                marker = mapped[pos:pos + 1]
                if marker == b'*':
                    audit['deletedSourceRecords'] += 1
                    continue
                if marker != b' ':
                    raise ValueError('Invalid DBF deletion flag')
                audit['activeSourceRecords'] += 1
                permit = normalized_permit(value(pos, 'fileno'))
                api = normalized_api(value(pos, 'api'))
                name = value(pos, 'well_name')
                if any(ord(c) < 32 or ord(c) == 127 for c in name):
                    name = ''
                    audit['invalidSourceNames'] += 1
                if not permit:
                    audit['invalidSourcePermits'] += 1
                    continue
                if not api:
                    audit['invalidSourceAPIs'] += 1
                if not name:
                    audit['blankSourceNames'] += 1
                records.append({'permit': permit, 'api': api, 'name': name})
    return records, dict(audit), codec, codec_source


def resolve_name(branch, by_permit):
    """Exact API14 first; API10 only with one nonblank unambiguous base name."""
    permit = normalized_permit(branch.get('permit'))
    api = normalized_api(branch.get('api'))
    if not permit:
        return '', 'invalidPermit'
    if not api:
        return '', 'invalidAPI'
    rows = by_permit.get(permit, [])
    if not rows:
        return '', 'permitAbsent'
    exact = [row for row in rows if len(api) == 14 and row['api'] == api]
    if exact:
        names = {row['name'] for row in exact}
        if len(names) != 1:
            return '', 'conflictingExactNames'
        name = next(iter(names))
        return (name, 'matchedExactAPI14') if name else ('', 'nameAbsent')
    base = [row for row in rows if row['api'] and row['api'][:10] == api[:10]]
    if not base:
        return '', 'apiMismatch' if any(row['api'] for row in rows) else 'sourceAPIAbsent'
    names = {row['name'] for row in base}
    if len(names) != 1:
        return '', 'conflictingBaseNames'
    name = next(iter(names))
    return (name, 'matchedBaseAPI10') if name else ('', 'nameAbsent')


def build_sidecar(manifest, records, manifest_sha256, provenance, source_audit=None):
    if not re.fullmatch(r'[a-f0-9]{64}', manifest_sha256):
        raise ValueError('A valid manifest SHA-256 is required')
    wells = manifest.get('wells')
    if not isinstance(wells, list):
        raise ValueError('Manifest wells must be a list')
    ids = [well.get('id') for well in wells]
    if any(type(value) is not int or value < 0 for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Manifest branch IDs must be unique nonnegative integers')
    origin = manifest.get('origin')
    if not isinstance(origin, list) or len(origin) != 2 or any(type(n) not in (int, float) or not math.isfinite(n) for n in origin):
        raise ValueError('Manifest must declare a finite geographic origin')
    if type(manifest.get('stations')) is not int or manifest['stations'] < 0 or not manifest.get('sourceCRS'):
        raise ValueError('Manifest survey metadata is incomplete')
    by_permit = defaultdict(list)
    for row in records:
        by_permit[row['permit']].append(row)
    names, reasons, matched_identities, identities = {}, Counter(), set(), set()
    for well in wells:
        identity = (normalized_permit(well.get('permit')), normalized_api(well.get('api'))[:10])
        identities.add(identity)
        name, reason = resolve_name(well, by_permit)
        reasons[reason] += 1
        if name:
            names[str(well['id'])] = name
            matched_identities.add(identity)
    matched = len(names)
    return {
        'version': 1,
        'survey': {'manifestSHA256': manifest_sha256, 'branchCount': len(wells),
                   'stations': manifest['stations'], 'sourceCRS': manifest['sourceCRS'],
                   'origin': origin, 'sourceDate': manifest.get('sourceSnapshot', {}).get('date')},
        'source': provenance,
        'names': names,
        'coverage': {'matchedBranches': matched, 'missingBranches': len(wells) - matched,
                     'matchedWellIdentities': len(matched_identities),
                     'datasetWellIdentities': len(identities),
                     'distinctNames': len(set(names.values())),
                     'byReason': dict(sorted(reasons.items())), 'sourceRecords': source_audit or {}},
        'notes': [
            'Names retain the Wells DBF well_name text, excluding field padding; absent entries are unavailable, not unnamed wells.',
            'Join uses normalized permit plus exact API14 first; base API10 is allowed only when all matching source candidates have one identical nonblank name. No permit-only or spatial fallback is used.',
            'names keys are manifest branch IDs, not array positions. The exact manifestSHA256 must match before using this optional metadata.',
            'Names describe the dated Wells snapshot, not historical name changes or ownership. Geometry, production, metrics and original manifest are unchanged.',
        ],
    }


def prepare(wells_dbf, dataset_dir, source_date, output=None, encoding=None, expected_manifest_sha256=None):
    wells_dbf, dataset_dir = Path(wells_dbf), Path(dataset_dir)
    manifest_path = dataset_dir / 'manifest.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    if expected_manifest_sha256 and manifest_hash != expected_manifest_sha256:
        raise ValueError('Manifest SHA-256 does not match the expected snapshot')
    manifest = json.loads(manifest_bytes)
    source_hash = sha256(wells_dbf)
    records, source_audit, codec, codec_source = read_wells(wells_dbf, encoding)
    provenance = {'sourceURL': SOURCE_URL, 'sourceDate': source_date.isoformat(),
                  'dbfSHA256': source_hash, 'nameField': 'well_name', 'permitField': 'fileno',
                  'apiField': 'api', 'encoding': codec, 'encodingSource': codec_source}
    result = build_sidecar(manifest, records, manifest_hash, provenance, source_audit)
    out = Path(output) if output is not None else dataset_dir / 'well-names.json'
    if out.name != 'well-names.json':
        raise ValueError('Output must be named well-names.json to protect existing dataset files')
    if out.resolve() in (manifest_path.resolve(), wells_dbf.resolve()):
        raise ValueError('Output cannot replace source data')
    if sha256(manifest_path) != manifest_hash or sha256(wells_dbf) != source_hash:
        raise ValueError('Source changed during preparation; rerun against a stable snapshot')
    payload = json.dumps(result, separators=(',', ':'), ensure_ascii=False).encode('utf8')
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name('.well-names.json.tmp')
    try:
        temporary.write_bytes(payload)
        temporary.replace(out)
    finally:
        temporary.unlink(missing_ok=True)
    return result, out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wells_dbf', type=Path)
    parser.add_argument('dataset_dir', type=Path)
    parser.add_argument('--source-date', required=True, type=date.fromisoformat)
    parser.add_argument('--out', type=Path, help='Optional path ending in well-names.json')
    parser.add_argument('--encoding', help='Override CPG; default cp1252 only when CPG is absent')
    parser.add_argument('--expected-manifest-sha256', help='Optional exact snapshot guard')
    args = parser.parse_args()
    result, out = prepare(args.wells_dbf, args.dataset_dir, args.source_date, args.out,
                          args.encoding, args.expected_manifest_sha256)
    print(json.dumps({'output': str(out), 'bytes': out.stat().st_size,
                      'manifestSHA256': result['survey']['manifestSHA256'],
                      **result['coverage']}, indent=2))


if __name__ == '__main__':
    main()
