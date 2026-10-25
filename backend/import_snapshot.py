"""Explicit, idempotent importer for the prototype's OWN SQL read model.

  python import_snapshot.py data/forward-snapshot.json
  python import_snapshot.py data/forward-snapshot.json --db data/forward.sqlite3
  python import_snapshot.py data/forward-snapshot.json --postgres --confirm-postgres-import
  python import_snapshot.py data/forward-snapshot.json --postgres --init-postgres --confirm-postgres-import
  python import_snapshot.py data/forward-snapshot.json --postgres --init-postgres --create-reader --verify-reader-api --confirm-postgres-import

PostgreSQL uses BAKKEN_IMPORT_DATABASE_URL, falling back to DATABASE_URL.
Schema creation requires the explicit --init-postgres flag and an empty,
dedicated database or an already identified Forward schema.
No source database is opened. Existing unrelated SQLite databases are rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from backend import APP_NAME, APPLICATION_ID, DEFAULT_DB, SCHEMA_VERSION, search_text

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS forward_metadata (
  id INTEGER PRIMARY KEY CHECK (id = 1), app_name TEXT NOT NULL,
  schema_version INTEGER NOT NULL, payload TEXT NOT NULL, source_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forward_records (
  kind TEXT NOT NULL CHECK (kind IN ('orders','notices')), id TEXT NOT NULL,
  date_value TEXT, operator_value TEXT, type_value TEXT,
  search_text TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (kind, id)
);
CREATE INDEX IF NOT EXISTS forward_records_date ON forward_records(kind, date_value DESC, id);
CREATE INDEX IF NOT EXISTS forward_records_operator ON forward_records(kind, operator_value);
CREATE INDEX IF NOT EXISTS forward_records_type ON forward_records(kind, type_value);
"""


def _dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _category(value, name, maximum):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError(f"Invalid {name}.")
    return value.strip() or None


def _date(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T)", value):
        raise ValueError("Record dates must be ISO dates or null.")
    if len(value) > 10:
        datetime.fromisoformat(value)
    return date.fromisoformat(value[:10]).isoformat()


def _strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
        yield str(value)


def prepare_snapshot(snapshot_path):
    path = Path(snapshot_path).expanduser().resolve()
    raw = path.read_bytes()
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("Snapshot exceeds the prototype's 64 MiB import limit.")
    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Non-finite JSON number.")))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("snapshot"), dict):
        raise ValueError("Expected a version 1 snapshot object.")
    rows, counts = [], {}
    for kind in ("orders", "notices"):
        records = data.get(kind)
        if not isinstance(records, list):
            raise ValueError(f"{kind} must be an array.")
        seen = set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Records must be JSON objects.")
            record_id = record.get("id")
            if not isinstance(record_id, str) or not record_id.strip() or len(record_id) > 512 or re.search(r"[\x00-\x1f\x7f]", record_id) or record_id in seen:
                raise ValueError(f"Invalid or duplicate {kind} identifier.")
            seen.add(record_id)
            record_date = _date(record.get("date" if kind == "orders" else "reportDate"))
            operator = _category(record.get("operator"), "operator", 300)
            category = _category(record.get("reviewStatus" if kind == "orders" else "noticeType"), "record type", 120)
            rows.append((kind, record_id, record_date, operator, category, search_text(" ".join(_strings(record))), _dump(record)))
        counts[kind] = len(records)
    return _dump(data["snapshot"]), hashlib.sha256(raw).hexdigest(), rows, counts


def _assert_owned_sqlite(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise ValueError("Refusing to modify an existing database not owned by this prototype.")
        marker = connection.execute("SELECT app_name, schema_version FROM forward_metadata WHERE id = 1").fetchone()
        if marker != (APP_NAME, SCHEMA_VERSION):
            raise ValueError("Refusing to modify a database with a different application or schema version.")


def import_sqlite(snapshot_path, db_path=DEFAULT_DB):
    source = Path(snapshot_path).expanduser().resolve()
    target_input = Path(db_path).expanduser()
    if target_input.is_symlink():
        raise ValueError("The output database must not be a symlink.")
    target = target_input.resolve()
    if target == source:
        raise ValueError("Snapshot and output database must be separate files.")
    metadata, fingerprint, rows, counts = prepare_snapshot(source)
    existed = target.exists()
    if existed:
        _assert_owned_sqlite(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SQLITE_SCHEMA)
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
            connection.execute("DELETE FROM forward_records")
            connection.executemany("INSERT INTO forward_records(kind,id,date_value,operator_value,type_value,search_text,payload) VALUES(?,?,?,?,?,?,?)", rows)
            connection.execute(
                "INSERT INTO forward_metadata(id,app_name,schema_version,payload,source_sha256) VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET app_name=excluded.app_name,schema_version=excluded.schema_version,payload=excluded.payload,source_sha256=excluded.source_sha256",
                (APP_NAME, SCHEMA_VERSION, metadata, fingerprint),
            )
    finally:
        connection.close()
    return counts


def _initialize_postgres(connection):
    """Opt-in bootstrap. No request/startup code calls this function."""
    tables = connection.execute(
        "SELECT to_regclass('public.forward_metadata'), to_regclass('public.forward_records')"
    ).fetchone()
    if tables == (None, None):
        has_other_tables = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname NOT IN ('pg_catalog','information_schema') "
            "AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','v','m','f'))"
        ).fetchone()[0]
        if has_other_tables:
            raise ValueError("Bootstrap requires an empty dedicated database.")
        # The owned SQL file has its own BEGIN/COMMIT; connection autocommit
        # avoids an implicit outer transaction around this exact schema script.
        connection.execute(Path(__file__).with_name("schema_postgres.sql").read_text(encoding="utf-8"))
    elif not all(tables):
        raise ValueError("Refusing to repair or replace a partial PostgreSQL schema.")


def import_postgres(snapshot_path, database_url, *, initialize=False):
    from urllib.parse import urlsplit
    if urlsplit(database_url).scheme not in {"postgres", "postgresql"}:
        raise ValueError("DATABASE_URL must identify a PostgreSQL database.")
    metadata, fingerprint, rows, counts = prepare_snapshot(snapshot_path)
    import psycopg
    with psycopg.connect(database_url, connect_timeout=10, autocommit=True,
                        options="-c search_path=public -c statement_timeout=30000 -c lock_timeout=10000") as connection:
        if initialize:
            _initialize_postgres(connection)
        with connection.transaction():
            marker = connection.execute("SELECT app_name, schema_version FROM forward_metadata WHERE id=1").fetchone()
            if marker != (APP_NAME, SCHEMA_VERSION):
                raise ValueError("Apply the dedicated prototype schema before importing PostgreSQL.")
            connection.execute("LOCK TABLE forward_metadata, forward_records IN EXCLUSIVE MODE")
            connection.execute("DELETE FROM forward_records")
            with connection.cursor() as cursor:
                cursor.executemany("INSERT INTO forward_records(kind,id,date_value,operator_value,type_value,search_text,payload) VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb)", rows)
            connection.execute("UPDATE forward_metadata SET payload=%s::jsonb,source_sha256=%s WHERE id=1", (metadata, fingerprint))
    return counts


READER_ROLE = "forward_reader"
READER_MARKER = "bakken-forward-preview dedicated read-only role v1"


def _reader_configuration():
    """Validate the explicit staging reader inputs before any database writes."""
    import os
    from urllib.parse import parse_qs, unquote, urlsplit
    password = os.environ.get("PGPASSWORD", "")
    reader_url = os.environ.get("DATABASE_URL", "")
    parsed = urlsplit(reader_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if not (24 <= len(password) <= 256) or any(ord(char) < 33 or ord(char) > 126 for char in password):
        raise ValueError("Set a generated reader PGPASSWORD of 24 to 256 printable characters.")
    if (parsed.scheme not in {"postgres", "postgresql"} or unquote(parsed.username or "") != READER_ROLE
            or parsed.password is not None or not parsed.hostname):
        raise ValueError("DATABASE_URL must name forward_reader without an embedded password; PGPASSWORD supplies it.")
    if (set(query) - {"sslmode"} or parsed.fragment
            or ("sslmode" in query and (len(query["sslmode"]) != 1 or query["sslmode"][0] not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}))):
        raise ValueError("Reader URL query permits only a single sslmode option, with no credential or connection-target overrides.")
    return password, reader_url


def _reader_permissions(connection):
    """Effective privileges, including any grants inherited through PUBLIC."""
    row = connection.execute(
        "SELECT has_table_privilege(%s,'public.forward_metadata','SELECT'), "
        "has_table_privilege(%s,'public.forward_records','SELECT'), "
        "has_table_privilege(%s,'public.forward_metadata','INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'), "
        "has_table_privilege(%s,'public.forward_records','INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'), "
        "has_schema_privilege(%s,'public','CREATE'), has_database_privilege(%s,current_database(),'CREATE')",
        (READER_ROLE,) * 6,
    ).fetchone()
    result = dict(zip(("metadataSelect", "recordsSelect", "metadataWrite", "recordsWrite", "schemaCreate", "databaseCreate"), row))
    if list(row) != [True, True, False, False, False, False]:
        raise ValueError("The dedicated reader has unexpected effective privileges.")
    return result


def provision_reader(database_url, password):
    """Explicit one-time role provisioning; separate from schema/data import."""
    import psycopg
    from psycopg import sql
    with psycopg.connect(database_url, connect_timeout=10,
                        options="-c search_path=public -c statement_timeout=30000 -c lock_timeout=10000") as connection:
        role = connection.execute(
            "SELECT oid,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,"
            "shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=%s", (READER_ROLE,),
        ).fetchone()
        if role:
            if any(role[1:6]) or role[6] != READER_MARKER:
                raise ValueError("Refusing to change an unrelated or privileged existing reader role.")
            membership = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_auth_members WHERE member=%s OR roleid=%s)", (role[0], role[0]),
            ).fetchone()[0]
            ownership = connection.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_shdepend WHERE refclassid='pg_authid'::regclass "
                "AND refobjid=%s AND deptype='o')", (role[0],),
            ).fetchone()[0]
            if membership or ownership:
                raise ValueError("The reader must have no role memberships or owned objects.")
        action = sql.SQL("ALTER ROLE") if role else sql.SQL("CREATE ROLE")
        connection.execute(sql.SQL("{} {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                                   "NOINHERIT NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 16").format(
            action, sql.Identifier(READER_ROLE), sql.Literal(password),
        ))
        connection.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(READER_ROLE), sql.Literal(READER_MARKER)))
        connection.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(sql.Identifier(READER_ROLE)))
        connection.execute(sql.SQL("REVOKE ALL PRIVILEGES ON TABLE public.forward_metadata, public.forward_records FROM {}").format(sql.Identifier(READER_ROLE)))
        connection.execute(sql.SQL("GRANT SELECT ON TABLE public.forward_metadata, public.forward_records TO {}").format(sql.Identifier(READER_ROLE)))
        connection.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(READER_ROLE)))
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(READER_ROLE)))
        database = connection.execute("SELECT current_database()").fetchone()[0]
        connection.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(READER_ROLE)))
        permissions = _reader_permissions(connection)
    return permissions


def verify_reader_api():
    """Exercise real PostgreSQL reads after provisioning; return no source rows."""
    import psycopg
    from backend import handle_api
    _, reader_url = _reader_configuration()
    # This first connection intentionally has no application-enforced read-only
    # option: it also checks the role's own default on an ordinary connection.
    with psycopg.connect(reader_url, connect_timeout=10) as connection:
        current_user, readonly = connection.execute("SELECT current_user, current_setting('transaction_read_only')").fetchone()
        if current_user != READER_ROLE or readonly != "on":
            raise ValueError("Reader identity or read-only default is incorrect.")
        permissions = _reader_permissions(connection)
    status, health = handle_api("/health")
    if status != 200 or health.get("database") != "ready":
        raise ValueError("Reader health verification failed.")
    status, metadata = handle_api("/api/forward/meta")
    if status != 200 or metadata.get("backend") != {"storage": "postgresql", "mode": "read-only"}:
        raise ValueError("Reader metadata verification failed.")
    for kind in ("orders", "notices"):
        status, listing = handle_api("/api/forward/records", {"kind": kind, "limit": "1"})
        if status != 200 or listing.get("total") != metadata["counts"][kind]:
            raise ValueError("Reader listing verification failed.")
        if listing["rows"]:
            from urllib.parse import quote
            record = listing["rows"][0]
            status, detail = handle_api(f"/api/forward/records/{kind}/{quote(record['id'], safe='')}")
            if status != 200 or detail != record:
                raise ValueError("Reader detail verification failed.")
    return {"storage": "postgresql", "role": READER_ROLE, "readOnlyDefault": True,
            "health": "ready", "counts": metadata["counts"], "permissions": permissions,
            "apiChecks": ["health", "meta", "orders list/detail", "notices list/detail"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--postgres", action="store_true")
    parser.add_argument("--init-postgres", action="store_true", help="Create the exact prototype schema only in an empty dedicated PostgreSQL database.")
    parser.add_argument("--create-reader", action="store_true", help="Explicitly create the dedicated forward_reader role using PGPASSWORD after import.")
    parser.add_argument("--verify-reader-api", action="store_true", help="Verify PostgreSQL API reads using the reader DATABASE_URL and PGPASSWORD.")
    parser.add_argument("--confirm-postgres-import", action="store_true", help="Explicitly authorize replacing this dedicated PostgreSQL read model.")
    args = parser.parse_args()
    verification = permissions = None
    try:
        if args.postgres:
            if not args.confirm_postgres_import:
                parser.error("PostgreSQL import requires --confirm-postgres-import.")
            import os
            database_url = os.environ.get("BAKKEN_IMPORT_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
            if not database_url:
                parser.error("Set DATABASE_URL for the dedicated import role.")
            if args.create_reader or args.verify_reader_api:
                password, reader_url = _reader_configuration()
                if not os.environ.get("BAKKEN_IMPORT_DATABASE_URL") or database_url == reader_url:
                    parser.error("Reader provisioning requires a separate BAKKEN_IMPORT_DATABASE_URL.")
            counts = import_postgres(args.snapshot, database_url, initialize=args.init_postgres)
            if args.create_reader:
                permissions = provision_reader(database_url, password)
            if args.verify_reader_api:
                verification = verify_reader_api()
        else:
            if args.confirm_postgres_import or args.init_postgres or args.create_reader or args.verify_reader_api:
                parser.error("PostgreSQL import flags require --postgres.")
            counts = import_sqlite(args.snapshot, args.db)
    except Exception:
        parser.exit(1, "Import failed. Check snapshot validation, dedicated database ownership, configuration and permissions. No database credentials are printed.\n")
    result = {"imported": counts, "storage": "postgresql" if args.postgres else "sqlite"}
    if permissions is not None:
        result["readerPermissions"] = permissions
    if verification is not None:
        result["readerVerification"] = verification
    print(json.dumps(result))


if __name__ == "__main__":
    main()
