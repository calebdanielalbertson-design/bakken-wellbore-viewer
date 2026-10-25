"""Meaningful join, alias, DBF and alignment fixtures; no external dependencies."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from prepare_operators import (build_sidecar, group_for, normalized_api10,
                               normalized_permit, read_wells, resolve_operator)


class OperatorJoinTests(unittest.TestCase):
    def test_normalized_identifiers_and_strict_mismatch(self):
        self.assertEqual(normalized_permit('000123.00'), '123')
        self.assertEqual(normalized_permit('123a'), '')
        self.assertEqual(normalized_api10('33-053-01234-00-01'), '3305301234')
        self.assertEqual(normalized_api10('3305301234'), '3305301234')
        self.assertEqual(normalized_api10('bad3305301234'), '')
        records = {'123':[{'permit':'123', 'api':'3305301234', 'operator':'XTO Energy Inc'}]}
        self.assertEqual(resolve_operator({'permit':'00123', 'api':'33-053-01234-01-00'}, records),
                         ('XTO Energy Inc', 'matchedPermitAPI'))
        self.assertEqual(resolve_operator({'permit':'123', 'api':'33053099990000'}, records), ('', 'apiMismatch'))
        self.assertEqual(resolve_operator({'permit':'123', 'api':''}, records),
                         ('XTO Energy Inc', 'matchedUniquePermitMissingAPI'))

    def test_duplicate_records_and_absence_are_not_guessed(self):
        rows = [{'permit':'5', 'api':'3305301234', 'operator':name} for name in ('HESS', 'XTO')]
        self.assertEqual(resolve_operator({'permit':'5', 'api':'33053012340000'}, {'5':rows}),
                         ('', 'ambiguousOperator'))
        self.assertEqual(resolve_operator({'permit':'5', 'api':''}, {'5':rows}), ('', 'ambiguousPermit'))
        identical = [rows[0], dict(rows[0])]
        self.assertEqual(resolve_operator({'permit':'5', 'api':'33053012340000'}, {'5':identical}),
                         ('HESS', 'matchedPermitAPI'))
        absent = {'5':[{'permit':'5', 'api':'', 'operator':'Hess'}]}
        self.assertEqual(resolve_operator({'permit':'5', 'api':'3305301234'}, absent),
                         ('Hess', 'matchedUniquePermitMissingAPI'))
        self.assertEqual(resolve_operator({'permit':'6', 'api':'3305301234'}, absent), ('', 'permitAbsent'))

    def test_legend_specificity_and_requested_colors(self):
        self.assertEqual(group_for('PETRO-HUNT DAKOTA, LLC')[0], 'petro-hunt-dakota')
        self.assertEqual(group_for('PETRO-HUNT, L.L.C.')[0], 'petro-hunt')
        self.assertEqual(group_for('Hess Bakken Investments II, LLC')[2], '#5dca1b')
        self.assertEqual(group_for('CHEVRON USA, INC.')[0], 'hess-chevron')
        self.assertEqual(group_for('XTO ENERGY INC')[2], '#ffb000')
        self.assertNotEqual(group_for('XTO ENERGY INC')[2], group_for('HESS')[2])
        self.assertEqual(group_for('CHORD ENERGY')[0], group_for('Whiting Oil and Gas')[0])
        self.assertEqual(group_for('AMERADA HESS CORPORATION')[0], 'hess-chevron')
        self.assertEqual(group_for('LIME ROCK RESOURCES III-A, L.P.')[0], 'lime-rock-iii-a')
        self.assertNotEqual(group_for('LIME ROCK RESOURCES V-A, L.P.')[0], 'lime-rock-iii-a')
        self.assertTrue(group_for('WPX ENERGY WILLISTON, LLC')[0].startswith('operator-'))
        self.assertEqual(group_for('Odd Co.')[0], group_for('ODD-CO')[0])
        self.assertEqual(group_for('Odd Co.')[2], group_for('ODD-CO')[2])

    def test_raw_name_preservation_counts_and_branch_alignment(self):
        manifest = {'stations':90, 'overviewSegments':12, 'sourceCRS':'NAD83', 'origin':[-103,48],
                    'wells':[{'permit':'1','api':'33053000010000'},
                             {'permit':'1','api':'33053000010001'},
                             {'permit':'2','api':'33053000020000'},
                             {'permit':'3','api':'33053000030000'},
                             {'permit':'4','api':'33053000040000'}]}
        rows = [{'permit':'1', 'api':'3305300001', 'operator':'XTO ENERGY INC'},
                {'permit':'2', 'api':'3305300002', 'operator':'Hess Bakken Investments II, LLC'},
                {'permit':'3', 'api':'3305300003', 'operator':'CHEVRON USA, INC.'}]
        result = build_sidecar(manifest, rows, {'sourceDate':'2026-10-17'})
        self.assertEqual(result['survey']['branchCount'], 5)
        self.assertEqual(len(result['branchGroups']), len(result['branchNames']))
        self.assertEqual([g['id'] for g in result['groups']], list(range(len(result['groups']))))
        groups = {g['key']:g for g in result['groups']}
        self.assertEqual(groups['xto']['wellCount'], 1)
        self.assertEqual(groups['xto']['branchCount'], 2)
        self.assertEqual(groups['hess-chevron']['wellCount'], 2)
        self.assertEqual(groups['hess-chevron']['rawNames'], ['CHEVRON USA, INC.', 'Hess Bakken Investments II, LLC'])
        self.assertEqual(sum(g['branchCount'] for g in result['groups']), 5)
        self.assertEqual(result['names'][result['branchNames'][1]], 'XTO ENERGY INC')
        self.assertEqual(result['names'][result['branchNames'][3]], 'CHEVRON USA, INC.')
        self.assertEqual(result['groups'][result['branchGroups'][4]]['key'], 'unknown')
        self.assertEqual(result['joinStats']['matchedBranches'], 4)
        self.assertEqual(result['joinStats']['unknownBranches'], 1)
        # Reordered source records produce the same model and branch references.
        self.assertEqual(result, build_sidecar(manifest, list(reversed(rows)), {'sourceDate':'2026-10-17'}))
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_readonly_dbf_reader_skips_deleted_and_preserves_operator(self):
        fields = [('fileno','N',10), ('api','C',14), ('operator','C',100)]
        start, step = 32+32*len(fields)+1, 1+sum(f[2] for f in fields)
        content = bytearray(32)
        content[0] = 3
        struct.pack_into('<IHH', content, 4, 3, start, step)
        for name, kind, size in fields:
            descriptor = bytearray(32)
            descriptor[:len(name)] = name.encode()
            descriptor[11] = ord(kind)
            descriptor[16] = size
            content.extend(descriptor)
        content.extend(b'\r')
        for deleted, values in [(False,['0007','33053000070000','Mixed-Case Operator, L.L.C.']),
                                (True,['8','33053000080000','Deleted Operator']),
                                (False,['9','',''])]:
            content.extend(b'*' if deleted else b' ')
            for (_,_,width), value in zip(fields, values):
                content.extend(value.encode('cp1252').ljust(width,b' '))
        content.extend(b'\x1a')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as directory:
            self.assertEqual(Path(directory).resolve().parent, Path(__file__).resolve().parent)
            path = Path(directory)/'wells.dbf'
            path.write_bytes(content)
            original = path.read_bytes()
            rows, audit = read_wells(path)
            self.assertEqual(rows[0], {'permit':'7','api':'3305300007','operator':'Mixed-Case Operator, L.L.C.'})
            self.assertEqual(len(rows), 2)
            self.assertEqual(audit['deletedSourceRecords'], 1)
            self.assertEqual(path.read_bytes(), original)


if __name__ == '__main__':
    unittest.main(verbosity=2)
