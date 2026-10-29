"""Interaction tests: no API mutation without explicit consent or stale recheck."""
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / 'src' / 'script.watchnixtoons.anilist'
sys.path.insert(0, str(BASE))


class FakeDialog:
    def __init__(self, yes, selections):
        self.yes = list(yes)
        self.selections = list(selections)
        self.messages = []
    def yesno(self, *args, **kwargs):
        return self.yes.pop(0)
    def select(self, *args, **kwargs):
        return self.selections.pop(0)
    def ok(self, *args, **kwargs):
        self.messages.append(('ok', args))
    def textviewer(self, *args, **kwargs):
        self.messages.append(('preview', args))
    def input(self, *args, **kwargs):
        return '0'


class UIRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = self.tmp.name
        self.xbmcaddon = ModuleType('xbmcaddon')
        class Addon:
            def __init__(s, addon_id=None): pass
            def getAddonInfo(s, field): return self.profile if field == 'profile' else ''
            def getSetting(s, field): return 'test-token' if field == 'token' else 'true'
        self.xbmcaddon.Addon = Addon
        self.xbmcgui = ModuleType('xbmcgui')
        self.xbmcgui.INPUT_NUMERIC = 1
        self.xbmcgui.Dialog = lambda: self.dialog
        self.xbmcvfs = ModuleType('xbmcvfs')
        self.xbmcvfs.listdir = lambda path: ([], ['MyVideos121.db'])
        self.xbmcvfs.translatePath = lambda p: p.replace('special://database', self.profile).replace('special://profile', self.profile)
        self.dialog = FakeDialog([], [])
        self.patchmod = patch.dict(sys.modules, {'xbmcaddon': self.xbmcaddon,
                                                 'xbmcgui': self.xbmcgui,
                                                 'xbmcvfs': self.xbmcvfs})
        self.patchmod.start()
        sys.modules.pop('historical_ui', None)
        self.ui = importlib.import_module('historical_ui')
        self.group = {'naruto|s1': {'key': 'naruto|s1', 'title': 'naruto', 'season': 1,
                                   'episodes': [1, 2, 3]}}
        self.anime = {'id': 77, 'episodes': 12, 'status': 'FINISHED',
                      'mediaListEntry': {'id': 88, 'progress': 0, 'status': 'CURRENT'}}
        (Path(self.profile) / 'mappings.json').write_text(json.dumps({'naruto|s1':
            {'id': 77, 'title': 'Naruto', 'offset': 0}}))

    def tearDown(self):
        self.patchmod.stop()
        sys.modules.pop('historical_ui', None)
        self.tmp.cleanup()

    def test_scan_requires_permission(self):
        self.ui.DIALOG = FakeDialog([False], [])
        with patch.object(self.ui, 'read_history') as read:
            self.ui.run(lambda title: None)
        read.assert_not_called()

    def test_import_is_preview_only_if_user_cancels(self):
        self.ui.DIALOG = FakeDialog([True, True, False], [0, 1])
        with patch.object(self.ui, 'read_history', return_value=self.group), \
             patch.object(self.ui, 'details', return_value=self.anime), \
             patch.object(self.ui, 'save') as save:
            self.ui.run(lambda title: None)
        save.assert_not_called()
        self.assertTrue(any(t == 'preview' for t, _ in self.ui.DIALOG.messages))

    def test_confirmed_import_only_one_save(self):
        self.ui.DIALOG = FakeDialog([True, True, True], [0, 1])
        with patch.object(self.ui, 'read_history', return_value=self.group), \
             patch.object(self.ui, 'details', return_value=self.anime) as api, \
             patch.object(self.ui, 'save', return_value={'progress': 3}) as save:
            self.ui.run(lambda title: None)
        self.assertEqual(api.call_count, 2)
        save.assert_called_once_with(77, 88, 3, 'CURRENT', 'test-token')

    def test_changed_anilist_progress_fails_closed(self):
        self.ui.DIALOG = FakeDialog([True, True, True], [0, 1])
        changed = dict(self.anime, mediaListEntry={'id': 88, 'progress': 1, 'status': 'CURRENT'})
        with patch.object(self.ui, 'read_history', return_value=self.group), \
             patch.object(self.ui, 'details', side_effect=[self.anime, changed]), \
             patch.object(self.ui, 'save') as save:
            self.ui.run(lambda title: None)
        save.assert_not_called()
        self.assertTrue(any('progress changed' in str(arg).lower() for typ, args in self.ui.DIALOG.messages for arg in args))

    def test_ignored_mapping_cannot_import(self):
        (Path(self.profile)/'mappings.json').write_text(json.dumps({'naruto|s1': {'ignore': True}}))
        self.ui.DIALOG = FakeDialog([True], [0, 1])
        with patch.object(self.ui, 'read_history', return_value=self.group), \
             patch.object(self.ui, 'details') as api, \
             patch.object(self.ui, 'save') as save:
            self.ui.run(lambda title: None)
        save.assert_not_called()
        api.assert_not_called()

    def test_missing_ani_list_token_no_scan(self):
        self.xbmcaddon.Addon.getSetting = lambda self, field: ''
        self.ui.DIALOG = FakeDialog([True], [])
        with patch.object(self.ui, 'read_history') as read:
            self.ui.run(lambda title: None)
        read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
