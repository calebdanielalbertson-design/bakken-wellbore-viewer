"""Portable identity, ambiguity, encoding and immutable-input tests."""
from datetime import date
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from prepare_well_names import (build_sidecar, normalized_api, normalized_permit,
                                prepare, read_wells, resolve_name)


def fixture_dbf(path, rows):
    fields = [('fileno', 'N', 10), ('api', 'C', 14), ('well_name', 'C', 80)]
    start, step = 32 + 32 * len(fields) + 1, 1 + sum(f[2] for f in fields)
    content = bytearray(32)
    content[0] = 3
    struct.pack_into('<IHH', content, 4, len(rows), start, step)
    for name, kind, width in fields:
        d = bytearray(32)
        d[:len(name)] = name.encode()
        d[11], d[16] = ord(kind), width
        content.extend(d)
    content.extend(b'\r')
    for deleted, values in rows:
        content.extend(b'*' if deleted else b' ')
        for (_, _, width), value in zip(fields, values):
            encoded = value.encode('utf8')
            if len(encoded) > width:
                raise ValueError('Fixture field too wide')
            content.extend(encoded.ljust(width, b' '))
    content.extend(b'\x1a')
    path.write_bytes(content)
    path.with_suffix('.cpg').write_text('UTF-8')


class WellNameTests(unittest.TestCase):
    def setUp(self):
        self.rows = {'7': [dict(permit='7', api='33053000070000', name='ÅSE 7-1H')]}

    def test_identifiers_and_no_digit_extraction_guesses(self):
        self.assertEqual(normalized_permit('0007.00'), '7')
        self.assertEqual(normalized_permit('permit 7'), '')
        self.assertEqual(normalized_permit('0'), '')
        self.assertEqual(normalized_api('33-053-00007-00-01'), '33053000070001')
        self.assertEqual(normalized_api('3305300007'), '3305300007')
        self.assertEqual(normalized_api('API3305300007'), '')

    def test_exact_and_unique_base_keep_raw_names(self):
        self.assertEqual(resolve_name({'permit': '007', 'api': '33053000070000'}, self.rows),
                         ('ÅSE 7-1H', 'matchedExactAPI14'))
        self.assertEqual(resolve_name({'permit': '7', 'api': '33053000070002'}, self.rows),
                         ('ÅSE 7-1H', 'matchedBaseAPI10'))
        self.assertEqual(resolve_name({'permit': '7', 'api': '3305300007'}, self.rows),
                         ('ÅSE 7-1H', 'matchedBaseAPI10'))

    def test_no_permit_only_or_other_permit_or_api_match(self):
        self.assertEqual(resolve_name({'permit': '7', 'api': ''}, self.rows)[1], 'invalidAPI')
        self.assertEqual(resolve_name({'permit': '8', 'api': '33053000070000'}, self.rows)[1], 'permitAbsent')
        self.assertEqual(resolve_name({'permit': '7', 'api': '33053000080000'}, self.rows)[1], 'apiMismatch')
        rows = {'7': [dict(permit='7', api='', name='KNOWN NAME')]}
        self.assertEqual(resolve_name({'permit': '7', 'api': '33053000070000'}, rows), ('', 'sourceAPIAbsent'))

    def test_exact_precedes_ambiguous_base_and_conflicts_are_missing(self):
        rows = {'7': self.rows['7'] + [dict(permit='7', api='33053000070001', name='OTHER NAME')]}
        self.assertEqual(resolve_name({'permit': '7', 'api': '33053000070000'}, rows),
                         ('ÅSE 7-1H', 'matchedExactAPI14'))
        self.assertEqual(resolve_name({'permit': '7', 'api': '33053000070002'}, rows), ('', 'conflictingBaseNames'))
        rows['7'].append(dict(permit='7', api='33053000070000', name='CONFLICT'))
        self.assertEqual(resolve_name({'permit': '7', 'api': '33053000070000'}, rows), ('', 'conflictingExactNames'))

    def test_duplicate_same_name_is_safe_but_blank_not_invented(self):
        rows = {'7': self.rows['7'] * 2}
        self.assertEqual(resolve_name({'permit': '7', 'api': '33053000070002'}, rows)[0], 'ÅSE 7-1H')
        rows['7'].append(dict(permit='7', api='33053000070001', name=''))
        self.assertEqual(resolve_name({'permit': '7', 'api': '33053000070002'}, rows), ('', 'conflictingBaseNames'))
        self.assertEqual(resolve_name({'permit': '7', 'api': '33053000070001'}, rows), ('', 'nameAbsent'))

    def test_stable_ids_not_array_positions_and_hash_required(self):
        manifest = dict(stations=10, sourceCRS='NAD83', origin=[-103, 48],
                        wells=[dict(id=21, permit='7', api='33053000070000'),
                               dict(id=4, permit='7', api='33053000070001')])
        result = build_sidecar(manifest, self.rows['7'], 'a' * 64, {})
        self.assertEqual(result['names'], {'21': 'ÅSE 7-1H', '4': 'ÅSE 7-1H'})
        self.assertEqual(result['coverage']['matchedWellIdentities'], 1)
        self.assertEqual(result['coverage']['byReason'], {'matchedBaseAPI10': 1, 'matchedExactAPI14': 1})
        self.assertEqual(result['survey']['manifestSHA256'], 'a' * 64)
        with self.assertRaises(ValueError):
            build_sidecar(manifest, self.rows['7'], '', {})
        manifest['wells'][1]['id'] = 21
        with self.assertRaises(ValueError):
            build_sidecar(manifest, self.rows['7'], 'a' * 64, {})

    def test_dbf_utf8_deleted_padding_and_truncation(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            path = Path(tmp) / 'wells.dbf'
            fixture_dbf(path, [(False, ['7', '33053000070000', 'ÅSE 7-1H']),
                               (True, ['8', '33053000080000', 'DELETED'])])
            original = path.read_bytes()
            rows, audit, codec, _ = read_wells(path)
            self.assertEqual(rows, self.rows['7'])
            self.assertEqual(audit['deletedSourceRecords'], 1)
            self.assertEqual(codec, 'utf-8')
            self.assertEqual(path.read_bytes(), original)
            path.write_bytes(original[:-30])
            with self.assertRaises(ValueError):
                read_wells(path)

    def test_preparation_hash_guard_and_existing_bytes_untouched(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as tmp:
            folder = Path(tmp)
            dbf = folder / 'wells.dbf'
            fixture_dbf(dbf, [(False, ['7', '33053000070000', 'ÅSE 7-1H'])])
            manifest = dict(stations=10, sourceCRS='NAD83', origin=[-103, 48],
                            wells=[dict(id=12, permit='7', api='33053000070000')])
            mp = folder / 'manifest.json'
            mp.write_text(json.dumps(manifest))
            payload = b'untouched production bytes'
            existing = folder / 'oil.bin'
            existing.write_bytes(payload)
            before = {p.name: p.read_bytes() for p in folder.iterdir()}
            result, output = prepare(dbf, folder, date(2026, 10, 17))
            self.assertEqual(result['survey']['manifestSHA256'], hashlib.sha256(before['manifest.json']).hexdigest())
            self.assertEqual(result['names'], {'12': 'ÅSE 7-1H'})
            self.assertEqual(output.name, 'well-names.json')
            for name, content in before.items():
                self.assertEqual((folder / name).read_bytes(), content)
            self.assertNotIn(str(folder), output.read_text())
            previous = output.read_bytes()
            with self.assertRaises(ValueError):
                prepare(dbf, folder, date(2026, 10, 17), expected_manifest_sha256='0' * 64)
            self.assertEqual(output.read_bytes(), previous)
            with self.assertRaises(ValueError):
                prepare(dbf, folder, date(2026, 10, 17), output=folder / 'manifest.json')
            self.assertEqual(mp.read_bytes(), before['manifest.json'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
