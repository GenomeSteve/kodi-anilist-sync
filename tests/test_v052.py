import json, os, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1]/'script.watchnixtoons.anilist'
sys.path.insert(0,str(BASE))
from sync_protocol import add_resume, add_watched, merge_state, blank_state, episode_id
from passive_resume import selected_episode, verified_source
import auto_sync
from device_sync import record_for_url

URL='plugin://plugin.video.watchnixtoons2/?action=actionResolve&url=%2Fblack-clover-tv-episode-8-english-subbed'
KEY=episode_id(URL)
OTHER='plugin://plugin.video.another/?action=play&url=video'

class FakeAddon:
    def __init__(self):
        self.settings={'private_sync':'true','auto_watched':'false','private_repo':'GenomeSteve/kodi-watch-state','private_token':'SECRET','rewatch_episode':''}
    def getSetting(self,k):return self.settings.get(k,'')

class FakeKodi:
    def __init__(self):
        self.labels={};self.calls=[];self.resumes={};self.players=[];self.fail_new=False
    def getInfoLabel(self,k):return self.labels.get(k,'')
    def executeJSONRPC(self,data):
        m=json.loads(data);self.calls.append(m)
        f=m['params'].get('file')
        if m['method']=='Files.GetFileDetails':
            return json.dumps({'result':{'filedetails':{'resume':self.resumes.get(f,{}),'playcount':0}}})
        if m['method']=='Files.SetFileDetails':
            if self.fail_new:
                return json.dumps({'error':{'code':-32602,'message':'Not yet indexed'}})
            self.resumes[f]=m['params']['resume'];return json.dumps({'result':'OK'})
        return json.dumps({'error':'Unexpected request'})
    def Player(self):return self.players[-1]

class FakeVfs:
    def __init__(self,d):self.path=d
    def listdir(self,path):return [],['MyVideos121.db']
    def translatePath(self,path):return path.replace('special://profile',self.path).replace('special://database',self.path)

class FakePlayer:
    def __init__(self,time_s=0,total=1434,path='https://cdn.example/video.mp4',series='Black Clover',episode=8):
        self.t=time_s;self.total=total;self.path=path;self.series=series;self.ep=episode;self.seeks=[]
    def getTime(self):return self.t
    def getTotalTime(self):return self.total
    def seekTime(self,seconds):self.seeks.append(seconds);self.t=seconds
    def getPlayingFile(self):return self.path
    def getPlayingItem(self):return SimpleNamespace(getPath=lambda:self.path)
    def getVideoInfoTag(self):return SimpleNamespace(getEpisode=lambda:self.ep,getSeason=lambda:1,getTVShowTitle=lambda:self.series)

class FakeStore:
    def __init__(self,remote):self.remote=remote
    def read(self):return self.remote,'sha'
    def merge_and_write(self,proposed):self.remote=merge_state(self.remote,proposed);return self.remote

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addon=FakeAddon();self.kodi=FakeKodi();self.vfs=FakeVfs(self.tmp.name)
        self.engine=auto_sync.BackgroundEngine(self.addon,self.kodi,self.vfs,self.tmp.name)
        self.row=record_for_url(URL,0)
        self.engine.records=lambda: [self.row]
        self.remote=add_resume(blank_state(),KEY,1039.7,1433.8,{'at':100,'device':'living','counter':2})
        self.store=FakeStore(self.remote)
        self.patch=patch.object(auto_sync,'GitHubStore',side_effect=lambda *a,**k:self.store);self.patch.start()
        self.engine._remote=self.remote
        self.kodi.labels={'Container.FolderPath':'plugin://plugin.video.watchnixtoons2/?action=actionEpisodesMenu',
                          'ListItem.FileNameAndPath':URL}
    def tearDown(self):self.patch.stop();self.tmp.cleanup()
    def test_selected_exact_no_directory_requests(self):
        self.assertEqual(selected_episode(self.kodi),URL)
        self.engine.observe_selected(1000)
        self.assertAlmostEqual(self.kodi.resumes[URL]['position'],1039.7)
        self.assertEqual(self.engine.state['stats']['resumes_downloaded'],1)
        self.assertFalse(any(x['method']=='Files.GetDirectory' for x in self.kodi.calls))
    def test_wrong_folder_or_plugin_ignored(self):
        self.kodi.labels['Container.FolderPath']='plugin://plugin.video.other/'
        self.assertIsNone(selected_episode(self.kodi))
        self.kodi.labels['Container.FolderPath']=''
        self.kodi.labels['ListItem.FileNameAndPath']=OTHER
        self.assertIsNone(selected_episode(self.kodi))
    def test_new_episode_before_index_falls_back_to_verified_seek(self):
        self.kodi.fail_new=True
        self.engine.observe_selected(time.time())
        self.assertEqual(self.engine.state['stats']['episodes_recognised'],1)
        folder=Path(self.tmp.name)/'addon_data'/'plugin.video.watchnixtoons2'
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'recently_watched.dat').write_text(json.dumps({'h':{'name':'Black Clover','url':'/black-clover-tv'}}))
        player=FakePlayer()
        self.engine.apply_playback_resume(player,time.time())
        self.assertEqual(player.seeks,[1039.7])
        self.assertEqual(self.engine.state['stats']['resumes_downloaded'],1)
    def test_unrelated_player_must_not_seek(self):
        self.engine.observe_selected(time.time())
        self.engine._playback_restored=None
        player=FakePlayer(path=OTHER)
        self.engine.apply_playback_resume(player,time.time())
        self.assertEqual(player.seeks,[])
    def test_wrong_episode_or_show_never_seeks(self):
        self.kodi.fail_new=True
        self.engine.observe_selected(time.time())
        folder=Path(self.tmp.name)/'addon_data'/'plugin.video.watchnixtoons2'
        folder.mkdir(parents=True,exist_ok=True)
        (folder/'recently_watched.dat').write_text(json.dumps({'h':{'name':'Black Clover','url':'/black-clover-tv'}}))
        for player in (FakePlayer(series='Bleach'),FakePlayer(episode=9),FakePlayer(total=500)):
            self.engine.apply_playback_resume(player,time.time())
            self.assertEqual(player.seeks,[])
    def test_local_meaningful_bookmark_never_replaced(self):
        self.engine.observe_selected(time.time())
        self.engine._playback_restored=None
        self.kodi.resumes[URL]={'position':650,'total':1434}
        player=FakePlayer(path=URL)
        self.engine.apply_playback_resume(player,time.time())
        self.assertEqual(player.seeks,[])
    def test_resume_upload_and_counters_after_remote_download(self):
        self.engine.observe_selected(time.time())
        self.engine._selected['at']=time.time()
        player=FakePlayer(time_s=1130,path=URL)
        self.engine.state['last_capture']=0
        self.engine.capture_playback(player,time.time())
        self.engine.state['last_flush']=0
        self.engine.flush_playback(time.time())
        self.assertAlmostEqual(self.store.remote['resumes'][KEY]['position'],1130)
        self.assertEqual(self.engine.state['stats']['resumes_uploaded'],1)
        self.assertEqual(self.engine.state['stats']['resumes_downloaded'],1)
    def test_first_low_progress_does_not_replace_incoming(self):
        self.kodi.fail_new=True
        self.engine.observe_selected(time.time())
        p=FakePlayer(time_s=9,path=URL)
        self.engine.capture_playback(p,time.time())
        self.assertEqual(self.engine.state['pending']['resumes'],{})
    def test_two_way_receiving_newer_other_firestick_resume(self):
        # Firestick A already has an A-origin bookmark, with a known timestamp.
        self.engine.observe_selected(time.time())
        self.assertEqual(self.engine.state['observed'][KEY]['at'], 100)
        # Firestick B continues the episode after A, creating a newer event.
        self.store.remote=add_resume(self.store.remote, KEY, 1215, 1433.8,
                                     {'at':200,'device':'bedroom','counter':3})
        self.engine.private_sync()
        self.assertAlmostEqual(self.kodi.resumes[URL]['position'],1215)
        self.assertEqual(self.engine.state['stats']['resumes_downloaded'],2)
        self.assertEqual(self.engine.state['observed'][KEY]['at'],200)
        # The new remote point does not get spuriously published as new local.
        self.engine.private_sync()
        self.assertAlmostEqual(self.store.remote['resumes'][KEY]['position'],1215)

    def test_other_firestick_can_rewind_newer_timestamp_wins(self):
        self.engine.observe_selected(time.time())
        self.store.remote=add_resume(self.store.remote, KEY, 410, 1433.8,
                                     {'at':200,'device':'bedroom','counter':4})
        self.engine.private_sync()
        self.assertAlmostEqual(self.kodi.resumes[URL]['position'],410)

    def test_new_active_capture_seeds_trusted_timestamp(self):
        self.engine._remote=blank_state()
        self.engine._selected={'url':URL,'key':KEY,'at':time.time()}
        player=FakePlayer(time_s=800,path=URL)
        self.engine.capture_playback(player,time.time())
        self.assertGreater(self.engine.state['observed'][KEY]['at'],0)
        self.assertAlmostEqual(self.engine.state['pending']['resumes'][KEY]['position'],800)

    def test_full_private_sync_does_not_execute_plugin_directory(self):
        self.engine.private_sync()
        self.assertFalse(any(x['method']=='Files.GetDirectory' for x in self.kodi.calls))
    def test_remote_completion_blocks_passive_restore(self):
        self.engine._remote=add_watched(self.remote,[KEY])
        self.engine.observe_selected(time.time())
        self.assertNotIn(URL,self.kodi.resumes)

if __name__=='__main__':unittest.main()
