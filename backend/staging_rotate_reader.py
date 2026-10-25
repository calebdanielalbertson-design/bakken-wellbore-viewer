"""One-time private staging reader rotation; no secret output."""
import base64
import hashlib
import hmac
import os
from urllib.parse import urlsplit


def rotate():
    import psycopg
    from psycopg import sql
    from import_snapshot import _reader_configuration
    password, reader = _reader_configuration()
    owner = os.environ['BAKKEN_IMPORT_DATABASE_URL']
    a, b = urlsplit(owner), urlsplit(reader)
    if (a.username != 'postgres' or a.hostname != b.hostname or a.path != b.path
            or not a.hostname.endswith('.railway.internal')
            or os.environ.get('RAILWAY_ENVIRONMENT_ID') != '78d48523-3b40-4010-8d4f-10c04d69fe23'):
        raise ValueError('Unexpected staging connection.')
    # Send a SCRAM verifier rather than plaintext in the ALTER ROLE statement.
    salt = os.urandom(16)
    salted = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 4096)
    client = hmac.digest(salted, b'Client Key', 'sha256')
    server = hmac.digest(salted, b'Server Key', 'sha256')
    enc = lambda value: base64.b64encode(value).decode()
    verifier = f'SCRAM-SHA-256$4096:{enc(salt)}${enc(hashlib.sha256(client).digest())}:{enc(server)}'
    with psycopg.connect(owner, connect_timeout=15, sslmode='require') as db:
        row = db.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname='forward_reader'").fetchone()
        if row != (False, False, False, False, False):
            raise ValueError('Reader privileges changed.')
        if db.execute("SELECT count(*) FROM pg_auth_members WHERE member='forward_reader'::regrole").fetchone()[0]:
            raise ValueError('Unexpected reader membership.')
        db.execute(sql.SQL('ALTER ROLE forward_reader PASSWORD {}').format(sql.Literal(verifier)))
    with psycopg.connect(owner, connect_timeout=15, sslmode='require', autocommit=True) as db:
        db.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename='forward_reader' AND pid<>pg_backend_pid()")
    with psycopg.connect(reader, password=password, connect_timeout=15) as db:
        if db.execute('SELECT current_user').fetchone()[0] != 'forward_reader':
            raise ValueError('Reader verification failed.')


if __name__ == '__main__':
    try:
        rotate()
    except Exception:
        raise SystemExit('Staging reader rotation failed; diagnostic details withheld.')
    print('{"reader_rotation_verified":true}')
