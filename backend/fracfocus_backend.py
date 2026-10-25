"""Bounded local-only FracFocus route, registered exclusively in serve.py."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3

from backend import InvalidInput, Unavailable, _error
import wells_backend
from fracfocus_store import APP, VERSION, APPLICATION_ID, DEFAULT_DB


@contextmanager
def connect():
    connection = None
    try:
        path = Path(os.environ.get('BAKKEN_FRACFOCUS_DB_PATH', str(DEFAULT_DB))).expanduser().resolve()
        connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        if connection.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
            raise Unavailable()
        marker = connection.execute('SELECT app_name,schema_version,payload FROM ff_metadata WHERE id=1').fetchone()
        if not marker or (marker['app_name'], marker['schema_version']) != (APP, VERSION):
            raise Unavailable()
        metadata = json.loads(marker['payload'])
        for field in ('source_sha256', 'well_manifest_sha256', 'well_bindings_sha256', 'dictionary_sha256'):
            if not re.fullmatch(r'[a-f0-9]{64}', metadata.get(field, '')):
                raise Unavailable()
        if not re.fullmatch(r'ff-[a-f0-9]{24}', metadata.get('snapshot_id', '')):
            raise Unavailable()
        accepted = metadata.get('counts', {}).get('accepted_disclosures')
        if type(accepted) is not int or accepted < 0 or connection.execute('SELECT COUNT(*) FROM ff_events').fetchone()[0] != accepted:
            raise Unavailable()
        yield connection, metadata
    finally:
        if connection is not None: connection.close()


def handle_api(path, query=None):
    try:
        if not isinstance(path, str) or (query is not None and not isinstance(query, dict)):
            raise InvalidInput('Invalid request.')
        match = re.fullmatch(r'/api/wells/([1-9][0-9]{0,8})/fracfocus', path)
        if not match: return _error(404, 'not_found', 'Local completion endpoint not found.')
        if query: raise InvalidInput('This endpoint does not accept query parameters.')
        if os.environ.get('DATABASE_URL', '').strip():
            return _error(503, 'fracfocus_local_only', 'The FracFocus preview requires the local well snapshot. No remote database was queried.')
        file_number = match.group(1)
        with wells_backend.connect() as (wells, release, _):
            row = wells.execute('SELECT file_number,api FROM well_registry WHERE release_id=? AND file_number=?', (release['release_id'], file_number)).fetchone()
            if not row: return _error(404, 'not_found', 'This well is not present in the selected source release.')
            api = row['api']
            with connect() as (db, metadata):
                if metadata['release_id'] != release['release_id'] or metadata['well_manifest_sha256'] != release['manifest_sha256']:
                    return _error(503, 'fracfocus_release_mismatch', 'The local FracFocus snapshot belongs to a different well release. Rebuild the local snapshot before comparing it; coverage is unknown.')
                binding = db.execute('SELECT api FROM ff_bindings WHERE file_number=?', (file_number,)).fetchone()
                if not binding or binding['api'] != api:
                    return _error(503, 'fracfocus_identity_mismatch', 'The well identity differs from the prepared FracFocus snapshot. No disclosure was assigned; coverage is unknown.')
                total = suffix_count = quarantined = 0
                events = []
                valid_api = isinstance(api, str) and re.fullmatch(r'33[0-9]{12}', api)
                if valid_api:
                    total = db.execute('SELECT COUNT(*) FROM ff_events WHERE api=?', (api,)).fetchone()[0]
                    suffix_count = db.execute('SELECT COUNT(*) FROM ff_events WHERE api10=? AND api<>?', (api[:10], api)).fetchone()[0]
                    quarantined = db.execute("SELECT COUNT(*) FROM ff_evidence WHERE api=? AND disposition='quarantined'", (api,)).fetchone()[0]
                    events = [json.loads(event['payload']) for event in db.execute('SELECT payload FROM ff_events WHERE api=? ORDER BY job_end_date IS NULL,job_end_date DESC,job_start_date DESC,disclosure_id LIMIT 200', (api,)).fetchall()]
                status = 'review_required' if quarantined or not valid_api else 'matched' if total else 'review_required' if suffix_count else 'no_disclosure'
                notes = ['Only exact full API14 matches are displayed; absence is not proof of no treatment.']
                if suffix_count: notes.append(f'{suffix_count} disclosure(s) share the API10 prefix but have a different branch/completion suffix; excluded pending identity review.')
                if quarantined: notes.append(f'{quarantined} conflicting or invalid source record(s) for this API were quarantined and excluded.')
                if not valid_api: notes.append('This well lacks a valid full North Dakota API14; no disclosure match was inferred.')
                provenance = {key: metadata[key] for key in ('release_id','snapshot_id','source_name','source_file','source_sha256','prepared_at','latest_job_end','source_url','note')}
                provenance['dictionary_sha256'] = metadata['dictionary_sha256']
                return 200, {'well': {'file_number': file_number, 'api': api}, 'provenance': provenance,
                    'coverage': {'status': status, 'total': total, 'returned': len(events), 'truncated': total > 200,
                        'api10_review_count': suffix_count, 'quarantined_count': quarantined, 'note': ' '.join(notes)},
                    'events': events}
    except InvalidInput as exc:
        return _error(400, 'invalid_request', str(exc))
    except Exception:
        return _error(503, 'fracfocus_unavailable', 'The validated local FracFocus snapshot is unavailable. Treatment coverage is unknown, not zero.')
