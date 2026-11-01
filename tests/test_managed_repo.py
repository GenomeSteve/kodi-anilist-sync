"""Managed repository index and reviewed-hash release safety tests."""
import hashlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_managed_repo as managed


class ManagedRepoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.src, self.out, self.repo = self.path / 'src', self.path / 'managed', self.path / 'repository'
        self.src.mkdir()
        self.repo.mkdir()
        approved = {}
        for addon_id, (version, filename, _) in managed.APPROVED.items():
            data = io.BytesIO()
            with ZipFile(data, 'w') as z:
                z.writestr(addon_id + '/addon.xml',
                           '<addon id="%s" version="%s" />' % (addon_id, version))
            raw = data.getvalue()
            (self.src / filename).write_bytes(raw)
            approved[addon_id] = (version, filename, managed.digest(raw))
        self.approved = patch.object(managed, 'APPROVED', approved)
        self.approved.start()
        self.addCleanup(self.approved.stop)
        (self.repo / 'addon.xml').write_text(
            '<addon id="%s" version="%s"><extension point="xbmc.addon.repository"><dir>'
            '<info>%saddons.xml</info><checksum>%saddons.xml.md5</checksum>'
            '<datadir zip="true">%s</datadir><hashes>false</hashes>'
            '</dir></extension></addon>' % (
                managed.REPOSITORY_ID, managed.REPOSITORY_VERSION,
                managed.BASE_URL, managed.BASE_URL, managed.BASE_URL))

    def test_index_matches_installable_packages(self):
        hashes = managed.make_repo(self.src, self.out, self.repo)
        addons = ET.parse(self.out / 'addons.xml').getroot()
        self.assertEqual(len(addons), 3)
        for addon in addons:
            aid, version = addon.get('id'), addon.get('version')
            package = self.out / aid / (aid + '-' + version + '.zip')
            self.assertTrue(package.exists())
            self.assertEqual(managed.digest(package.read_bytes()),
                             hashes[package.relative_to(self.out).as_posix()])
        self.assertTrue((self.out / 'repository.genomesteve.syncbeta-1.0.3.zip').exists())
        self.assertEqual(hashlib.md5((self.out / 'addons.xml').read_bytes()).hexdigest(),
                         (self.out / 'addons.xml.md5').read_text())

    def test_unreviewed_hash_never_publishes_index(self):
        path = self.src / managed.APPROVED['script.watchnixtoons.anilist'][1]
        path.write_bytes(path.read_bytes() + b'wrong')
        with self.assertRaisesRegex(ValueError, 'Unapproved'):
            managed.make_repo(self.src, self.out, self.repo)
        self.assertFalse((self.out / 'addons.xml').exists())

    def test_wrong_package_identity_never_publishes(self):
        aid = 'script.watchnixtoons.anilist'
        version, filename, _ = managed.APPROVED[aid]
        data = io.BytesIO()
        with ZipFile(data, 'w') as z:
            z.writestr(aid + '/addon.xml', '<addon id="wrong.addon" version="%s" />' % version)
        raw = data.getvalue()
        (self.src / filename).write_bytes(raw)
        managed.APPROVED[aid] = (version, filename, managed.digest(raw))
        with self.assertRaisesRegex(ValueError, 'Unexpected add-on'):
            managed.make_repo(self.src, self.out, self.repo)
        self.assertFalse((self.out / 'addons.xml').exists())

    def test_unknown_repository_endpoint_rejected(self):
        path = self.repo / 'addon.xml'
        path.write_text(path.read_text().replace('raw.githubusercontent.com', 'untrusted.example'))
        with self.assertRaisesRegex(ValueError, 'endpoint mismatch'):
            managed.make_repo(self.src, self.out, self.repo)


if __name__ == '__main__':
    unittest.main()
