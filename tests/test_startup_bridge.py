"""Startup sync and Kodi 21 first-render WatchNixtoons2 integration checks."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'src' / 'script.watchnixtoons.anilist'
BRIDGE = ROOT / 'integration' / 'watchnixtoons2-kodi19' / 'lib' / 'wnt2_sync_bridge.py'
sys.path.insert(0, str(BASE))
spec = importlib.util.spec_from_file_location('wnt2_sync_bridge', BRIDGE)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

from sync_protocol import add_resume, add_watched, blank_state, episode_id
from test_auto_sync import Background, URL

SUB = URL
DUB = URL.replace('subbed', 'dubbed')
OTHER = 'plugin://plugin.video.other/?action=actionResolve&url=%2Fnaruto-episode-5-english-subbed'


class VideoTag:
    def __init__(self):
        self.playcount = None
        self.resume = None
    def setPlaycount(self, count):
        self.playcount = count
    def setResumePoint(self, position, total):
        self.resume = (position, total)


class Item:
    def __init__(self):
        self.tag = VideoTag()
    def getVideoInfoTag(self):
        return self.tag


class BridgeTests(unittest.TestCase):
    def test_exact_id_matches_sync_protocol(self):
        self.assertEqual(bridge.episode_key(SUB), episode_id(SUB))
        self.assertNotEqual(bridge.episode_key(SUB), bridge.episode_key(DUB))
        self.assertIsNone(bridge.episode_key(OTHER))
        self.assertIsNone(bridge.episode_key('plugin://plugin.video.watchnixtoons2/?action=actionResolve&url=%2Fnaruto'))

    def test_corrupt_and_missing_cache_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'private_snapshot.json'
            self.assertEqual(bridge.read_snapshot(str(p))['resumes'], {})
            p.write_text('not json')
            self.assertEqual(bridge.read_snapshot(str(p))['watched'], {})
            p.write_text(json.dumps({'schema':2, 'watched':{}, 'resumes':{}}))
            self.assertEqual(bridge.read_snapshot(str(p))['resumes'], {})

    def test_first_render_resume_unplayed_episode(self):
        state = {'watched':{}, 'resumes':{bridge.episode_key(SUB):{
            'position':689.5, 'total':1420, 'event':{'at':500,'device':'A','counter':1}}},
            'local':{}, 'observed':{}}
        item = Item()
        bridge.decorate(item, SUB, state)
        self.assertEqual(item.tag.resume, (689.5, 1420.0))
        self.assertIsNone(item.tag.playcount)
        self.assertIsNone(Item().tag.resume)

    def test_unrelated_edition_and_other_plugin_never_marked(self):
        state = {'watched':{}, 'resumes':{bridge.episode_key(SUB):{
            'position':689.5, 'total':1420, 'event':{'at':500}}},
            'local':{}, 'observed':{}}
        for url in (DUB, OTHER):
            item = Item()
            bridge.decorate(item,url,state)
            self.assertIsNone(item.tag.resume)
            self.assertIsNone(item.tag.playcount)

    def test_completed_remote_episode_has_tick_not_resume(self):
        key=bridge.episode_key(SUB)
        state={'watched':{key:True}, 'resumes':{key:{
            'position':689.5,'total':1420,'event':{'at':500}}},
            'local':{},'observed':{}}
        item=Item()
        bridge.decorate(item,SUB,state)
        self.assertEqual(item.tag.playcount,1)
        self.assertIsNone(item.tag.resume)

    def test_local_bookmark_of_unknown_age_wins(self):
        key=bridge.episode_key(SUB)
        state={'watched':{},'resumes':{key:{
            'position':689.5,'total':1420,'event':{'at':500}}},
            'local':{key:{'playcount':0,'position':900,'total':1420}},'observed':{}}
        item=Item()
        bridge.decorate(item,SUB,state)
        self.assertEqual(item.tag.resume,(900,1420))

    def test_confirmed_newer_remote_event_replaces_old_local(self):
        key=bridge.episode_key(SUB)
        state={'watched':{},'resumes':{key:{
            'position':550,'total':1420,'event':{'at':500}}},
            'local':{key:{'playcount':0,'position':900,'total':1420}},
            'observed':{key:{'signature':'900/1420','at':100}}}
        item=Item()
        bridge.decorate(item,SUB,state)
        self.assertEqual(item.tag.resume,(550,1420))

    def test_local_completed_cannot_be_unwatched_by_remote_resume(self):
        key=bridge.episode_key(SUB)
        state={'watched':{},'resumes':{key:{
            'position':689.5,'total':1420,'event':{'at':500}}},
            'local':{key:{'playcount':1,'position':0,'total':0}},'observed':{}}
        item=Item()
        bridge.decorate(item,SUB,state)
        self.assertEqual(item.tag.playcount,1)
        self.assertIsNone(item.tag.resume)

    def test_no_network_side_effects(self):
        text=BRIDGE.read_text()
        for forbidden in ('urlopen(', 'Files.GetDirectory', 'request_helper(', 'requests.get('):
            self.assertNotIn(forbidden,text)

    def test_cold_start_reads_verified_cached_private_state(self):
        fake = Background()
        fake.setUp()
        try:
            key=episode_id(URL)
            existing=add_resume(blank_state(),key,350,1200,
                                {'at':500,'device':'A','counter':1})
            from storage import write_json
            write_json(str(Path(fake.tmp.name)/'private_snapshot.json'),existing)
            import auto_sync
            engine=auto_sync.BackgroundEngine(fake.addon,fake.kodi,
                                              fake.engine.vfs,fake.tmp.name)
            self.assertEqual(engine.state['last_private'],0)
            self.assertEqual(engine._remote['resumes'][key]['position'],350)
            self.assertEqual(fake.kodi.calls,[])
        finally:
            fake.tearDown()

    def test_successful_idle_sync_publishes_new_snapshot(self):
        fake=Background()
        fake.setUp()
        try:
            import auto_sync
            key=episode_id(URL)
            fake.hub.value=add_resume(blank_state(),key,689.5,1200,
                                      {'at':500,'device':'A','counter':1})
            fake.engine.private_sync()
            payload=json.loads((Path(fake.tmp.name)/'private_snapshot.json').read_text())
            self.assertEqual(payload['resumes'][key]['position'],689.5)
            self.assertNotIn('token',json.dumps(payload).lower())
        finally:
            fake.tearDown()


if __name__ == '__main__':
    unittest.main()
