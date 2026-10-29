"""Live-tracking and metadata contract regression tests, without real Kodi."""
import importlib
import os
import sys
import tempfile
import time
import json
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / 'src' / 'script.watchnixtoons.anilist'
sys.path.insert(0, str(BASE))
from core import desired_progress, exact_candidate, mapping_key, source_matches, parse_token


class CoreRegression(unittest.TestCase):
    def test_mapping_key_normalises_title(self):
        self.assertEqual(mapping_key('My Anime English Dubbed', 1), 'my anime|s1')

    def test_source_identity_rejects_different_anime(self):
        self.assertFalse(source_matches('One Piece', 'Naruto'))

    def test_auto_mapping_only_exact_unique_first_season(self):
        entry = {'id': 12, 'title': {'english': 'Naruto', 'romaji': 'Naruto'}, 'episodes': 24}
        self.assertEqual(exact_candidate('Naruto', 1, 3, [entry])['id'], 12)
        self.assertIsNone(exact_candidate('Naruto', 2, 3, [entry]))
        self.assertIsNone(exact_candidate('Naruto', 1, 3, [entry, dict(entry, id=13)]))

    def test_live_progress_never_decreases(self):
        self.assertIsNone(desired_progress({'progress': 9}, 7, 12, 'FINISHED'))

    def test_live_final_episode_can_complete(self):
        self.assertEqual(desired_progress({'progress': 9}, 12, 12, 'FINISHED'), (12, 'COMPLETED'))

    def test_oauth_token_parser(self):
        self.assertEqual(parse_token('https://a.test/path#access_token=abc123&token_type=Bearer'), 'abc123')

    def test_service_does_not_reference_history_importer(self):
        service_source = (BASE/'service.py').read_text()
        self.assertNotIn('history_import', service_source)
        self.assertNotIn('historical_ui', service_source)

    def test_existing_watched_parser_has_not_been_modified(self):
        from watched_db import parse_watched_url
        a = parse_watched_url('plugin://plugin.video.watchnixtoons2/?action=actionResolve&url=%2Fnaruto-episode-23')
        self.assertEqual(a, {'title': 'naruto', 'season': 1, 'episode': 23})
        self.assertIsNone(parse_watched_url('plugin://plugin.video.thecrew/?action=actionResolve&url=%2Fnaruto-episode-23'))


class LiveServiceRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.profile = self.tmp.name
        base = Path(self.profile)
        (base/'database').mkdir(exist_ok=True)
        self.fake_addon = ModuleType('xbmcaddon')
        class Addon:
            def __init__(s, addon_id=None):
                pass
            def getAddonInfo(s, field):
                return self.profile if field == 'profile' else ''
            def getSetting(s, field):
                return {'enabled': 'true', 'threshold': '85', 'token': 'fake-token'}[field]
        self.fake_addon.Addon = Addon
        self.fake_vfs = ModuleType('xbmcvfs')
        self.fake_vfs.translatePath = lambda s: s.replace('special://profile', self.profile).replace('special://database', self.profile + '/database')
        self.fake_vfs.listdir = lambda s: ([], ['MyVideos121.db'])
        self.fake_xbmc = ModuleType('xbmc')
        self.fake_xbmc.LOGINFO = 1
        self.fake_xbmc.LOGWARNING = 2
        self.fake_xbmc.LOGERROR = 3
        self.fake_xbmc.log = lambda *args, **kwargs: None
        class Player:
            def isPlayingVideo(s):
                return False
        self.fake_xbmc.Player = Player
        self.patches = [patch.dict(sys.modules, {'xbmc': self.fake_xbmc,
                                                  'xbmcaddon': self.fake_addon,
                                                  'xbmcvfs': self.fake_vfs})]
        for p in self.patches:
            p.start()
        sys.modules.pop('service', None)
        self.svc = importlib.import_module('service')

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        sys.modules.pop('service', None)
        self.tmp.cleanup()

    def test_fallback_queues_existing_watched_tick(self):
        tracker = self.svc.Tracker()
        event = {'title': 'naruto', 'season': 1, 'episode': 3}
        with patch.object(self.svc, 'recent_watched', return_value=[event]), \
             patch.object(tracker, 'reconcile'):
            tracker.tick(time.time())
        self.assertIn('naruto|s1|e3', tracker.state['pending'])
        self.assertEqual(tracker.state['pending']['naruto|s1|e3']['episode'], 3)

    def test_repeated_scan_does_not_duplicate(self):
        tracker = self.svc.Tracker()
        event = {'title': 'naruto', 'season': 1, 'episode': 3}
        with patch.object(self.svc, 'recent_watched', return_value=[event]), \
             patch.object(tracker, 'reconcile'):
            tracker.tick(1000)
            tracker.tick(1022)
        self.assertEqual(len(tracker.state['pending']), 1)

    def test_reconcile_matched_series_updates_to_anilist(self):
        tracker = self.svc.Tracker()
        tracker.state['pending']['naruto|s1|e3'] = {'title': 'naruto', 'season': 1, 'episode': 3, 'key': 'naruto|s1'}
        with open(self.svc.MAPPINGS_FILE, 'w') as f:
            json.dump({'naruto|s1': {'id': 77, 'title': 'Naruto', 'offset': 0}}, f)
        before = {'id': 77, 'episodes': 12, 'status': 'FINISHED',
                  'mediaListEntry': {'id': 98, 'progress': 2, 'status': 'CURRENT'}}
        with patch.object(self.svc, 'details', return_value=before), \
             patch.object(self.svc, 'save', return_value={'progress': 3}) as saving:
            tracker.reconcile()
        self.assertIn('naruto|s1|e3', tracker.state['done'])
        self.assertNotIn('naruto|s1|e3', tracker.state['pending'])
        saving.assert_called_once_with(77, 98, 3, 'CURRENT', 'fake-token')

    def test_reconcile_unmapped_title_needs_review(self):
        tracker = self.svc.Tracker()
        tracker.state['pending']['naruto|s1|e3'] = {'title': 'naruto', 'season': 1, 'episode': 3, 'key': 'naruto|s1'}
        with patch.object(self.svc, 'search', return_value=[]):
            tracker.reconcile()
        self.assertEqual(len(tracker.state['pending']), 1)

    def test_reconcile_does_not_reduce_progress(self):
        tracker = self.svc.Tracker()
        tracker.state['pending']['naruto|s1|e3'] = {'title': 'naruto', 'season': 1, 'episode': 3, 'key': 'naruto|s1'}
        with open(self.svc.MAPPINGS_FILE, 'w') as f:
            json.dump({'naruto|s1': {'id': 77, 'title': 'Naruto', 'offset': 0}}, f)
        before = {'id': 77, 'episodes': 12, 'status': 'FINISHED',
                  'mediaListEntry': {'id': 98, 'progress': 4, 'status': 'CURRENT'}}
        with patch.object(self.svc, 'details', return_value=before), \
             patch.object(self.svc, 'save') as saving:
            tracker.reconcile()
        saving.assert_not_called()
        self.assertIn('naruto|s1|e3', tracker.state['done'])


if __name__ == '__main__':
    unittest.main()
