"""Mock end-to-end tests: two Kodi installs, one private state, optional receiver."""
import importlib, json, os, tempfile, time, unittest, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1]/'src'/'script.watchnixtoons.anilist'
sys.path.insert(0,str(BASE))
import auto_sync
from device_sync import record_for_url
from sync_protocol import blank_state, add_watched, add_resume, merge_state, episode_id

URL='plugin://plugin.video.watchnixtoons2/?action=actionResolve&url=%2Fnaruto-episode-5-english-subbed'

class Addon:
    def __init__(self, settings=None):
        self.values={'auto_watched':'false','private_sync':'false','token':'AT',
                     'private_repo':'O/private','private_token':'test-token','rewatch_episode':''}
        self.values.update(settings or {})
    def getSetting(self,k):return self.values.get(k,'')

class Kodi:
    def __init__(self):self.calls=[];self.resumes={};self.playcount={}
    def executeJSONRPC(self,payload):
        msg=json.loads(payload);self.calls.append(msg);p=msg['params'];f=p.get('file')
        if msg['method']=='Files.GetFileDetails':
            point=self.resumes.get(f,{})
            return json.dumps({'result':{'filedetails':{'resume':point,'playcount':self.playcount.get(f,0)}}})
        if msg['method']=='Files.SetFileDetails':
            if 'playcount' in p:self.playcount[f]=p['playcount']
            if 'resume' in p:self.resumes[f]=p['resume']
            return json.dumps({'result':'OK'})
        return json.dumps({'error':{'code':-1,'message':'unexpected'}})
    def Player(self):return SimpleNamespace()

class FakeVfs:
    def __init__(self,profile):self.profile=profile
    def listdir(self,path):return [],['MyVideos121.db']
    def translatePath(self,path):return path.replace('special://database',self.profile).replace('special://profile',self.profile)

class Hub:
    def __init__(self,remote):self.value=remote;self.writes=[]
    def read(self):return self.value,'latest'
    def merge_and_write(self, proposed):
        self.value=merge_state(self.value,proposed);self.writes.append(proposed);return self.value

class Background(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.kodi=Kodi();self.addon=Addon();self.engine=auto_sync.BackgroundEngine(
            self.addon,self.kodi,FakeVfs(self.tmp.name),self.tmp.name)
        self.row=record_for_url(URL,0)
        self.hub=Hub(blank_state())
        self.patcher=patch.object(auto_sync,'GitHubStore',side_effect=lambda *a,**k:self.hub)
        self.patcher.start()
        self.engine.known_episodes=lambda include_listings=False:[self.row]
    def tearDown(self):self.patcher.stop();self.tmp.cleanup()
    def test_default_no_background_requests(self):
        self.engine.tick(20000,False)
        self.assertEqual(self.hub.writes,[])
        self.assertEqual(self.kodi.calls,[])
    def test_playing_skips_auto_pull(self):
        self.addon.values['auto_watched']='true'
        with patch.object(self.engine,'pull_anilist') as pull:
            self.engine.tick(20000,True);pull.assert_not_called()
    def test_private_exact_watched_tick_from_second_device(self):
        self.addon.values['private_sync']='true'
        self.hub.value=add_watched(blank_state(),[episode_id(URL)])
        self.engine.private_sync()
        self.assertEqual(self.kodi.playcount[URL],1)
        self.assertIn('exact ticks',self.engine.state['last_status'])
    def test_private_remains_readonly_if_path_unmatched(self):
        self.hub.value=add_watched(blank_state(),['/other-series-episode-8'])
        self.engine.private_sync()
        self.assertEqual(self.kodi.playcount,{})
    def test_private_does_not_clear_watched(self):
        self.row['playcount']=1
        self.hub.value=blank_state()
        self.engine.private_sync()
        self.assertIn(episode_id(URL),self.hub.value['watched'])
        self.assertFalse(any('playcount' in x['params'] for x in self.kodi.calls))
    def test_private_restores_empty_resume(self):
        self.hub.value=add_resume(blank_state(),episode_id(URL),120,1200,
                                  {'at':500,'device':'A','counter':1})
        self.engine.private_sync()
        self.assertEqual(self.kodi.resumes[URL],{'position':120.,'total':1200.})
    def test_newer_remote_rewind_replaces_old_local_bookmark(self):
        self.kodi.resumes[URL]={'position':350,'total':1200}
        self.engine.state['observed'][episode_id(URL)]={'signature':'350/1200','at':100}
        self.hub.value=add_resume(blank_state(),episode_id(URL),120,1200,
                                  {'at':500,'device':'B','counter':2})
        self.engine.private_sync()
        self.assertEqual(self.kodi.resumes[URL]['position'],120)
    def test_older_remote_does_not_replace_newer_local(self):
        self.kodi.resumes[URL]={'position':350,'total':1200}
        self.engine.state['observed'][episode_id(URL)]={'signature':'350/1200','at':600}
        self.hub.value=add_resume(blank_state(),episode_id(URL),120,1200,
                                  {'at':500,'device':'B','counter':2})
        self.engine.private_sync()
        self.assertEqual(self.kodi.resumes[URL]['position'],350)
    def test_new_local_bookmark_publishes_to_private(self):
        self.kodi.resumes[URL]={'position':400,'total':1200}
        self.engine.state['observed'][episode_id(URL)]={'signature':'300/1200','at':1}
        self.engine.private_sync()
        self.assertEqual(self.hub.value['resumes'][episode_id(URL)]['position'],400)
    def test_first_scan_never_uploads_old_unverified_bookmark(self):
        self.kodi.resumes[URL]={'position':400,'total':1200}
        self.engine.private_sync()
        self.assertNotIn(episode_id(URL),self.hub.value['resumes'])
    def test_no_resume_for_completed_without_rewatch(self):
        self.row['playcount']=1
        self.hub.value=add_resume(blank_state(),episode_id(URL),250,1200,
                                  {'at':500,'device':'A','counter':1})
        self.engine.private_sync()
        self.assertNotIn(URL,self.kodi.resumes)
    def test_rewatch_allows_resume_without_clearing_tick(self):
        self.row['playcount']=1
        self.addon.values['rewatch_episode']=episode_id(URL)
        completed=add_watched(blank_state(),[episode_id(URL)])
        self.hub.value=add_resume(completed,episode_id(URL),250,1200,
                                  {'at':500,'device':'A','counter':1},rewatch=True)
        self.engine.private_sync()
        self.assertEqual(self.kodi.resumes[URL]['position'],250)
        self.assertEqual(self.row['playcount'],1)
    def test_failure_retains_offline_queue(self):
        self.kodi.resumes[URL]={'position':400,'total':1200}
        self.engine.state['observed'][episode_id(URL)]={'signature':'300/1200','at':1}
        self.hub.merge_and_write=lambda value:(_ for _ in ()).throw(RuntimeError('network down'))
        with self.assertRaises(RuntimeError):self.engine.private_sync()
        self.assertIn(episode_id(URL),self.engine.state['pending']['resumes'])
    def test_engine_nonoverlap_deadline(self):
        self.addon.values['auto_watched']='true'
        with patch.object(self.engine,'pull_anilist') as pull:
            self.engine.tick(20000)
            self.engine.tick(20001)
            self.assertEqual(pull.call_count,1)
    def test_pull_requires_approved_mapping(self):
        self.addon.values['auto_watched']='true'
        with patch.object(auto_sync,'details') as details:
            self.engine.pull_anilist()
            details.assert_not_called()
    def test_pull_does_not_overwrite_progress(self):
        with open(self.engine.mappings_path,'w') as f:json.dump({'naruto|s1':{'id':77,'offset':0}},f)
        with patch.object(auto_sync,'details',return_value={'id':77,'episodes':12,'mediaListEntry':{'progress':2}}),\
             patch.object(auto_sync,'apply_pull_plan') as apply:
            self.engine.pull_anilist()
            apply.assert_called_once()
            self.assertEqual(apply.call_args.args[0]['to_mark'],[])
    def test_pull_adds_only_missing_approved_episodes(self):
        with open(self.engine.mappings_path,'w') as f:json.dump({'naruto|s1':{'id':77,'offset':0}},f)
        with patch.object(auto_sync,'details',return_value={'id':77,'episodes':12,'mediaListEntry':{'progress':5}}),\
             patch.object(auto_sync,'apply_pull_plan',return_value={'accepted':[5],'failed':[]}) as apply:
            self.engine.pull_anilist()
            self.assertEqual(len(apply.call_args.args[0]['to_mark']),1)
            self.assertEqual(apply.call_args.kwargs['confirmed'],True)
    def _player(self, title='Naruto', episode=5, pos=300):
        tag=SimpleNamespace(getTVShowTitle=lambda:title,getEpisode=lambda:episode,getSeason=lambda:1)
        return SimpleNamespace(getVideoInfoTag=lambda:tag,getTime=lambda:pos,getTotalTime=lambda:1200)
    def _setup_recent(self):
        folder=Path(self.tmp.name)/'addon_data'/'plugin.video.watchnixtoons2'
        folder.mkdir(parents=True)
        (folder/'recently_watched.dat').write_text(json.dumps({'hash':{'name':'Naruto','url':'/naruto'}}))
        return folder
    def test_active_playback_only_with_matching_recent_wnt2(self):
        self.engine.records=lambda:[self.row]
        self._setup_recent()
        self.engine.capture_playback(self._player(),time.time())
        self.assertIn(episode_id(URL),self.engine.state['pending']['resumes'])
    def test_active_playback_rejects_unrelated_title(self):
        self.engine.records=lambda:[self.row]
        self._setup_recent()
        self.engine.capture_playback(self._player(title='Bleach'),time.time())
        self.assertEqual(self.engine.state['pending']['resumes'],{})
    def test_active_playback_rejects_ambiguous_multiple_paths(self):
        self.engine.records=lambda:[self.row,record_for_url(URL.replace('subbed','dubbed'),0)]
        self._setup_recent()
        self.engine.capture_playback(self._player(),time.time())
        self.assertEqual(self.engine.state['pending']['resumes'],{})
    def test_active_resume_upload_no_local_writes(self):
        self.engine.records=lambda:[self.row]
        self._setup_recent()
        now=time.time()
        self.engine.capture_playback(self._player(),now)
        self.engine.flush_playback(now)
        self.assertEqual(self.hub.value['resumes'][episode_id(URL)]['position'],300)
        self.assertFalse(any(x['method']=='Files.SetFileDetails' for x in self.kodi.calls))
    def test_active_skips_completed_unless_rewatch(self):
        self.engine.records=lambda:[self.row]
        self._setup_recent()
        self.engine.state['pending']=add_watched(blank_state(),[episode_id(URL)])
        self.engine.capture_playback(self._player(),time.time())
        self.assertEqual(self.engine.state['pending']['resumes'],{})
    def test_active_rewatch_captures_without_removing_watched(self):
        self.engine.records=lambda:[self.row]
        self._setup_recent()
        self.addon.values['rewatch_episode']=episode_id(URL)
        self.engine.state['pending']=add_watched(blank_state(),[episode_id(URL)])
        self.engine.capture_playback(self._player(),time.time())
        self.assertIn(episode_id(URL),self.engine.state['pending']['watched'])
        self.assertTrue(self.engine.state['pending']['resumes'][episode_id(URL)]['rewatch'])

    def test_no_other_addon_in_private(self):
        self.hub.value=add_watched(blank_state(),['/naruto-episode-5-other-addon'])
        self.engine.known_episodes=lambda include_listings=False:[]
        self.engine.private_sync()
        self.assertEqual(self.kodi.calls,[])

if __name__=='__main__':unittest.main()
