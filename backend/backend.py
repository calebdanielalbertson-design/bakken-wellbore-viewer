"""Small read-only Bakken Forward API; importing data is a separate CLI action.

Local callers use handle_api(path, parse_qs(query)). Railway can run
gunicorn backend:application. No request path creates tables or imports files.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = BASE_DIR / "data" / "forward.sqlite3"
SCHEMA_VERSION = 1
APPLICATION_ID = 0x42464F52
APP_NAME = "bakken-forward-preview"
KINDS = {"orders", "notices"}


class InvalidInput(ValueError):
    pass


class Unavailable(RuntimeError):
    pass


def search_text(value):
    """Identical Unicode folding for importer and literal substring queries."""
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


class ReadConnection:
    def __init__(self, connection, storage):
        self.connection, self.storage = connection, storage

    def execute(self, sql, parameters=()):
        # All SQL is application-owned; values are always separate parameters.
        if self.storage == "postgresql":
            sql = sql.replace("?", "%s")
        return self.connection.execute(sql, parameters)


@contextmanager
def _connect():
    connection = None
    try:
        database_url = os.environ.get("DATABASE_URL", "").strip()
        if database_url:
            if urlsplit(database_url).scheme not in {"postgres", "postgresql"}:
                raise Unavailable("Unsupported database configuration.")
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise Unavailable("PostgreSQL driver is not installed.") from exc
            connection = psycopg.connect(
                database_url, connect_timeout=5, row_factory=dict_row,
                options="-c default_transaction_read_only=on -c statement_timeout=5000 -c search_path=public",
            )
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            storage = "postgresql"
        else:
            path = Path(os.environ.get("BAKKEN_DB_PATH", str(DEFAULT_DB))).expanduser().resolve()
            # mode=ro is essential: a missing path must never create a database.
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            # Keep metadata, counts and rows from one committed import even if
            # an explicit importer replaces the snapshot during this request.
            connection.execute("BEGIN")
            if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
                raise Unavailable("Not a prepared Forward snapshot.")
            storage = "sqlite"
        db = ReadConnection(connection, storage)
        marker = db.execute("SELECT app_name, schema_version, source_sha256 FROM forward_metadata WHERE id = 1").fetchone()
        fingerprint = marker["source_sha256"] if marker else None
        if (not marker or marker["app_name"] != APP_NAME or marker["schema_version"] != SCHEMA_VERSION
                or not isinstance(fingerprint, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", fingerprint)):
            raise Unavailable("Forward snapshot is unavailable.")
        yield db
    finally:
        if connection is not None:
            connection.close()


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _scalar(query, key, default="", maximum=300):
    value = query.get(key, default)
    if isinstance(value, (list, tuple)):
        if len(value) != 1:
            raise InvalidInput(f"Supply {key} only once.")
        value = value[0]
    if not isinstance(value, str) or len(value) > maximum or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise InvalidInput(f"Invalid {key}.")
    return value.strip()


def _number(query, key, default, maximum):
    raw = _scalar(query, key, str(default), maximum=12)
    if not re.fullmatch(r"\d+", raw):
        raise InvalidInput(f"{key} must be a nonnegative integer.")
    number = int(raw)
    if number > maximum or (key == "limit" and number < 1):
        raise InvalidInput(f"{key} is outside the supported range.")
    return number


def _error(status, code, message):
    return status, {"error": {"code": code, "message": message}}


def _metadata(db):
    row = db.execute("SELECT payload FROM forward_metadata WHERE id = 1").fetchone()
    counts = {kind: 0 for kind in sorted(KINDS)}
    for record in db.execute("SELECT kind, COUNT(*) AS total FROM forward_records GROUP BY kind").fetchall():
        counts[record["kind"]] = record["total"]
    operators, types = {}, {}
    for kind in sorted(KINDS):
        operators[kind] = [r["value"] for r in db.execute(
            "SELECT DISTINCT operator_value AS value FROM forward_records WHERE kind = ? AND operator_value IS NOT NULL ORDER BY operator_value", (kind,)
        ).fetchall()]
        types[kind] = [r["value"] for r in db.execute(
            "SELECT DISTINCT type_value AS value FROM forward_records WHERE kind = ? AND type_value IS NOT NULL ORDER BY type_value", (kind,)
        ).fetchall()]
    return {"snapshot": _json(row["payload"]), "counts": counts, "operators": operators,
            "types": types, "backend": {"storage": db.storage, "mode": "read-only"}}


def handle_api(path, query_dict=None):
    """Return (HTTP status, JSON object). Accept scalar or parse_qs query values."""
    query = query_dict if query_dict is not None else {}
    if not isinstance(path, str) or not isinstance(query, dict):
        return _error(400, "invalid_request", "Invalid request.")
    if path == '/api/wells' or path.startswith('/api/wells/'):
        from wells_backend import handle_api as handle_wells
        return handle_wells(path, query)
    try:
        if path not in {"/health", "/api/forward/meta", "/api/forward/records"} and not path.startswith("/api/forward/records/"):
            return _error(404, "not_found", "Endpoint not found.")
        filters, parameters = [], []
        kind = record_id = None
        if path == "/api/forward/records":
            if set(query) - {"kind", "q", "operator", "type", "offset", "limit"}:
                raise InvalidInput("Unsupported query parameter.")
            kind = _scalar(query, "kind", "notices", 16)
            if kind not in KINDS:
                raise InvalidInput("kind must be notices or orders.")
            offset, limit = _number(query, "offset", 0, 1_000_000), _number(query, "limit", 25, 50)
            filters, parameters = ["kind = ?"], [kind]
            for key, column, maximum in [("operator", "operator_value", 300), ("type", "type_value", 120)]:
                value = _scalar(query, key, maximum=maximum)
                if value:
                    filters.append(column + " = ?")
                    parameters.append(value)
            term = _scalar(query, "q", maximum=200)
            if term:
                # % and _ are literal user text, not SQL wildcard controls.
                literal = search_text(term).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                filters.append("search_text LIKE ? ESCAPE '\\'")
                parameters.append("%" + literal + "%")
        elif path.startswith("/api/forward/records/"):
            kind, separator, raw_id = path[len("/api/forward/records/"):].partition("/")
            if kind not in KINDS or not separator or not raw_id:
                return _error(404, "not_found", "Record not found.")
            record_id = unquote(raw_id)
            if len(record_id) > 512 or re.search(r"[\x00-\x1f\x7f]", record_id):
                raise InvalidInput("Invalid record identifier.")
            if query:
                raise InvalidInput("This endpoint does not accept query parameters.")
        elif query:
            raise InvalidInput("This endpoint does not accept query parameters.")
        with _connect() as db:
            if path == "/health":
                db.execute("SELECT 1 FROM forward_records LIMIT 1").fetchone()
                if os.environ.get('BAKKEN_REQUIRE_WELL_RELEASE') == '1':
                    from wells_backend import handle_api as handle_wells
                    status, wells = handle_wells('/api/wells/meta')
                    if status != 200:
                        return _error(503, 'wells_unavailable', 'The validated well release is unavailable.')
                    return 200, {"ok": True, "database": "ready", "well_release": wells['release']['id']}
                return 200, {"ok": True, "database": "ready"}
            if path == "/api/forward/meta":
                return 200, _metadata(db)
            if record_id is not None:
                row = db.execute("SELECT payload FROM forward_records WHERE kind = ? AND id = ?", (kind, record_id)).fetchone()
                return (200, _json(row["payload"])) if row else _error(404, "not_found", "Record not found.")
            where = " AND ".join(filters)
            total = db.execute("SELECT COUNT(*) AS total FROM forward_records WHERE " + where, tuple(parameters)).fetchone()["total"]
            rows = db.execute(
                "SELECT payload FROM forward_records WHERE " + where +
                " ORDER BY CASE WHEN date_value IS NULL THEN 1 ELSE 0 END, date_value DESC, id ASC LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
            return 200, {"rows": [_json(row["payload"]) for row in rows], "total": total, "offset": offset, "limit": limit}
    except InvalidInput as exc:
        return _error(400, "invalid_request", str(exc))
    except Exception:
        # Database driver errors may contain credentials/hostnames. Never return them.
        return _error(503, "database_unavailable", "The prepared snapshot is unavailable. Please try again later.")


def application(environ, start_response):
    """GET-only WSGI boundary with explicit cross-origin allowlist."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    origin = environ.get("HTTP_ORIGIN", "")
    same_origin = f"{environ.get('wsgi.url_scheme', 'http')}://{environ.get('HTTP_HOST', '')}"
    allowed = {value.strip().rstrip("/") for value in os.environ.get("BAKKEN_ALLOWED_ORIGINS", "").split(",") if value.strip() and value.strip() != "*"}
    cross_origin = bool(origin and origin != same_origin)
    cors = [("Vary", "Origin")]
    if cross_origin and origin in allowed:
        cors.append(("Access-Control-Allow-Origin", origin))
    extra = []
    if method not in {"GET", "OPTIONS"}:
        status, payload = _error(405, "method_not_allowed", "Only GET is supported.")
        extra.append(("Allow", "GET"))
    elif cross_origin and origin not in allowed:
        status, payload = _error(403, "origin_not_allowed", "Origin is not allowed.")
    elif method == "OPTIONS":
        if environ.get("HTTP_ACCESS_CONTROL_REQUEST_METHOD", "GET").upper() != "GET":
            status, payload = _error(405, "method_not_allowed", "Only GET is supported.")
            extra.append(("Allow", "GET"))
        else:
            status, payload = 204, None
            if cross_origin:
                cors += [("Access-Control-Allow-Methods", "GET"), ("Access-Control-Allow-Headers", "Accept, Content-Type"), ("Access-Control-Max-Age", "600")]
    else:
        raw_query = environ.get("QUERY_STRING", "")
        try:
            if len(raw_query) > 4096:
                raise ValueError("Long query")
            query = parse_qs(raw_query, keep_blank_values=True, max_num_fields=12)
            # WSGI PATH_INFO is decoded; preserve literal percent characters when
            # passing through the raw-URL-path interface also used by serve.py.
            path = quote(environ.get("PATH_INFO", "/"), safe="/")
            status, payload = handle_api(path, query)
        except ValueError:
            status, payload = _error(400, "invalid_request", "Invalid query string.")
    body = b"" if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    reasons = {200: "OK", 204: "No Content", 400: "Bad Request", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 503: "Service Unavailable"}
    headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), *cors, *extra]
    start_response(f"{status} {reasons[status]}", headers)
    return [body]


if __name__ == "__main__":
    from wsgiref.simple_server import make_server
    port = int(os.environ.get("PORT", "8080"))
    with make_server("0.0.0.0", port, application) as server:
        server.serve_forever()
