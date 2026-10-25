"""Offline contract tests for the Forward snapshot importer and read-only API.

Run from this directory's parent with ``python -m unittest discover -s tests``.
Every test uses its own temporary source JSON and SQLite database; no real
snapshot, hosted database, network service, or third-party dependency is used.
"""

from __future__ import annotations

import io
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing
from unittest import mock
from types import SimpleNamespace
from urllib.parse import urlencode
from wsgiref.util import setup_testing_defaults


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

import backend  # noqa: E402
import import_snapshot  # noqa: E402
import prepare_staging_bundle  # noqa: E402


META = "/api/forward/meta"
RECORDS = "/api/forward/records"
EXPECTED_BUNDLE_FILES = {
    "backend.py", "import_snapshot.py", "schema_postgres.sql", "requirements.txt",
    "Dockerfile", "railway.toml", ".dockerignore", "data/forward-snapshot.json",
}


def fixture():
    """Distinct sentinel strings expose accidental SQL wildcard expansion."""
    snapshot = {
        "label": "Offline contract fixture",
        "preparedAt": "2026-10-17T12:00:00Z",
        "sourceDates": {"notices": "2026-10-10", "orders": "2026-10-11"},
        "coverage": "Synthetic test records only",
        "limitations": ["Not a production dataset"],
    }
    notices = [
        {"id": "n-02", "reportDate": "2026-10-10", "noticeType": "Permit",
         "operator": "Aperture Energy", "wellName": "NORTH 100% SPECIAL",
         "permit": "1001", "api": "33001000010000", "summary": "Percent marker",
         "sourceURL": "https://example.invalid/notices/2",
         "futureField": {"flags": [True, None, 7], "nested": {"literal": "future payload"}}},
        {"id": "n-01", "reportDate": "2026-10-10", "noticeType": "Completion",
         "operator": "Boreal Energy", "wellName": "A_B Survey",
         "permit": "1002", "api": None, "summary": "Underscore marker",
         "sourceURL": None},
        {"id": "n-03", "reportDate": "2026-10-09", "noticeType": "Completion",
         "operator": "Aperture Energy", "wellName": "BACK\\SLASH 3H",
         "permit": "1003", "api": None, "summary": "Backslash marker",
         "sourceURL": None},
        {"id": "n-04", "reportDate": "2026-10-08", "noticeType": "Permit",
         "operator": "Literal Operator", "wellName": "SQL literal",
         "permit": "1004", "api": None, "summary": "' OR 1=1 --",
         "sourceURL": None},
        {"id": "n-06", "reportDate": None, "noticeType": "Permit",
         "operator": "Aperture Energy", "wellName": "Undated B",
         "permit": None, "api": None, "summary": None, "sourceURL": None},
        {"id": "n-05", "reportDate": None, "noticeType": None,
         "operator": None, "wellName": "Undated A", "permit": None,
         "api": None, "summary": None, "sourceURL": None},
    ]
    orders = [
        {"id": "o-02", "date": "2026-10-11", "title": "Spacing order B",
         "orderNo": "40002", "caseNo": "50002", "operator": "Aperture Energy",
         "permit": None, "api": None, "summary": "Reviewed spacing",
         "provisions": ["First provision"], "sourceURL": None,
         "reviewStatus": "Reviewed"},
        {"id": "o-01", "date": "2026-10-11", "title": "Spacing order A",
         "orderNo": "40001", "caseNo": "50001", "operator": "Boreal Energy",
         "permit": None, "api": None, "summary": "Awaiting review",
         "provisions": [], "sourceURL": None, "reviewStatus": "Needs review"},
        {"id": "o-03", "date": "2026-10-08", "title": "Pooling order",
         "orderNo": "40003", "caseNo": "50003", "operator": "Aperture Energy",
         "permit": "1001", "api": None, "summary": "Reviewed pooling",
         "provisions": None, "sourceURL": None, "reviewStatus": "Reviewed",
         "unsupported": {"nullable": None, "values": [1.5, "preserve me"]}},
        {"id": "o-05", "date": None, "title": "Undated order B",
         "orderNo": None, "caseNo": None, "operator": "Aperture Energy",
         "permit": None, "api": None, "summary": None, "provisions": None,
         "sourceURL": None, "reviewStatus": "Needs review"},
        {"id": "o-04", "date": None, "title": "Undated order A",
         "orderNo": None, "caseNo": None, "operator": None, "permit": None,
         "api": None, "summary": None, "provisions": None,
         "sourceURL": None, "reviewStatus": None},
    ]
    return {"version": 1, "snapshot": snapshot, "orders": orders, "notices": notices}


class BackendContractTests(unittest.TestCase):
    def setUp(self):
        # Keep transient files within the test workspace: Windows sandbox TEMP
        # can allow directory creation while denying writes inside it.
        self.temp = tempfile.TemporaryDirectory(prefix=".tmp-forward-", dir=Path(__file__).resolve().parent)
        self.root = Path(self.temp.name).resolve()
        self.assertTrue(self.root.is_relative_to(PROJECT / "tests"))
        self.addCleanup(self.temp.cleanup)
        self.db = self.root / "snapshot.sqlite3"
        self.source = self.root / "snapshot.json"
        self.data = fixture()
        self.source.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.source_bytes = self.source.read_bytes()
        env = dict(os.environ)
        env.pop("DATABASE_URL", None)
        env.pop("BAKKEN_ALLOWED_ORIGINS", None)
        env["BAKKEN_DB_PATH"] = str(self.db)
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.counts = import_snapshot.import_sqlite(str(self.source), str(self.db))

    def api(self, path=RECORDS, **query):
        status, payload = backend.handle_api(path, query)
        self.assertIs(type(status), int)
        self.assertIsInstance(payload, dict)
        return status, payload

    def rows(self, **query):
        status, payload = self.api(**query)
        self.assertEqual(status, 200, payload)
        self.assertEqual(set(payload), {"rows", "total", "offset", "limit"})
        self.assertIsInstance(payload["rows"], list)
        for key in ("total", "offset", "limit"):
            self.assertIs(type(payload[key]), int, key)
        return payload

    def assert_error(self, result, status):
        actual_status, payload = result
        self.assertEqual(actual_status, status, payload)
        self.assertEqual(set(payload), {"error"})
        self.assertEqual(set(payload["error"]), {"code", "message"})
        self.assertIsInstance(payload["error"]["code"], str)
        self.assertTrue(payload["error"]["code"])
        self.assertIsInstance(payload["error"]["message"], str)
        self.assertTrue(payload["error"]["message"])
        self.assertNotIn("traceback", payload["error"]["message"].lower())

    def wsgi(self, path=RECORDS, *, method="GET", query=None, origin=None, request_method=None):
        environ = {}
        setup_testing_defaults(environ)
        environ.update({"REQUEST_METHOD": method, "PATH_INFO": path,
                        "QUERY_STRING": urlencode(query or {}, doseq=True),
                        "wsgi.input": io.BytesIO(b"")})
        if origin is not None:
            environ["HTTP_ORIGIN"] = origin
        if request_method is not None:
            environ["HTTP_ACCESS_CONTROL_REQUEST_METHOD"] = request_method
        response = {}

        def start_response(status, headers, exc_info=None):
            response["status"] = int(status.split(" ", 1)[0])
            response["headers"] = {key.lower(): value for key, value in headers}

        iterable = backend.application(environ, start_response)
        try:
            body = b"".join(iterable)
        finally:
            if hasattr(iterable, "close"):
                iterable.close()
        response["body"] = body
        response["json"] = json.loads(body) if body else None
        return response

    def test_import_counts_and_source_unchanged(self):
        self.assertEqual(self.counts, {"orders": 5, "notices": 6})
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        self.assertTrue(self.db.is_file())

    def test_metadata_exact_shape_and_types(self):
        status, payload = self.api(META)
        self.assertEqual(status, 200)
        self.assertEqual(payload, {
            "snapshot": self.data["snapshot"],
            "counts": {"orders": 5, "notices": 6},
            "operators": {"orders": ["Aperture Energy", "Boreal Energy"],
                          "notices": ["Aperture Energy", "Boreal Energy", "Literal Operator"]},
            "types": {"orders": ["Needs review", "Reviewed"],
                      "notices": ["Completion", "Permit"]},
            "backend": {"storage": "sqlite", "mode": "read-only"},
        })
        for value in payload["counts"].values():
            self.assertIs(type(value), int)

    def test_default_list_is_notices_with_default_pagination(self):
        payload = self.rows()
        self.assertEqual((payload["total"], payload["offset"], payload["limit"]), (6, 0, 25))
        self.assertEqual({row["id"] for row in payload["rows"]}, {row["id"] for row in self.data["notices"]})

    def test_pagination_is_stable_with_null_dates_last(self):
        for kind, date_field in (("notices", "reportDate"), ("orders", "date")):
            with self.subTest(kind=kind):
                all_rows = self.rows(kind=kind, limit="50")["rows"]
                self.assertEqual(all_rows, self.rows(kind=kind, limit="50")["rows"])
                dates = [row[date_field] for row in all_rows]
                dated = [date for date in dates if date is not None]
                self.assertEqual(dates, sorted(dated, reverse=True) + [None] * (len(dates) - len(dated)))
                paged = []
                for offset in range(0, len(all_rows), 2):
                    page = self.rows(kind=kind, offset=str(offset), limit="2")
                    self.assertEqual((page["total"], page["offset"], page["limit"]), (len(all_rows), offset, 2))
                    paged.extend(page["rows"])
                self.assertEqual(paged, all_rows)
                past_end = self.rows(kind=kind, offset="100", limit="2")
                self.assertEqual(past_end["rows"], [])
                self.assertEqual(past_end["total"], len(all_rows))

    def test_operator_and_kind_specific_type_filters(self):
        cases = [
            ({"operator": "Aperture Energy"}, {"n-02", "n-03", "n-06"}),
            ({"type": "Completion"}, {"n-01", "n-03"}),
            ({"operator": "Aperture Energy", "type": "Completion"}, {"n-03"}),
            ({"kind": "orders", "type": "Reviewed"}, {"o-02", "o-03"}),
            ({"kind": "orders", "operator": "Aperture Energy", "type": "Needs review"}, {"o-05"}),
            ({"operator": "No such operator"}, set()),
            ({"type": "No such type"}, set()),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                payload = self.rows(**query)
                self.assertEqual({row["id"] for row in payload["rows"]}, expected)
                self.assertEqual(payload["total"], len(expected))

    def test_search_is_case_insensitive_and_combines_filters(self):
        self.assertEqual([row["id"] for row in self.rows(q="north")["rows"]], ["n-02"])
        self.assertEqual([row["id"] for row in self.rows(kind="orders", q="40003")["rows"]], ["o-03"])
        self.assertEqual(self.rows(q="north", operator="Boreal Energy")["rows"], [])
        self.assertEqual(self.rows(q="north", type="Completion")["rows"], [])
        self.assertEqual(self.rows(q="")["total"], 6)

    def test_search_percent_underscore_and_backslash_are_literal(self):
        for query, expected in (("%", "n-02"), ("_", "n-01"), ("\\", "n-03")):
            with self.subTest(query=query):
                payload = self.rows(q=query)
                self.assertEqual(payload["total"], 1)
                self.assertEqual([row["id"] for row in payload["rows"]], [expected])

    def test_sql_looking_search_filter_and_id_are_data(self):
        marker = "' OR 1=1 --"
        payload = self.rows(q=marker)
        self.assertEqual([row["id"] for row in payload["rows"]], ["n-04"])
        self.assertEqual(self.rows(operator=marker)["rows"], [])
        self.assertEqual(self.rows(type=marker)["rows"], [])
        self.assert_error(self.api(f"{RECORDS}/notices/{marker}"), 404)
        self.assertEqual(self.rows(q="'; DROP TABLE notices; --")["rows"], [])
        self.assertEqual(self.rows()["total"], 6)
        self.assertEqual(self.rows(kind="orders")["total"], 5)

    def test_detail_is_raw_record_and_preserves_unknown_fields_and_nulls(self):
        for kind in ("notices", "orders"):
            for expected in self.data[kind]:
                with self.subTest(kind=kind, id=expected["id"]):
                    status, payload = self.api(f"{RECORDS}/{kind}/{expected['id']}")
                    self.assertEqual(status, 200)
                    self.assertEqual(payload, expected)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_list_preserves_raw_record_fields(self):
        for kind in ("notices", "orders"):
            expected = {row["id"]: row for row in self.data[kind]}
            for row in self.rows(kind=kind)["rows"]:
                self.assertEqual(row, expected[row["id"]])

    def test_invalid_parameters_return_400(self):
        invalid = [
            {"kind": "other"}, {"kind": "notices; DROP TABLE notices"},
            {"limit": "0"}, {"limit": "-1"}, {"limit": "51"},
            {"limit": "2.5"}, {"limit": "NaN"}, {"limit": "1; SELECT 1"},
            {"offset": "-1"}, {"offset": "1.5"}, {"offset": "NaN"},
            {"q": ["one", "two"]}, {"kind": ["notices", "orders"]},
            {"operator": ["Aperture Energy", "Boreal Energy"]},
        ]
        for query in invalid:
            with self.subTest(query=query):
                self.assert_error(backend.handle_api(RECORDS, query), 400)

    def test_parse_qs_style_single_values_supported(self):
        status, payload = backend.handle_api(RECORDS, {
            "kind": ["notices"], "q": ["north"], "operator": ["Aperture Energy"],
            "type": ["Permit"], "limit": ["2"], "offset": ["0"],
        })
        self.assertEqual(status, 200, payload)
        self.assertEqual([row["id"] for row in payload["rows"]], ["n-02"])
        self.assertEqual((payload["total"], payload["offset"], payload["limit"]), (1, 0, 2))

    def test_missing_records_and_routes_return_404(self):
        for path in (f"{RECORDS}/notices/missing", f"{RECORDS}/orders/missing", "/api/forward/not-a-route"):
            with self.subTest(path=path):
                self.assert_error(self.api(path), 404)

    def test_database_absent_returns_503_without_creating_file(self):
        missing = self.root / "never-created.sqlite3"
        with mock.patch.dict(os.environ, {"BAKKEN_DB_PATH": str(missing)}):
            for path in (META, RECORDS, f"{RECORDS}/notices/n-02"):
                with self.subTest(path=path):
                    self.assert_error(self.api(path), 503)
                    self.assertFalse(missing.exists())

    def test_health_reports_ready(self):
        self.assertEqual(self.api("/health"), (200, {"ok": True, "database": "ready"}))

    def test_schema_without_imported_fingerprint_is_not_ready(self):
        for fingerprint in ("", "f" * 63, "g" * 64):
            connection = sqlite3.connect(self.db)
            try:
                with connection:
                    connection.execute("DELETE FROM forward_records")
                    connection.execute("UPDATE forward_metadata SET payload = '{}', source_sha256 = ? WHERE id = 1", (fingerprint,))
            finally:
                connection.close()
            for path in ("/health", META, RECORDS):
                with self.subTest(fingerprint=fingerprint, path=path):
                    self.assert_error(self.api(path), 503)
        import_snapshot.import_sqlite(self.source, self.db)
        self.assertEqual(self.api("/health")[0], 200, "explicit import restores readiness")

    def test_postgres_empty_import_marker_is_not_ready(self):
        # Driver boundary only: no installed dependency or hosted database needed.
        driver, rows_module = types.ModuleType("psycopg"), types.ModuleType("psycopg.rows")
        rows_module.dict_row = object()
        connection = mock.MagicMock()
        connection.execute.return_value.fetchone.return_value = {
            "app_name": backend.APP_NAME, "schema_version": backend.SCHEMA_VERSION, "source_sha256": ""
        }
        driver.connect = mock.Mock(return_value=connection)
        with mock.patch.dict(sys.modules, {"psycopg": driver, "psycopg.rows": rows_module}), mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql://reader:secret@private.invalid/forward"}):
            self.assert_error(self.api("/health"), 503)
        connection.close.assert_called_once()

    def test_reimport_is_idempotent_and_never_changes_source(self):
        before = {kind: self.rows(kind=kind)["rows"] for kind in ("orders", "notices")}
        counts = import_snapshot.import_sqlite(str(self.source), str(self.db))
        self.assertEqual(counts, self.counts)
        self.assertEqual(self.source.read_bytes(), self.source_bytes)
        for kind in ("orders", "notices"):
            self.assertEqual(self.rows(kind=kind)["rows"], before[kind])

    def test_import_refuses_existing_foreign_database_without_modifying_it(self):
        foreign = self.root / "foreign.sqlite3"
        with closing(sqlite3.connect(foreign)) as connection, connection:
            connection.execute("CREATE TABLE valuable_data (id INTEGER PRIMARY KEY, message TEXT)")
            connection.execute("INSERT INTO valuable_data VALUES (1, ?)", ("Do not overwrite",))
        original_bytes = foreign.read_bytes()
        with self.assertRaises(Exception):
            import_snapshot.import_sqlite(str(self.source), str(foreign))
        self.assertEqual(foreign.read_bytes(), original_bytes)
        with closing(sqlite3.connect(foreign)) as connection:
            self.assertEqual(connection.execute("SELECT * FROM valuable_data").fetchall(), [(1, "Do not overwrite")])
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            self.assertEqual(tables, [("valuable_data",)])
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_backend_database_connection_rejects_sql_writes(self):
        if callable(getattr(backend, "_connect", None)):
            with backend._connect() as connection:
                self.assertEqual(connection.execute("SELECT 1").fetchone()[0], 1)
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute("CREATE TABLE forbidden_write (id INTEGER)")
        else:
            # Observe the real connection, rather than substituting a fake DB.
            original_connect = sqlite3.connect
            attempts = []

            def observe_connect(*args, **kwargs):
                connection = original_connect(*args, **kwargs)
                try:
                    connection.execute("CREATE TABLE forbidden_write (id INTEGER)")
                except sqlite3.DatabaseError:
                    attempts.append(True)
                else:
                    connection.rollback()
                    attempts.append(False)
                return connection

            with mock.patch("sqlite3.connect", side_effect=observe_connect):
                self.assertEqual(self.api(META)[0], 200)
            self.assertTrue(attempts, "Could not observe an actual backend SQLite connection")
            self.assertTrue(all(attempts), "Backend connection allowed SQL writes")
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE name='forbidden_write'").fetchall(), [])

    def test_wsgi_get_json_and_query_validation(self):
        response = self.wsgi(query={"kind": "orders", "limit": "2"})
        self.assertEqual(response["status"], 200)
        self.assertTrue(response["headers"].get("content-type", "").startswith("application/json"))
        self.assertEqual(response["json"]["total"], 5)
        self.assertEqual(len(response["json"]["rows"]), 2)
        duplicate = self.wsgi(query={"kind": ["notices", "orders"]})
        self.assert_error((duplicate["status"], duplicate["json"]), 400)

    def test_wsgi_mutation_methods_rejected_with_allow_get(self):
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                response = self.wsgi(method=method)
                self.assert_error((response["status"], response["json"]), 405)
                self.assertEqual(response["headers"].get("allow"), "GET")
        self.assertEqual(self.rows()["total"], 6)

    def test_wsgi_cors_exact_allowlist_never_wildcard_or_credentials(self):
        origin = "https://preview.example.invalid"
        second = "http://localhost:8765"
        with mock.patch.dict(os.environ, {"BAKKEN_ALLOWED_ORIGINS": f"{origin},{second}"}):
            for allowed in (origin, second):
                with self.subTest(allowed=allowed):
                    response = self.wsgi(origin=allowed)
                    self.assertEqual(response["status"], 200)
                    self.assertEqual(response["headers"].get("access-control-allow-origin"), allowed)
                    self.assertNotEqual(response["headers"].get("access-control-allow-credentials", "").lower(), "true")
            for denied in (origin + ".attacker.invalid", "https://attacker.invalid", "null"):
                with self.subTest(denied=denied):
                    response = self.wsgi(origin=denied)
                    self.assertNotIn("access-control-allow-origin", response["headers"])
        response = self.wsgi(origin=origin)
        self.assertNotIn("access-control-allow-origin", response["headers"])

    def test_wsgi_cors_preflight_allows_only_configured_get_origin(self):
        origin = "https://preview.example.invalid"
        with mock.patch.dict(os.environ, {"BAKKEN_ALLOWED_ORIGINS": origin}):
            allowed = self.wsgi(method="OPTIONS", origin=origin, request_method="GET")
            self.assertEqual(allowed["status"], 204)
            self.assertEqual(allowed["body"], b"")
            self.assertEqual(allowed["headers"].get("access-control-allow-origin"), origin)
            self.assertEqual(allowed["headers"].get("access-control-allow-methods"), "GET")
            denied = self.wsgi(method="OPTIONS", origin="https://attacker.invalid", request_method="GET")
            self.assertEqual(denied["status"], 403)
            self.assertNotIn("access-control-allow-origin", denied["headers"])
            mutation = self.wsgi(method="OPTIONS", origin=origin, request_method="POST")
            self.assertEqual(mutation["status"], 405)
            self.assertEqual(mutation["headers"].get("allow"), "GET")
        unconfigured = self.wsgi(method="OPTIONS", origin=origin, request_method="GET")
        self.assertEqual(unconfigured["status"], 403)
        self.assertNotIn("access-control-allow-origin", unconfigured["headers"])

    def test_postgres_bootstrap_empty_database_executes_exact_sibling_schema(self):
        connection = mock.MagicMock()
        connection.execute.side_effect = [
            mock.Mock(fetchone=mock.Mock(return_value=(None, None))),
            mock.Mock(fetchone=mock.Mock(return_value=(False,))),
            mock.Mock(),
        ]
        import_snapshot._initialize_postgres(connection)
        statements = [call.args[0] for call in connection.execute.call_args_list]
        schema = Path(import_snapshot.__file__).with_name("schema_postgres.sql").read_text(encoding="utf-8")
        self.assertEqual(len(statements), 3)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT ") for sql in statements[:-1]))
        self.assertEqual(statements[-1], schema)

    def test_postgres_bootstrap_refuses_unrelated_relations_before_mutation(self):
        connection = mock.MagicMock()
        connection.execute.side_effect = [
            mock.Mock(fetchone=mock.Mock(return_value=(None, None))),
            mock.Mock(fetchone=mock.Mock(return_value=(True,))),
        ]
        with self.assertRaises(ValueError):
            import_snapshot._initialize_postgres(connection)
        statements = [call.args[0] for call in connection.execute.call_args_list]
        self.assertEqual(len(statements), 2)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT ") for sql in statements))

    def test_postgres_bootstrap_refuses_partial_schema_before_mutation(self):
        for tables in (("forward_metadata", None), (None, "forward_records")):
            with self.subTest(tables=tables):
                connection = mock.MagicMock()
                connection.execute.return_value.fetchone.return_value = tables
                with self.assertRaises(ValueError):
                    import_snapshot._initialize_postgres(connection)
                statements = [call.args[0] for call in connection.execute.call_args_list]
                self.assertEqual(len(statements), 1)
                self.assertTrue(statements[0].lstrip().upper().startswith("SELECT "))

    def test_postgres_bootstrap_does_not_reapply_existing_schema(self):
        connection = mock.MagicMock()
        connection.execute.return_value.fetchone.return_value = ("forward_metadata", "forward_records")
        import_snapshot._initialize_postgres(connection)
        statements = [call.args[0] for call in connection.execute.call_args_list]
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].lstrip().upper().startswith("SELECT "))

    def test_normal_postgres_import_never_bootstraps_existing_owned_schema(self):
        connection = mock.MagicMock()
        connection.execute.return_value.fetchone.return_value = (backend.APP_NAME, backend.SCHEMA_VERSION)
        connect = mock.MagicMock()
        connect.return_value.__enter__.return_value = connection
        fake_psycopg = SimpleNamespace(connect=connect)
        with mock.patch.dict(sys.modules, {"psycopg": fake_psycopg}), mock.patch.object(
                import_snapshot, "_initialize_postgres", side_effect=AssertionError("Unexpected bootstrap")) as bootstrap:
            counts = import_snapshot.import_postgres(self.source, "postgresql://example.invalid/fixture")
        bootstrap.assert_not_called()
        self.assertEqual(counts, {"orders": 5, "notices": 6})
        connection.transaction.assert_called_once_with()
        batch = connection.cursor.return_value.__enter__.return_value.executemany
        batch.assert_called_once()
        self.assertEqual(len(batch.call_args.args[1]), 11)
        statements = [call.args[0].lstrip().upper() for call in connection.execute.call_args_list]
        self.assertFalse(any(sql.startswith(("CREATE ", "DROP ", "ALTER ")) for sql in statements))
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def test_sqlite_reader_keeps_one_snapshot_across_concurrent_import(self):
        # WAL lets the importer commit while a different connection is reading.
        # Interleaved transactions make this deterministic without timing/thread races.
        with closing(sqlite3.connect(self.db)) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0].lower(), "wal")
        changed = fixture()
        changed["snapshot"]["label"] = "Replacement snapshot"
        changed["orders"] = []
        changed["notices"] = [{**changed["notices"][0], "id": "n-new"}]
        replacement = self.root / "replacement.json"
        replacement.write_text(json.dumps(changed), encoding="utf-8")
        with backend._connect() as reader:
            original_meta = backend._metadata(reader)
            original_rows = reader.execute("SELECT kind,id,payload FROM forward_records ORDER BY kind,id").fetchall()
            counts = import_snapshot.import_sqlite(replacement, self.db)
            self.assertEqual(counts, {"orders": 0, "notices": 1})
            self.assertEqual(backend._metadata(reader), original_meta)
            after_rows = reader.execute("SELECT kind,id,payload FROM forward_records ORDER BY kind,id").fetchall()
            self.assertEqual([tuple(row) for row in after_rows], [tuple(row) for row in original_rows])
        status, current = self.api(META)
        self.assertEqual(status, 200)
        self.assertEqual(current["counts"], {"orders": 0, "notices": 1})
        self.assertEqual(current["snapshot"]["label"], "Replacement snapshot")
        self.assertEqual([row["id"] for row in self.rows()["rows"]], ["n-new"])
        self.assertEqual(self.source.read_bytes(), self.source_bytes)

    def bundle_source(self):
        source = self.root / "bundle-source"
        source.mkdir()
        for name in EXPECTED_BUNDLE_FILES:
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.source_bytes if name == "data/forward-snapshot.json" else f"Fixture file: {name}\n".encode())
        exclusions = {
            ".env": b"FAKE_SECRET=do-not-package\n",
            "data/forward.sqlite3": b"Local database must stay local",
            "forward/index.html": b"<html>Frontend excluded</html>",
            "tests/test_local.py": b"# Tests excluded\n",
            "logs/import.log": b"Local log excluded\n",
            "credentials.json": b'{"fake": "not a deployment input"}',
        }
        for name, contents in exclusions.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        return source, hashlib.sha256(self.source_bytes).hexdigest()

    def test_staging_bundle_contains_only_allowlisted_bytes_and_verified_manifest(self):
        source, fingerprint = self.bundle_source()
        before = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()}
        destination = self.root / "staging-bundle"
        manifest = prepare_staging_bundle.prepare_bundle(destination, fingerprint, source=source)
        bundled = {path.relative_to(destination).as_posix(): path.read_bytes() for path in destination.rglob("*") if path.is_file()}
        self.assertEqual(set(bundled), EXPECTED_BUNDLE_FILES | {"BUNDLE-MANIFEST.json"})
        self.assertEqual(manifest["snapshotSHA256"], fingerprint)
        self.assertEqual(manifest["counts"], {"orders": 5, "notices": 6})
        self.assertEqual(set(manifest["files"]), EXPECTED_BUNDLE_FILES)
        for name in EXPECTED_BUNDLE_FILES:
            self.assertEqual(bundled[name], before[name])
            self.assertEqual(manifest["files"][name], {"bytes": len(before[name]), "sha256": hashlib.sha256(before[name]).hexdigest()})
        self.assertEqual(json.loads(bundled["BUNDLE-MANIFEST.json"]), manifest)
        after = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*") if path.is_file()}
        self.assertEqual(after, before)

    def test_staging_bundle_requires_exact_reviewed_snapshot_hash(self):
        source, fingerprint = self.bundle_source()
        for index, wrong_hash in enumerate((None, "not-a-hash", "0" * 64)):
            with self.subTest(hash=wrong_hash):
                destination = self.root / f"bad-hash-{index}"
                with self.assertRaises(ValueError):
                    prepare_staging_bundle.prepare_bundle(destination, wrong_hash, source=source)
                self.assertFalse(destination.exists())
        changed = fixture()
        changed["snapshot"]["label"] = "Changed after review"
        (source / "data/forward-snapshot.json").write_text(json.dumps(changed), encoding="utf-8")
        destination = self.root / "stale-review"
        with self.assertRaises(ValueError):
            prepare_staging_bundle.prepare_bundle(destination, fingerprint, source=source)
        self.assertFalse(destination.exists())

    def test_staging_bundle_refuses_existing_destination_without_changes(self):
        source, fingerprint = self.bundle_source()
        destination = self.root / "existing"
        destination.mkdir()
        sentinel = destination / "keep.txt"
        sentinel.write_bytes(b"Preserve this existing directory.")
        with self.assertRaises(ValueError):
            prepare_staging_bundle.prepare_bundle(destination, fingerprint, source=source)
        self.assertEqual(sentinel.read_bytes(), b"Preserve this existing directory.")
        self.assertEqual([path.name for path in destination.iterdir()], ["keep.txt"])
        with self.assertRaises(ValueError):
            prepare_staging_bundle.prepare_bundle(source / "nested-bundle", fingerprint, source=source)
        self.assertFalse((source / "nested-bundle").exists())

    def test_reader_configuration_accepts_separate_password_and_rejects_bad_secrets(self):
        reader_url = "postgresql://forward_reader@example.invalid/fixture"
        password = "test-only-password-0123456789"
        with mock.patch.dict(os.environ, {"DATABASE_URL": reader_url, "PGPASSWORD": password}):
            self.assertEqual(import_snapshot._reader_configuration(), (password, reader_url))
        for invalid in ("", "x" * 23, "x" * 257, " " * 24, "x" * 23 + "\n"):
            with self.subTest(length=len(invalid)), mock.patch.dict(
                    os.environ, {"DATABASE_URL": reader_url, "PGPASSWORD": invalid}):
                with self.assertRaises(ValueError):
                    import_snapshot._reader_configuration()

    def test_reader_configuration_rejects_wrong_identity_and_embedded_password(self):
        urls = (
            "postgresql://administrator@example.invalid/fixture",
            "postgresql://forward_reader:embedded@example.invalid/fixture",
            "postgresql://forward_reader:@example.invalid/fixture",
            "postgresql://forward_reader@example.invalid/fixture?user=administrator",
            "postgresql://forward_reader@example.invalid/fixture?password=embedded",
            "postgresql://forward_reader@/fixture",
            "https://forward_reader@example.invalid/fixture",
        )
        for reader_url in urls:
            with self.subTest(url=reader_url), mock.patch.dict(
                    os.environ, {"DATABASE_URL": reader_url, "PGPASSWORD": "test-only-password-0123456789"}):
                with self.assertRaises(ValueError):
                    import_snapshot._reader_configuration()

    def test_reader_permissions_require_select_without_write_or_create(self):
        expected = {"metadataSelect": True, "recordsSelect": True, "metadataWrite": False,
                    "recordsWrite": False, "schemaCreate": False, "databaseCreate": False}
        connection = mock.MagicMock()
        connection.execute.return_value.fetchone.return_value = tuple(expected.values())
        self.assertEqual(import_snapshot._reader_permissions(connection), expected)
        self.assertEqual(connection.execute.call_args.args[1], ("forward_reader",) * 6)
        for index, field in enumerate(expected):
            with self.subTest(field=field):
                privileges = list(expected.values())
                privileges[index] = not privileges[index]
                connection.execute.return_value.fetchone.return_value = tuple(privileges)
                with self.assertRaises(ValueError):
                    import_snapshot._reader_permissions(connection)

    def test_reader_cli_guards_run_before_any_import_or_role_mutation(self):
        password = "test-only-password-0123456789"
        reader_url = "postgresql://forward_reader@example.invalid/fixture"
        base_env = {"DATABASE_URL": reader_url, "PGPASSWORD": password}
        for flag in ("--create-reader", "--verify-reader-api"):
            cases = [
                ([flag], base_env),
                (["--postgres", "--confirm-postgres-import", flag], base_env),
                (["--postgres", "--confirm-postgres-import", flag], {**base_env, "BAKKEN_IMPORT_DATABASE_URL": reader_url}),
                (["--postgres", "--confirm-postgres-import", flag], {**base_env,
                 "BAKKEN_IMPORT_DATABASE_URL": "postgresql://importer@example.invalid/fixture", "PGPASSWORD": "short"}),
            ]
            for index, (arguments, env) in enumerate(cases):
                with self.subTest(flag=flag, case=index), mock.patch.dict(os.environ, env, clear=True), \
                        mock.patch.object(sys, "argv", ["import_snapshot.py", str(self.source), *arguments]), \
                        mock.patch("sys.stderr", new_callable=io.StringIO) as stderr, \
                        mock.patch("sys.stdout", new_callable=io.StringIO), \
                        mock.patch.object(import_snapshot, "import_postgres") as pg_import, \
                        mock.patch.object(import_snapshot, "import_sqlite") as sqlite_import, \
                        mock.patch.object(import_snapshot, "provision_reader") as provision, \
                        mock.patch.object(import_snapshot, "verify_reader_api") as verify:
                    with self.assertRaises(SystemExit) as stopped:
                        import_snapshot.main()
                    self.assertNotEqual(stopped.exception.code, 0)
                    pg_import.assert_not_called()
                    sqlite_import.assert_not_called()
                    provision.assert_not_called()
                    verify.assert_not_called()
                    self.assertNotIn(password, stderr.getvalue())
                    self.assertNotIn(reader_url, stderr.getvalue())

    def test_reader_api_verifies_postgres_lists_and_encoded_details_without_returning_rows(self):
        reader_url = "postgresql://forward_reader@example.invalid/fixture"
        orders = {"id": "order/A B", "summary": "Source details sentinel"}
        notices = {"id": "notice/A B", "summary": "Another source row"}
        metadata = {"backend": {"storage": "postgresql", "mode": "read-only"}, "counts": {"orders": 1, "notices": 1}}
        responses = [(200, {"database": "ready"}), (200, metadata),
                     (200, {"rows": [orders], "total": 1}), (200, orders),
                     (200, {"rows": [notices], "total": 1}), (200, notices)]
        connection = mock.MagicMock()
        connection.execute.return_value.fetchone.return_value = ("forward_reader", "on")
        connect = mock.MagicMock()
        connect.return_value.__enter__.return_value = connection
        permissions = {"metadataSelect": True, "recordsSelect": True, "metadataWrite": False,
                       "recordsWrite": False, "schemaCreate": False, "databaseCreate": False}
        with mock.patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect)}), \
                mock.patch.object(import_snapshot, "_reader_configuration", return_value=("synthetic", reader_url)), \
                mock.patch.object(import_snapshot, "_reader_permissions", return_value=permissions), \
                mock.patch.object(backend, "handle_api", side_effect=responses) as api:
            result = import_snapshot.verify_reader_api()
        connect.assert_called_once_with(reader_url, connect_timeout=10)
        self.assertEqual(result, {"storage": "postgresql", "role": "forward_reader", "readOnlyDefault": True,
                                 "health": "ready", "counts": {"orders": 1, "notices": 1}, "permissions": permissions,
                                 "apiChecks": ["health", "meta", "orders list/detail", "notices list/detail"]})
        self.assertEqual(api.call_args_list, [
            mock.call("/health"), mock.call(META), mock.call(RECORDS, {"kind": "orders", "limit": "1"}),
            mock.call(f"{RECORDS}/orders/order%2FA%20B"), mock.call(RECORDS, {"kind": "notices", "limit": "1"}),
            mock.call(f"{RECORDS}/notices/notice%2FA%20B"),
        ])
        self.assertNotIn("Source details sentinel", json.dumps(result))

    def test_reader_api_rejects_wrong_login_or_default_before_api_calls(self):
        for identity in (("administrator", "on"), ("forward_reader", "off")):
            connection = mock.MagicMock()
            connection.execute.return_value.fetchone.return_value = identity
            connect = mock.MagicMock()
            connect.return_value.__enter__.return_value = connection
            with self.subTest(identity=identity), \
                    mock.patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect)}), \
                    mock.patch.object(import_snapshot, "_reader_configuration", return_value=("synthetic", "postgresql://example.invalid/fixture")), \
                    mock.patch.object(backend, "handle_api") as api:
                with self.assertRaises(ValueError):
                    import_snapshot.verify_reader_api()
                api.assert_not_called()

    def test_reader_api_rejects_failed_health_wrong_storage_count_or_detail(self):
        record = {"id": "o-1", "summary": "Expected detail"}
        metadata = {"backend": {"storage": "postgresql", "mode": "read-only"}, "counts": {"orders": 1, "notices": 0}}
        base = [(200, {"database": "ready"}), (200, metadata), (200, {"rows": [record], "total": 1}),
                (200, record), (200, {"rows": [], "total": 0})]
        cases = [(0, (503, {"error": "Unavailable"})),
                 (1, (200, {**metadata, "backend": {"storage": "sqlite", "mode": "read-only"}})),
                 (2, (200, {"rows": [record], "total": 2})),
                 (3, (200, {"id": "o-1", "summary": "Different detail"}))]
        for index, replacement in cases:
            responses = list(base)
            responses[index] = replacement
            connection = mock.MagicMock()
            connection.execute.return_value.fetchone.return_value = ("forward_reader", "on")
            connect = mock.MagicMock()
            connect.return_value.__enter__.return_value = connection
            with self.subTest(stage=index), \
                    mock.patch.dict(sys.modules, {"psycopg": SimpleNamespace(connect=connect)}), \
                    mock.patch.object(import_snapshot, "_reader_configuration", return_value=("synthetic", "postgresql://example.invalid/fixture")), \
                    mock.patch.object(import_snapshot, "_reader_permissions", return_value={}), \
                    mock.patch.object(backend, "handle_api", side_effect=responses):
                with self.assertRaises(ValueError):
                    import_snapshot.verify_reader_api()


if __name__ == "__main__":
    unittest.main(verbosity=2)
