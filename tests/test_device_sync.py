"""v0.4 cross-device functionality and v0.3 regression guard tests."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / 'src' / 'script.watchnixtoons.anilist'
sys.path.insert(0, str(BASE))
from core import mapping_key
from device_sync import (DeviceSyncError, record_for_url, local_records, series_directory,
                         rpc_call, listing_records, merge_records, make_pull_plan,
                         apply_pull_plan, MAX_WRITES)


def source_url(show='naruto', episode=3, season=1, plugin='plugin.video.watchnixtoons2'):
    from urllib.parse import urlencode
    p = '%s-episode-%s-english-dubbed' % (show, episode)
    if season != 1:
        p = '%s-season-%s-episode-%s-english-dubbed' % (show, season, episode)
    return 'plugin://%s/?%s' % (plugin, urlencode({'action': 'actionResolve', 'url': '/' + p}))


def item(ep=3, watched=0, **kw):
    return record_for_url(source_url(episode=ep, **kw), watched)


def remote(progress=3, id=77, total=24):
    return {'id': id, 'episodes': total, 'mediaListEntry': {'progress': progress}}


class ParseAndSafety(unittest.TestCase):
    def test_valid_wnt2_episode(self):
        self.assertEqual(item()['key'], 'naruto|s1')
        self.assertEqual(item()['episode'], 3)
    def test_kodi19_slug(self):
        self.assertEqual(item(plugin='plugin.video.watchnixtoons2.kodi19')['episode'], 3)
    def test_reject_unrelated_addon(self):
        self.assertIsNone(record_for_url(source_url(plugin='plugin.video.thecrew')))
    def test_reject_arbitrary_http_url(self):
        self.assertIsNone(record_for_url('https://example.com/naruto-episode-3'))
    def test_reject_movie_undetermined_episode(self):
        self.assertIsNone(record_for_url('plugin://plugin.video.watchnixtoons2/?action=actionResolve&url=%2Fanime-movie'))
    def test_reject_wrong_action(self):
        self.assertIsNone(record_for_url('plugin://plugin.video.watchnixtoons2/?action=actionSearch&url=%2Fabc-episode-3'))
    def test_directory_built_safe(self):
        self.assertEqual(series_directory('/naruto'),
                         'plugin://plugin.video.watchnixtoons2/?action=actionEpisodesMenu&url=%2Fnaruto')
    def test_directory_reject_remote_url(self):
        with self.assertRaises(DeviceSyncError): series_directory('https://site.test/show')
    def test_directory_reject_unknown_plugin(self):
        with self.assertRaises(DeviceSyncError): series_directory('/naruto', 'plugin.video.thecrew')
    def test_directory_reject_relative_url(self):
        with self.assertRaises(DeviceSyncError): series_directory('naruto')


class SQLiteReadOnly(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name)/'MyVideos121.db')
        conn = sqlite3.connect(self.path)
        conn.execute('CREATE TABLE files(idFile INTEGER PRIMARY KEY, strFilename TEXT, playCount INTEGER)')
        conn.executemany('INSERT INTO files (strFilename, playCount) VALUES (?,?)',
                         [(source_url(episode=1), 1), (source_url(episode=2), None),
                          (source_url(episode=3), 0), (source_url(plugin='plugin.video.thecrew'), 1)])
        conn.commit(); conn.close()
    def tearDown(self): self.tmp.cleanup()
    def test_includes_unwatched_and_watched_wnt2(self):
        entries = local_records(self.path)
        self.assertEqual(sorted(x['episode'] for x in entries), [1, 2, 3])
        self.assertEqual([x for x in entries if x['episode'] == 1][0]['playcount'], 1)
    def test_is_read_only(self):
        local_records(self.path)
        conn = sqlite3.connect(self.path)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM files').fetchone()[0], 4)
        conn.close()
    def test_missing_db_fails_closed(self):
        with self.assertRaises(DeviceSyncError): local_records('/bad/file/unknown.db')
    def test_limit_fails_closed(self):
        with self.assertRaises(DeviceSyncError): local_records(self.path, limit=2)


class JsonRpc(unittest.TestCase):
    def test_valid_response(self):
        def fake(payload):
            req = json.loads(payload)
            self.assertEqual(req['method'], 'Files.GetDirectory')
            return json.dumps({'jsonrpc':'2.0','id':1,'result':{'files':[]}})
        self.assertEqual(rpc_call(fake, 'Files.GetDirectory', {'directory':'abc'}), {'files':[]})
    def test_invalid_json_fails(self):
        with self.assertRaises(DeviceSyncError): rpc_call(lambda x:'INVALID', 'Files.GetDirectory', {})
    def test_error_fails(self):
        with self.assertRaises(DeviceSyncError): rpc_call(lambda x:json.dumps({'error':{'code':-1}}), 'Files.GetDirectory', {})
    def test_listing_only_recognises_wnt2_episode_files(self):
        def fake(s):
            return json.dumps({'result':{'files':[
                {'file': source_url(episode=2), 'filetype':'file', 'playcount':0},
                {'file': source_url(episode=3, plugin='plugin.video.thecrew'), 'filetype':'file'},
                {'file': source_url(episode=4), 'filetype':'directory'},
            ]}})
        result=listing_records(fake,'/naruto')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['episode'],2)
    def test_listing_caps_count(self):
        def fake(s): return json.dumps({'result':{'files':[{'file':'x'}]*501}})
        with self.assertRaises(DeviceSyncError): listing_records(fake,'/naruto')
    def test_listing_rejects_missing_files_key(self):
        with self.assertRaises(DeviceSyncError): listing_records(lambda x:json.dumps({'result':{}}),'/naruto')


class Planning(unittest.TestCase):
    MAP = {'id':77,'offset':0,'title':'Naruto'}
    def plan(self,items,progress=3,mapping=None,remote_result=None,max_writes=MAX_WRITES):
        return make_pull_plan(items,'naruto|s1',mapping or self.MAP,
                              remote_result or remote(progress),max_writes=max_writes)
    def test_only_marks_progress_below_anilist(self):
        plan=self.plan([item(1),item(2),item(3),item(4)],2)
        self.assertEqual([x['episode'] for x in plan['to_mark']],[1,2])
    def test_does_not_clear_existing(self):
        plan=self.plan([item(1,watched=1),item(2)],2)
        self.assertEqual([x['episode'] for x in plan['to_mark']],[2])
        self.assertEqual(plan['already_watched'],1)
    def test_wrong_show_is_ignored(self):
        plan=self.plan([item(1,show='bleach'),item(2)],2)
        self.assertEqual([x['episode'] for x in plan['to_mark']],[2])
    def test_wrong_season_is_ignored(self):
        plan=self.plan([item(1,season=2),item(2)],2)
        self.assertEqual([x['episode'] for x in plan['to_mark']],[2])
    def test_empty_progress_no_writes(self):
        self.assertFalse(self.plan([item(1)],0)['to_mark'])
    def test_missing_approved_mapping_refuses(self):
        with self.assertRaises(DeviceSyncError): self.plan([item()],mapping={'ignore':True})
    def test_wrong_anilist_id_refuses(self):
        with self.assertRaises(DeviceSyncError): self.plan([item()],remote_result=remote(id=88))
    def test_impossible_progress_refuses(self):
        with self.assertRaises(DeviceSyncError): self.plan([item()],remote_result=remote(progress=30,total=24))
    def test_episode_offset(self):
        src=[item(10),item(11),item(12),item(13)]
        plan=self.plan(src,2,mapping={'id':77,'offset':10})
        self.assertEqual([r['episode'] for r in plan['to_mark']], [11,12])
    def test_dub_and_sub_duplicate_paths_allowed(self):
        a=item(2)
        b=record_for_url(a['file'].replace('english-dubbed','english-subbed'))
        self.assertEqual(len(self.plan([a,b],2)['to_mark']),2)
    def test_merging_preserves_existing_watched(self):
        self.assertEqual(merge_records([item(1,1)],[item(1,0)])[0]['playcount'],1)
    def test_batch_limit_fail_closed(self):
        with self.assertRaises(DeviceSyncError): self.plan([item(i) for i in range(1,5)],4,max_writes=3)


class Mutations(unittest.TestCase):
    def setUp(self):
        self.plan=make_pull_plan([item(1),item(2)],'naruto|s1',{'id':77},remote(progress=2))
        self.called=[]
        def rpc(text):
            req=json.loads(text)
            self.called.append(req)
            return json.dumps({'id':1,'result':'OK'})
        self.rpc=rpc
    def test_no_write_without_explicit_consent(self):
        with self.assertRaises(DeviceSyncError): apply_pull_plan(self.plan,self.rpc)
        self.assertEqual(self.called,[])
    def test_only_writes_playcount_one_to_wnt2(self):
        result=apply_pull_plan(self.plan,self.rpc,confirmed=True)
        self.assertEqual(result['accepted'],[1,2])
        self.assertEqual({r['method'] for r in self.called},{'Files.SetFileDetails'})
        self.assertTrue(all(r['params']['playcount']==1 and r['params']['media']=='video' for r in self.called))
    def test_reject_untrusted_path_even_when_manually_injected(self):
        self.plan['to_mark'][0]['file']='plugin://plugin.video.thecrew/?action=actionResolve&url=xxx'
        result=apply_pull_plan(self.plan,self.rpc,confirmed=True)
        self.assertEqual(result['accepted'],[2])
        self.assertEqual(len(self.called),1)
        self.assertEqual(len(result['failed']),1)
    def test_failed_rpc_reported_and_remaining_continue(self):
        def failure(t):
            self.called.append(json.loads(t))
            return json.dumps({'error':{'code':-32601,'message':'No method'}})
        result=apply_pull_plan(self.plan,failure,confirmed=True)
        self.assertEqual(len(result['failed']),2)
        self.assertEqual(len(result['accepted']),0)
    def test_no_unwatched_changes(self):
        apply_pull_plan(self.plan,self.rpc,confirmed=True)
        self.assertFalse(any(req['params'].get('playcount')==0 for req in self.called))


if __name__=='__main__': unittest.main()
