"""Explicit local FracFocus import. Web requests never import or modify data.

Scan the complete disclosure CSV before deciding which North Dakota records are
safe to show. Original field values and row hashes stay in a private SQLite
sidecar; no ingredient-derived volumes, proppant estimates or event totals.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid

import wells_backend

APP = 'bakken-local-fracfocus'
VERSION = 1
APPLICATION_ID = 0x424B4646
DEFAULT_DB = Path(__file__).parent / 'data/fracfocus.sqlite'
SOURCE_URL = 'https://www.fracfocus.org/data-download'
FIELDS = ('DisclosureId','JobStartDate','JobEndDate','APINumber','StateName',
          'CountyName','OperatorName','WellName','Latitude','Longitude',
          'Projection','TVD','TotalBaseWaterVolume','TotalBaseNonWaterVolume',
          'FFVersion','FederalWell','IndianWell')


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def parse_water(raw):
    """A reported zero is valid; blanks and invalid numbers remain unknown."""
    raw = raw.strip()
    if not raw:
        return None, 'missing'
    if not re.fullmatch(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)', raw):
        return None, 'invalid'
    try:
        number = Decimal(raw)
        if not number.is_finite() or number < 0 or number > Decimal('1e15'):
            return None, 'invalid'
        return int(number) if number == number.to_integral_value() else float(number), 'reported'
    except (InvalidOperation, OverflowError):
        return None, 'invalid'


def parse_date(raw):
    raw = raw.strip()
    if not raw:
        return None, 'missing'
    for format_ in ('%m/%d/%Y %I:%M:%S %p', '%m/%d/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(raw, format_).date().isoformat(), 'reported'
        except ValueError:
            pass
    return None, 'invalid'


def strict_api(raw):
    value = raw.strip()
    return value if re.fullmatch(r'33[0-9]{12}', value) else None


def disclosure_key(raw):
    value = raw.strip()
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None


def schema(connection):
    connection.executescript('''
    CREATE TABLE ff_metadata(id INTEGER PRIMARY KEY CHECK(id=1),app_name TEXT NOT NULL,schema_version INTEGER NOT NULL,payload TEXT NOT NULL);
    CREATE TABLE ff_bindings(file_number TEXT PRIMARY KEY,api TEXT);
    CREATE TABLE ff_evidence(evidence_id INTEGER PRIMARY KEY,disclosure_key TEXT,api TEXT,first_source_row INTEGER NOT NULL,last_source_row INTEGER NOT NULL,occurrences INTEGER NOT NULL,raw_sha256 TEXT NOT NULL,raw_json TEXT NOT NULL,disposition TEXT NOT NULL,reason TEXT);
    CREATE INDEX ff_evidence_api ON ff_evidence(api,disposition);
    CREATE TABLE ff_events(disclosure_id TEXT PRIMARY KEY,api TEXT NOT NULL,api10 TEXT NOT NULL,job_start_date TEXT,job_end_date TEXT,water_gallons NUMERIC,water_status TEXT NOT NULL CHECK(water_status IN ('reported','missing','invalid')),evidence_id INTEGER NOT NULL REFERENCES ff_evidence(evidence_id),payload TEXT NOT NULL);
    CREATE INDEX ff_events_api ON ff_events(api,job_end_date,disclosure_id);
    CREATE INDEX ff_events_api10 ON ff_events(api10);
    CREATE TEMP TABLE incoming(disclosure_key TEXT NOT NULL,valid_id INTEGER NOT NULL,api TEXT,is_nd INTEGER NOT NULL,first_source_row INTEGER NOT NULL,last_source_row INTEGER NOT NULL,occurrences INTEGER NOT NULL,raw_sha256 TEXT NOT NULL,raw_json TEXT NOT NULL,PRIMARY KEY(disclosure_key,raw_sha256));
    CREATE INDEX incoming_nd ON incoming(is_nd);
    ''')
    connection.execute(f'PRAGMA application_id={APPLICATION_ID}')


def well_bindings():
    # This command is specifically for a local prototype, never a remote import.
    if os.environ.get('DATABASE_URL', '').strip():
        raise ValueError('Use the local well snapshot when preparing FracFocus.')
    with wells_backend.connect() as (db, release, _):
        rows = db.execute('SELECT file_number,api FROM well_registry WHERE release_id=? ORDER BY file_number', (release['release_id'],)).fetchall()
        bindings = [(row['file_number'], row['api']) for row in rows]
        if not bindings:
            raise ValueError('The validated well release has no identities.')
        return release['release_id'], release['manifest_sha256'], bindings


def prepare(source, target=DEFAULT_DB, dictionary=None):
    source = Path(source).resolve()
    dictionary = Path(dictionary).resolve() if dictionary else source.parent / 'readme csv.txt'
    if not source.is_file() or not dictionary.is_file():
        raise ValueError('Both the disclosure CSV and its data dictionary are required.')
    fingerprint, dictionary_sha = sha_file(source), sha_file(dictionary)
    rid, manifest_sha, bindings = well_bindings()
    identity_sha = hashlib.sha256(dump(bindings).encode('utf-8')).hexdigest()
    target_input = Path(target).expanduser()
    if target_input.is_symlink():
        raise ValueError('The local sidecar must not be a symlink.')
    target = target_input.resolve()
    if target == source or target == dictionary:
        raise ValueError('The output must be separate from source files.')
    if target.exists():
        with closing(sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)) as previous:
            if previous.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                raise ValueError('Refusing to replace an unrelated database.')
            marker = previous.execute('SELECT app_name,schema_version FROM ff_metadata WHERE id=1').fetchone()
            if tuple(marker or ()) != (APP, VERSION):
                raise ValueError('Refusing to replace an unknown FracFocus schema.')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.fracfocus-', suffix='.sqlite', dir=target.parent)
    os.close(fd)
    connection = None
    try:
        connection = sqlite3.connect(temporary)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        schema(connection)
        connection.execute('BEGIN')
        total_rows = 0
        with source.open('r', encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != list(FIELDS):
                raise ValueError('The disclosure CSV schema differs from the reviewed dictionary.')
            for row_number, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError('The disclosure CSV contains an incomplete row.')
                total_rows += 1
                raw_json = dump(row)
                raw_sha = hashlib.sha256(raw_json.encode('utf-8')).hexdigest()
                key = disclosure_key(row['DisclosureId'])
                api = strict_api(row['APINumber'])
                nd = row['APINumber'].strip().startswith('33') or row['StateName'].strip().casefold() == 'north dakota'
                # Invalid IDs still retain separate evidence and can never join.
                storage_key = key or 'invalid:' + row['DisclosureId'].strip()
                connection.execute('INSERT INTO incoming VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(disclosure_key,raw_sha256) DO UPDATE SET occurrences=occurrences+1,last_source_row=excluded.last_source_row',
                    (storage_key, int(key is not None), api, int(nd), row_number, row_number, 1, raw_sha, raw_json))
        if not total_rows:
            raise ValueError('Refusing an empty disclosure file.')
        rows = connection.execute('SELECT i.*, (SELECT COUNT(*) FROM incoming other WHERE other.disclosure_key=i.disclosure_key) AS variants FROM incoming i WHERE i.disclosure_key IN (SELECT disclosure_key FROM incoming WHERE is_nd=1) ORDER BY first_source_row').fetchall()
        counts = {'source_rows': total_rows, 'nd_evidence_records': len(rows), 'accepted_disclosures': 0,
                  'quarantined_records': 0, 'exact_duplicate_rows_collapsed': 0, 'conflicting_disclosure_ids': 0}
        conflicts = set()
        latest_end = None
        for item in rows:
            raw = json.loads(item['raw_json'])
            reasons = []
            if item['variants'] > 1:
                reasons.append('Conflicting rows share this DisclosureId; every variant is quarantined.')
                conflicts.add(item['disclosure_key'])
            if not item['valid_id']:
                reasons.append('Missing or invalid DisclosureId.')
            if not item['api']:
                reasons.append('A complete North Dakota API14 is required; no API suffix was inferred.')
            if raw['StateName'].strip() and raw['StateName'].strip().casefold() != 'north dakota':
                reasons.append('State name disagrees with North Dakota identity.')
            counts['exact_duplicate_rows_collapsed'] += item['occurrences'] - 1
            disposition = 'quarantined' if reasons else 'accepted'
            cursor = connection.execute('INSERT INTO ff_evidence(disclosure_key,api,first_source_row,last_source_row,occurrences,raw_sha256,raw_json,disposition,reason) VALUES(?,?,?,?,?,?,?,?,?)',
                (item['disclosure_key'], item['api'], item['first_source_row'], item['last_source_row'], item['occurrences'], item['raw_sha256'], item['raw_json'], disposition, ' '.join(reasons) or None))
            if reasons:
                counts['quarantined_records'] += 1
                continue
            start, start_status = parse_date(raw['JobStartDate'])
            end, end_status = parse_date(raw['JobEndDate'])
            water, water_status = parse_water(raw['TotalBaseWaterVolume'])
            notes = []
            if start_status != 'reported': notes.append('Job start date is ' + start_status + '.')
            if end_status != 'reported': notes.append('Job end date is ' + end_status + '.')
            if start and end and start > end:
                notes.append('Job start follows job end; both dates require review.')
                start = end = None
            if water_status != 'reported': notes.append('Reported treatment-water volume is ' + water_status + '; it is not zero.')
            if item['occurrences'] > 1: notes.append('Identical source rows were collapsed to one disclosure.')
            if not raw['StateName'].strip(): notes.append('State name missing; North Dakota is identified by the complete API.')
            event = {'disclosure_id': raw['DisclosureId'], 'api': item['api'], 'job_start_date': start,
                'job_end_date': end, 'operator_name': raw['OperatorName'].strip() or None,
                'well_name': raw['WellName'].strip() or None, 'water_gallons': water, 'water_status': water_status,
                'quality_notes': notes, 'raw_job_start_date': raw['JobStartDate'], 'raw_job_end_date': raw['JobEndDate'],
                'raw_water_gallons': raw['TotalBaseWaterVolume'], 'raw_record_sha256': item['raw_sha256'],
                'first_source_row': item['first_source_row'], 'source_occurrences': item['occurrences']}
            connection.execute('INSERT INTO ff_events VALUES(?,?,?,?,?,?,?,?,?)',
                (item['disclosure_key'], item['api'], item['api'][:10], start, end, water, water_status, cursor.lastrowid, dump(event)))
            counts['accepted_disclosures'] += 1
            if end and (latest_end is None or end > latest_end): latest_end = end
        # Same API/dates never establishes that two disclosures are one job.
        duplicate_groups = connection.execute('SELECT api,job_start_date,job_end_date,COUNT(*) AS n FROM ff_events GROUP BY api,job_start_date,job_end_date HAVING COUNT(*)>1').fetchall()
        possible_count = 0
        for group in duplicate_groups:
            records = connection.execute('SELECT disclosure_id,payload FROM ff_events WHERE api=? AND job_start_date IS ? AND job_end_date IS ?', (group['api'], group['job_start_date'], group['job_end_date'])).fetchall()
            for record in records:
                payload = json.loads(record['payload'])
                payload['quality_notes'].append('Multiple DisclosureIds share this API and date range; possible duplicate or separate treatment, retained for review.')
                connection.execute('UPDATE ff_events SET payload=? WHERE disclosure_id=?', (dump(payload), record['disclosure_id']))
                possible_count += 1
        counts.update({'conflicting_disclosure_ids': len(conflicts), 'possible_duplicate_groups': len(duplicate_groups),
                       'possible_duplicate_disclosures': possible_count,
                       'distinct_apis': connection.execute('SELECT COUNT(DISTINCT api) FROM ff_events').fetchone()[0]})
        snapshot_id = 'ff-' + hashlib.sha256(dump({'schema': VERSION, 'source': fingerprint, 'dictionary': dictionary_sha,
            'release': rid, 'manifest': manifest_sha, 'bindings': identity_sha}).encode()).hexdigest()[:24]
        metadata = {'snapshot_id': snapshot_id, 'release_id': rid, 'well_manifest_sha256': manifest_sha,
            'well_bindings_sha256': identity_sha, 'source_name': 'FracFocus', 'source_file': source.name,
            'source_sha256': fingerprint, 'dictionary_file': dictionary.name, 'dictionary_sha256': dictionary_sha,
            'prepared_at': datetime.now(timezone.utc).isoformat(), 'latest_job_end': latest_end,
            'source_url': SOURCE_URL, 'counts': counts,
            'note': 'User-supplied local snapshot, not a live feed. Exact API14 disclosure matches only. Each record is a disclosure, not a verified unique completed interval; water is reported carrier-fluid gallons, not produced water. Missing disclosures do not establish no treatment. No totals across disclosures.'}
        connection.executemany('INSERT INTO ff_bindings VALUES(?,?)', bindings)
        connection.execute('INSERT INTO ff_metadata VALUES(1,?,?,?)', (APP, VERSION, dump(metadata)))
        if sha_file(source) != fingerprint or sha_file(dictionary) != dictionary_sha:
            raise ValueError('Source changed during import; existing sidecar retained.')
        if well_bindings() != (rid, manifest_sha, bindings):
            raise ValueError('Well identities changed during import; existing sidecar retained.')
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Invalid disclosure evidence relationship.')
        connection.commit()
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('The prepared sidecar failed integrity validation.')
        connection.close(); connection = None
        os.replace(temporary, target)
        return metadata
    finally:
        if connection is not None: connection.close()
        if Path(temporary).exists(): Path(temporary).unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--dictionary', type=Path)
    parser.add_argument('--output', type=Path, default=DEFAULT_DB)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, args.dictionary), indent=2))
