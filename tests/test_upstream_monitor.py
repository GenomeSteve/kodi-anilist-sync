"""Upstream monitor must detect source drift, not silently change the provider."""
import base64
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import check_wnt2_upstream as check


class UpstreamMonitorTests(unittest.TestCase):
    def fixture(self, *, newer=False, repack=False, author=False):
        xml = '<addon id="plugin.video.watchnixtoons2.kodi19" version="0.3"/>'
        encoded = base64.b64encode(xml.encode()).decode()
        def fetch(url):
            if url == check.PUBLISHED:
                return [{'name':'plugin.video.watchnixtoons2-0.14.24.zip',
                         'sha': 'a'*40 if repack else check.BASELINE_PACKAGE_SHA},
                        {'name':'addon.xml'},
                        {'name':'plugin.video.watchnixtoons2-0.14.25.zip',
                         'sha': 'b'*40}] if newer else [
                        {'name':'plugin.video.watchnixtoons2-0.14.24.zip',
                         'sha': 'a'*40 if repack else check.BASELINE_PACKAGE_SHA}]
            if 'repo.dexe' in url:
                return {'sha': check.BASELINE_XML_SHA}
            if 'lib/plugin.py' in url:
                return {'sha': 'c'*40 if author else check.BASELINE_DEV_CODE_SHA}
            return {'sha': check.BASELINE_DEV_XML_SHA,
                    'encoding':'base64','content':encoded}
        return fetch

    def test_unchanged_upstream_is_silent(self):
        result = check.inspect(self.fixture())
        self.assertFalse(result['changed'])
        self.assertEqual(result['alerts'], [])

    def test_new_published_release_is_flagged(self):
        result = check.inspect(self.fixture(newer=True))
        self.assertTrue(result['changed'])
        self.assertEqual(result['published_version'], '0.14.25')

    def test_repacked_existing_release_is_flagged(self):
        result = check.inspect(self.fixture(repack=True))
        self.assertIn('changed bytes', ' '.join(result['alerts']))

    def test_developer_source_change_requires_review(self):
        result = check.inspect(self.fixture(author=True))
        self.assertTrue(result['changed'])
        self.assertIn('manual compatibility review', ' '.join(result['alerts']))
        self.assertEqual(result['developer_addon_id'], 'plugin.video.watchnixtoons2.kodi19')

    def test_stable_fingerprint_deduplicates_alerts(self):
        self.assertEqual(check.inspect(self.fixture(author=True))['marker'],
                         check.inspect(self.fixture(author=True))['marker'])
        self.assertNotEqual(check.inspect(self.fixture())['marker'],
                            check.inspect(self.fixture(author=True))['marker'])

    def test_rejects_unapproved_url(self):
        with self.assertRaises(ValueError):
            check.read_github('https://attacker.example/get')


if __name__ == '__main__':
    unittest.main()
