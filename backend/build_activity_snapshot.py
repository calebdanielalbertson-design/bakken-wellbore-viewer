"""Prepare a local 3D activity snapshot; never writes either source database.

Dates apply to well identities, not dated survey branches. Treatment water is
assigned once to the job-end month and is unknown for ambiguous disclosures.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile

import fracfocus_backend
import wells_backend
from fracfocus_store import dump, sha_file

ROOT = Path(__file__).resolve().parent
DEFAULT_MANIFEST = ROOT.parents[1] / 'outputs/wellbore-viewer/full-dataset/manifest.json'
DEFAULT_OUTPUT = ROOT / 'data/activity-snapshot.json'
VERSION = 1


def iso_date(value):
    if value is None or value == '': return None
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): return None
    try: return date.fromisoformat(value).isoformat()
    except ValueError: return None


def month_range(values):
    values = sorted(value for value in values if value)
    return {'first': values[0] if values else None, 'last': values[-1] if values else None}


def monthly_events(events):
    """Do not silently drop unknown/conflicting volumes from a monthly sum."""
    grouped = defaultdict(list)
    for event in events:
        if event['month']: grouped[event['month']].append(event)
    result = []
    for month, group in sorted(grouped.items()):
        if any(event['review_required'] for event in group): status = 'review_required'
        elif any(event['water_status'] == 'invalid' for event in group): status = 'invalid'
        elif any(event['water_status'] == 'missing' for event in group): status = 'missing'
        else: status = 'reported'
        volume = sum(event['water_gallons'] for event in group) if status == 'reported' else None
        result.append({'month': month, 'event_count': len(group), 'water_gallons': volume,
                       'water_status': status})
    return result


def build(manifest_path=DEFAULT_MANIFEST):
    if os.environ.get('DATABASE_URL', '').strip():
        raise ValueError('Activity preparation requires the local well snapshot; no remote database was queried.')
    manifest_path = Path(manifest_path).resolve()
    raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(raw).hexdigest()
    manifest = json.loads(raw)
    if not isinstance(manifest.get('wells'), list) or not manifest['wells']:
        raise ValueError('A complete survey manifest with displayed well identities is required.')
    identities = Counter()
    invalid_geometry_rows = 0
    for branch in manifest['wells']:
        permit, api = str(branch.get('permit', '')), branch.get('api')
        if not re.fullmatch(r'[1-9][0-9]{0,8}', permit) or not isinstance(api, str) or not re.fullmatch(r'33[0-9]{12}', api):
            invalid_geometry_rows += 1
            continue
        identities[(permit, api)] += 1
    with wells_backend.connect() as (db, release, well_metadata), fracfocus_backend.connect() as (ff, ff_metadata):
        rid = release['release_id']
        expected_survey_sha = well_metadata.get('survey', {}).get('manifest_sha256')
        if expected_survey_sha != manifest_sha:
            raise ValueError('Survey geometry does not match the validated well release.')
        if ff_metadata['release_id'] != rid or ff_metadata['well_manifest_sha256'] != release['manifest_sha256']:
            raise ValueError('FracFocus and well identities belong to different releases.')
        registry = {row['file_number']: dict(row) for row in db.execute('SELECT file_number,api,payload FROM well_registry WHERE release_id=?', (rid,)).fetchall()}
        bindings = {row['file_number']: row['api'] for row in ff.execute('SELECT file_number,api FROM ff_bindings').fetchall()}
        events_by_api = defaultdict(list)
        all_events = ff.execute('SELECT disclosure_id,api,job_start_date,job_end_date,water_gallons,water_status,payload FROM ff_events ORDER BY api,job_end_date,disclosure_id').fetchall()
        duplicate_keys = Counter((row['api'], row['job_start_date'], row['job_end_date']) for row in all_events)
        for event in all_events: events_by_api[event['api']].append(event)
        quarantine = dict(ff.execute("SELECT api,COUNT(*) FROM ff_evidence WHERE api IS NOT NULL AND disposition='quarantined' GROUP BY api").fetchall())
        snapshot_date = iso_date(well_metadata.get('source_date'))
        disclosure_prepared_date = iso_date(ff_metadata.get('prepared_at', '')[:10])
        counts = Counter({'manifest_branch_rows': len(manifest['wells']), 'unique_geometry_identities': len(identities),
            'invalid_geometry_identity_rows': invalid_geometry_rows, 'matched_wells': 0, 'unmatched_geometry_identities': 0,
            'spud_reported': 0, 'spud_missing': 0, 'spud_invalid': 0, 'spud_review_required': 0,
            'wells_with_disclosures': 0, 'disclosure_events': 0, 'events_with_end_month': 0,
            'events_without_end_month': 0, 'events_review_required': 0, 'possible_duplicate_disclosures': 0,
            'spud_after_job_end': 0, 'water_missing': 0, 'water_invalid': 0, 'water_reported_zero': 0,
            'quarantined_records_for_displayed_wells': 0})
        wells = []
        exclusions = []
        for (permit, api), branch_count in sorted(identities.items(), key=lambda item: (int(item[0][0]), item[0][1])):
            registered = registry.get(permit)
            if not registered or registered['api'] != api:
                counts['unmatched_geometry_identities'] += 1
                exclusions.append({'permit': permit, 'api': api, 'reason': 'No exact file-number/API14 match in the validated well registry.'})
                continue
            if permit not in bindings or bindings[permit] != api:
                raise ValueError('The FracFocus snapshot no longer matches a displayed well identity.')
            source_well = wells_backend.unpack(registered['payload'])
            raw_spud = source_well.get('spud_date')
            spud = iso_date(raw_spud)
            spud_status = 'reported' if spud else 'missing' if raw_spud in (None, '') else 'invalid'
            notes = []
            if spud and snapshot_date and spud > snapshot_date:
                spud = None; spud_status = 'review_required'
                notes.append('Reported spud date follows the GIS source snapshot; withheld from activity timing.')
            events = []
            timing_conflict = False
            for row in events_by_api.get(api, []):
                payload = json.loads(row['payload'])
                start, end = iso_date(row['job_start_date']), iso_date(row['job_end_date'])
                reasons = []
                duplicate = duplicate_keys[(api, row['job_start_date'], row['job_end_date'])] > 1
                if duplicate:
                    reasons.append('possible_duplicate_disclosure')
                    counts['possible_duplicate_disclosures'] += 1
                month = end[:7] if end else None
                if not end: reasons.append('missing_or_invalid_job_end')
                if end and disclosure_prepared_date and end > disclosure_prepared_date:
                    reasons.append('future_job_end'); month = None
                original_spud = iso_date(raw_spud)
                if end and original_spud and original_spud > end:
                    reasons.append('spud_after_job_end')
                    month = None; timing_conflict = True
                    counts['spud_after_job_end'] += 1
                if start and end and start > end:
                    reasons.append('job_date_order'); month = None
                water, status = row['water_gallons'], row['water_status']
                if status not in {'reported', 'missing', 'invalid'} or (status == 'reported' and (not isinstance(water, (int, float)) or not math.isfinite(water) or water < 0)):
                    raise ValueError('Invalid prepared treatment-water value.')
                if status in {'missing', 'invalid'}: counts['water_' + status] += 1
                if status == 'reported' and water == 0: counts['water_reported_zero'] += 1
                event = {'id': payload['disclosure_id'], 'start': start, 'end': end, 'month': month,
                    'water_gallons': water, 'water_status': status, 'review_required': bool(reasons), 'review_reasons': reasons}
                events.append(event)
                counts['events_with_end_month' if month else 'events_without_end_month'] += 1
                counts['events_review_required'] += int(bool(reasons))
            if timing_conflict:
                spud = None; spud_status = 'review_required'
                notes.append('Reported spud date follows at least one disclosure end date; conflicting spud and disclosure timing withheld pending review.')
            n_quarantined = quarantine.get(api, 0)
            if n_quarantined:
                notes.append(f'{n_quarantined} invalid or conflicting source record(s) excluded from the prepared disclosure snapshot.')
                counts['quarantined_records_for_displayed_wells'] += n_quarantined
            record = {'permit': permit, 'api': api, 'branch_count': branch_count, 'spud_date': spud,
                'spud_status': spud_status, 'review_notes': notes, 'events': events, 'monthly': monthly_events(events)}
            if spud_status in {'review_required', 'invalid'}: record['source_spud_date'] = raw_spud
            wells.append(record)
            counts['matched_wells'] += 1
            counts['spud_' + spud_status] += 1
            counts['wells_with_disclosures'] += int(bool(events))
            counts['disclosure_events'] += len(events)
        provenance = {'well_release_id': rid, 'well_manifest_sha256': release['manifest_sha256'],
            'well_source_date': well_metadata.get('source_date'),
            'well_source_sha256': well_metadata.get('sources', {}).get('wells_dbf', {}).get('sha256'),
            'fracfocus_snapshot_id': ff_metadata['snapshot_id'],
            'fracfocus_source_file': ff_metadata['source_file'], 'fracfocus_source_sha256': ff_metadata['source_sha256'],
            'fracfocus_dictionary_sha256': ff_metadata['dictionary_sha256'],
            'fracfocus_prepared_at': ff_metadata['prepared_at'],
            'survey_manifest_sha256': manifest_sha, 'survey_manifest_file': 'outputs/wellbore-viewer/full-dataset/manifest.json',
            'prepared_at': datetime.now(timezone.utc).isoformat(), 'latest_job_end': ff_metadata['latest_job_end'],
            'latest_job_end_month': ff_metadata['latest_job_end'][:7] if ff_metadata['latest_job_end'] else None,
            'source_url': 'https://www.fracfocus.org/data-download',
            'notes': [
                'Current mapped well geometry is shown as a proxy at the reported well spud date; it is not historical as-drilled geometry or a branch-specific drilling date.',
                'Missing or inconsistent spud dates remain unknown and are never inferred from treatment dates.',
                'A disclosure is not a verified unique completed interval. API14 matches do not assign a treatment to a particular survey branch.',
                'Full-job carrier-fluid water is assigned once to the job END month; it is not a daily injection rate and is not repeated across start/end months.',
                'Possible duplicate disclosures retain separate counts; their monthly water is unavailable pending review. Any missing or invalid water makes that well-month total unknown.',
                'Well identities and disclosure counts are deduplicated across repeated survey branches. No water totals are allocated to branches, DSUs or townships.',
                'No disclosure or missing monthly records do not establish zero treatment activity. This supplied file is not a live feed.'
            ]}
    if sha_file(manifest_path) != manifest_sha:
        raise ValueError('The survey manifest changed while preparing activity.')
    return {'schema_version': VERSION, 'provenance': provenance, 'coverage': dict(counts),
        'months': {'spud': month_range(well['spud_date'][:7] for well in wells if well['spud_date']),
                   'frac': month_range(event['month'] for well in wells for event in well['events'])},
        'wells': wells, 'excluded_identities': exclusions}


def prepare(manifest_path=DEFAULT_MANIFEST, output=DEFAULT_OUTPUT):
    result = build(manifest_path)
    target_input = Path(output).expanduser()
    if target_input.is_symlink(): raise ValueError('Activity output must not be a symlink.')
    target = target_input.resolve()
    if target.suffix != '.json' or target == Path(manifest_path).resolve():
        raise ValueError('Activity output must be a separate JSON file.')
    raw = dump(result).encode('utf-8')
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.activity-', suffix='.json', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream: stream.write(raw)
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists(): Path(temporary).unlink()
    return {'output': str(target), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
            'coverage': result['coverage'], 'months': result['months'], 'provenance': result['provenance']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(prepare(args.manifest, args.output), indent=2))
