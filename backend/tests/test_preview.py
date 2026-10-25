"""Checks for the local-only viewer bridge and asset boundary."""
import hashlib
import unittest
from urllib.parse import parse_qs
from serve import well_link, page_bytes, SITE


class PreviewBridgeTests(unittest.TestCase):
    registry = {'41914': {'33061055280000'}, '12': {'33053000010000', '33053000010001'}}

    def test_verified_file_and_api_bridge(self):
        status, body = well_link(parse_qs('permit=41914&api=3306105528'), self.registry)
        self.assertEqual(status, 200)
        self.assertTrue(body['matched'])
        self.assertIn('api=33061055280000', body['url'])

    def test_missing_mismatched_and_ambiguous_identities_stay_unmatched(self):
        for query in ('permit=999', 'permit=12', 'permit=41914&api=33053000010000', 'permit=41914&api=bad'):
            self.assertFalse(well_link(parse_qs(query), self.registry)[1]['matched'])
        self.assertEqual(well_link(parse_qs('permit=bad'), self.registry)[0], 400)

    def test_source_and_database_files_are_not_served(self):
        for path in ('/backend.py', '/data/forward.sqlite3', '/../../backend.py', '/schema_postgres.sql', '/.openai/hosting.json'):
            self.assertIsNone(page_bytes(path), path)

    def test_selection_hook_exists_only_in_served_preview(self):
        original = (SITE/'viewer/app.js').read_bytes()
        served, mime = page_bytes('/viewer/app.js')
        self.assertIn(b'previewQuery', served)
        self.assertNotIn(b'previewQuery', original)
        self.assertEqual(hashlib.sha256(original).hexdigest(), hashlib.sha256((SITE/'viewer/app.js').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
