"""Offline adapter contracts only; these do not verify a PostgreSQL server.

The fake driver records SQL ordering, COPY values, transaction boundaries and
connection selection. Real DDL/type adaptation/role privileges still require the
separate staging verification against PostgreSQL.
"""
from __future__ import annotations
import contextlib
import gzip
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
import wells_backend
import wells_store as store
from test_wells_store_api import fixture


class SQL(str):
    def format(self, *args):
        return SQL(str(self).format(*args))

    def join(self, values):
        return SQL(str(self).join(map(str, values)))


class Identifier(SQL):
    def __new__(cls, value):
        return super().__new__(cls, '"' + str(value).replace('"', '""') + '"')


class CursorResult:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class Copy:
    def __init__(self, connection, statement):
        self.connection = connection
        self.statement = str(statement)
        self.table = re.search(r'COPY\s+"?([a-z_]+)', self.statement).group(1)

    def __enter__(self):
        self.connection.events.append(('copy', self.statement))
        return self

    def write_row(self, values):
        self.connection.rows.setdefault(self.table, []).append(tuple(values))

    def __exit__(self, *args):
        return False


class Connection:
    def __init__(self, *, existing=False, orphan=False, wrong_count=False, partial=False, user='owner', readonly='off'):
        self.existing, self.orphan, self.wrong_count, self.partial = existing, orphan, wrong_count, partial
        self.rows, self.events = {}, []
        self.user, self.readonly = user, readonly
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.committed = kind is None
        self.rolled_back = kind is not None
        return False

    def cursor(self):
        return self

    def copy(self, statement):
        return Copy(self, statement)

    def execute(self, statement, parameters=None):
        text = str(statement)
        self.events.append(('execute', text, parameters))
        if text.startswith("SELECT current_user,current_setting('transaction_read_only')"):
            return CursorResult((self.user, self.readonly))
        if "SELECT to_regclass('public.well_app')" in text:
            return CursorResult(('well_app' if self.existing else None,))
        if text.startswith('SELECT to_regclass('):
            return CursorResult(('well_registry' if self.partial and parameters == ('public.well_registry',) else None,))
        if text.startswith('SELECT app_name,schema_version'):
            return CursorResult((store.APP, store.VERSION))
        if text.startswith('SELECT manifest_sha256') or text.startswith('SELECT row_count'):
            return CursorResult()
        if text.startswith('SELECT COUNT(*)'):
            table = re.search(r'FROM\s+"?([a-z_]+)', text).group(1)
            count = len(self.rows.get(table, []))
            return CursorResult((count + 1 if self.wrong_count else count,))
        if text.startswith('SELECT shobj_description'):
            return CursorResult(('bakken-forward-preview dedicated read-only role v1',))
        if text.startswith('SELECT has_table_privilege'):
            return CursorResult((True, False))
        if text.startswith('SELECT 1 FROM well_production'):
            return CursorResult(('orphan',) if self.orphan else None)
        return CursorResult()


class PostgresContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pg-contract-', dir=PROJECT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = fixture(self.root / 'bundle')
        # Explicit source-to-API bindings are mandatory for shared production.
        path = self.bundle / 'release.json'
        metadata = json.loads(path.read_text())
        metadata['production']['identities'] = {'1': '33001000010000'}
        path.write_text(json.dumps(metadata))

    def driver(self, connection):
        module = types.ModuleType('psycopg')
        module.connect = mock.Mock(return_value=connection)
        module.sql = types.SimpleNamespace(SQL=SQL, Identifier=Identifier)
        return module

    def test_bootstrap_copy_and_activation_are_one_transaction(self):
        connection = Connection()
        driver = self.driver(connection)
        with mock.patch.dict(sys.modules, {'psycopg': driver}):
            result = store.import_postgres(self.bundle, 'postgresql://owner:explicit@private/db', initialize=True, grant_reader=True)
        self.assertEqual(result['storage'], 'postgresql')
        self.assertTrue(connection.committed)
        self.assertFalse(connection.rolled_back)
        executed = [e[1] for e in connection.events if e[0] == 'execute']
        self.assertTrue(any('pg_advisory_xact_lock' in text for text in executed))
        self.assertTrue(executed[-1].startswith('INSERT INTO well_active'))
        self.assertTrue(any(text.startswith('CREATE TABLE well_app') or 'CREATE TABLE well_app' in text for text in executed))
        for table, _columns in store.TABLES.values():
            self.assertIn(table, connection.rows)
        self.assertEqual(len(connection.rows['well_production']), 3)
        invalid = [r for r in connection.rows['well_production'] if r[-2] == 'invalid'][0]
        self.assertIsNone(invalid[3])
        reported_zero = [r for r in connection.rows['well_production'] if r[3] == '0'][0]
        self.assertEqual(reported_zero[-2], 'reported')
        self.assertEqual(connection.rows['well_production_identities'][0][1:], ('1', '33001000010000'))

    def test_partial_schema_is_refused_before_create_or_copy(self):
        connection = Connection(partial=True)
        with mock.patch.dict(sys.modules, {'psycopg': self.driver(connection)}), self.assertRaisesRegex(ValueError, 'partial'):
            store.import_postgres(self.bundle, 'postgresql://owner:explicit@private/db', initialize=True)
        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.rows)
        self.assertFalse(any('CREATE TABLE' in e[1] for e in connection.events))

    def test_bad_counts_or_identity_rollback_without_activation(self):
        for options in ({'wrong_count': True}, {'orphan': True}):
            with self.subTest(options=options):
                connection = Connection(existing=True, **options)
                with mock.patch.dict(sys.modules, {'psycopg': self.driver(connection)}), self.assertRaises(ValueError):
                    store.import_postgres(self.bundle, 'postgresql://owner:explicit@private/db')
                self.assertTrue(connection.rolled_back)
                self.assertFalse(any(e[1].startswith('INSERT INTO well_active') for e in connection.events if e[0] == 'execute'))

    def test_reader_or_read_only_import_connection_rejected_before_schema_checks(self):
        for options in ({'user': 'forward_reader'}, {'readonly': 'on'}):
            with self.subTest(options=options):
                connection = Connection(**options)
                with mock.patch.dict(sys.modules, {'psycopg': self.driver(connection)}), self.assertRaisesRegex(ValueError, 'writable import'):
                    store.import_postgres(self.bundle, 'postgresql://owner:explicit@private/db', initialize=True)
                self.assertEqual(len(connection.events), 1)
                self.assertTrue(connection.rolled_back)

    def test_cli_uses_separate_owner_connection_and_never_reader_fallback(self):
        argv = ['wells_store.py', str(self.bundle), '--postgres', '--initialize', '--confirm-staging-import']
        environment = {'RAILWAY_ENVIRONMENT_NAME': 'staging', 'DATABASE_URL': 'postgresql://forward_reader@private/db',
                       'PGPASSWORD': 'reader-sentinel-secret', 'BAKKEN_IMPORT_DATABASE_URL': 'postgresql://owner:owner-sentinel@private/db'}
        with mock.patch.object(sys, 'argv', argv), mock.patch.dict(os.environ, environment), mock.patch.object(store, 'import_postgres', return_value={'ok': True}) as imported, contextlib.redirect_stdout(io.StringIO()) as output:
            store.main()
        self.assertEqual(imported.call_args.args[1], environment['BAKKEN_IMPORT_DATABASE_URL'])
        self.assertNotIn('sentinel', output.getvalue())
        with mock.patch.object(sys, 'argv', argv), mock.patch.dict(os.environ, {**environment, 'BAKKEN_IMPORT_DATABASE_URL': ''}), mock.patch.object(store, 'import_postgres') as imported, contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
            store.main()
        imported.assert_not_called()
        self.assertNotIn('sentinel', error.getvalue())

    def test_api_connect_enforces_read_only_before_reading_active_release(self):
        connection = mock.Mock()
        connection.execute.side_effect = [CursorResult(), CursorResult({'app_name': store.APP, 'schema_version': store.VERSION}),
            CursorResult({'release_id': 'release_fixture_001', 'production_id': 'production_fixture',
                          'manifest_sha256': 'a' * 64, 'imported_at': '2026-10-17', 'payload': {}})]
        driver = self.driver(connection)
        rows = types.ModuleType('psycopg.rows')
        rows.dict_row = object()
        with mock.patch.dict(sys.modules, {'psycopg': driver, 'psycopg.rows': rows}), mock.patch.dict(os.environ, {'DATABASE_URL': 'postgresql://forward_reader@private/db'}):
            with wells_backend.connect() as (_db, release, _metadata):
                self.assertEqual(release['release_id'], 'release_fixture_001')
        self.assertIn('default_transaction_read_only=on', driver.connect.call_args.kwargs['options'])
        self.assertEqual(connection.execute.call_args_list[0].args[0], 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        connection.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
