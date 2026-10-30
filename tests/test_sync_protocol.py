import sys, unittest, math, copy
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]/'src'/'script.watchnixtoons.anilist'
sys.path.insert(0,str(BASE))
from sync_protocol import (episode_id,blank_state,validate_position,add_watched,add_resume,
    merge_state,SyncStateError,incoming_resume,validated_state,event_rank)

URL=lambda ep='5',site='plugin.video.watchnixtoons2',suffix='english-subbed': ('plugin://%s/?action=actionResolve&url=https%%3A%%2F%%2Fwcostream.tv%%2Fnaruto-episode-%s-%s'% (site,ep,suffix))

def event(ts=10, dev='A',ctr=1): return {'at':ts,'device':dev,'counter':ctr}

class Protocol(unittest.TestCase):
    def test_id_is_domain_independent(self): self.assertEqual(episode_id(URL()),'/naruto-episode-5-english-subbed')
    def test_plugin_version_identity(self): self.assertEqual(episode_id(URL(site='plugin.video.watchnixtoons2.kodi19')),episode_id(URL()))
    def test_reject_unrelated_plugin(self): self.assertIsNone(episode_id(URL(site='plugin.video.thecrew')))
    def test_reject_non_wnt_video(self): self.assertIsNone(episode_id('https://example.com/test'))
    def test_reject_non_episode(self): self.assertIsNone(episode_id('plugin://plugin.video.watchnixtoons2/?action=actionResolve&url=/naruto'))
    def test_separate_dub_and_sub(self): self.assertNotEqual(episode_id(URL(suffix='english-dubbed')),episode_id(URL()))
    def test_reject_overlong(self): self.assertIsNone(episode_id('x'*4097))
    def test_minimum_duration(self): self.assertIsNone(validate_position(20,100))
    def test_reject_near_finish(self): self.assertIsNone(validate_position(97,100))
    def test_reject_negative(self): self.assertIsNone(validate_position(-1,100))
    def test_reject_zero_duration(self): self.assertIsNone(validate_position(34,0))
    def test_reject_nonfinite(self): self.assertIsNone(validate_position(float('nan'),600))
    def test_reject_infinite(self): self.assertIsNone(validate_position(40,float('inf')))
    def test_reject_long(self): self.assertIsNone(validate_position(80,15000))
    def test_valid(self): self.assertEqual(validate_position(100,120),{'position':100.,'total':120.})
    def test_union_watched(self):
        a=add_watched(blank_state(),['/one'])
        b=add_watched(blank_state(),['/two'])
        self.assertEqual(set(merge_state(a,b)['watched']),{'/one','/two'})
    def test_union_commutative(self):
        a=add_watched(blank_state(),['/one']);b=add_watched(blank_state(),['/two'])
        self.assertEqual(merge_state(a,b),merge_state(b,a))
    def test_remote_newest_resume_can_go_backwards(self):
        a=add_resume(blank_state(),'/one',400,1000,event(100))
        b=add_resume(blank_state(),'/one',300,1000,event(200))
        self.assertEqual(merge_state(a,b)['resumes']['/one']['position'],300)
    def test_older_event_never_overwrites(self):
        a=add_resume(blank_state(),'/one',400,1000,event(200))
        b=add_resume(blank_state(),'/one',300,1000,event(100))
        self.assertEqual(merge_state(a,b)['resumes']['/one']['position'],400)
    def test_tie_stably_merges(self):
        a=add_resume(blank_state(),'/one',400,1000,event(200,'A'))
        b=add_resume(blank_state(),'/one',300,1000,event(200,'B'))
        self.assertEqual(merge_state(a,b),merge_state(b,a))
    def test_completed_suppresses_resume(self):
        a=add_resume(blank_state(),'/one',400,1000,event(100))
        b=add_watched(blank_state(),['/one'])
        self.assertNotIn('/one',merge_state(a,b)['resumes'])
    def test_no_resume_on_watched_without_rewatch(self):
        a=add_watched(blank_state(),['/one'])
        self.assertEqual(add_resume(a,'/one',100,1000,event(200)),a)
    def test_rewatch_keeps_tick(self):
        a=add_watched(blank_state(),['/one'])
        c=add_resume(a,'/one',100,1000,event(200),rewatch=True)
        self.assertIn('/one',c['watched']);self.assertTrue(c['resumes']['/one']['rewatch'])
    def test_no_implicit_overwrite_local(self):
        self.assertIsNone(incoming_resume(120,{'position':300,'total':1000,'rewatch':False}))
    def test_incoming_unwatched(self):
        self.assertEqual(incoming_resume(0,{'position':300,'total':1000}),{'position':300.,'total':1000.})
    def test_incoming_finished_skip(self): self.assertIsNone(incoming_resume(0,{'position':300,'total':1000},watched=True))
    def test_incoming_rewatch_explicit(self):
        self.assertIsNotNone(incoming_resume(0,{'position':300,'total':1000,'rewatch':True},watched=True,rewatch=True))
    def test_invalid_schema(self):
        with self.assertRaises(SyncStateError): validated_state({'schema':0,'watched':{},'resumes':{}})
    def test_invalid_resume(self):
        with self.assertRaises(SyncStateError): validated_state({'schema':1,'watched':{},'resumes':{'/x':{'position':99,'total':100,'event':event()}}})
    def test_invalid_watched_identity(self):
        with self.assertRaises(SyncStateError): validated_state({'schema':1,'watched':{'http://malicious':True},'resumes':{}})
    def test_obsolete_version(self):
        with self.assertRaises(SyncStateError): merge_state(blank_state(),{})
    def test_no_mutation(self):
        a=blank_state();b=add_watched(a,['/x']);self.assertEqual(a,blank_state());self.assertNotEqual(a,b)
    def test_duplicate_watched(self):
        self.assertEqual(add_watched(add_watched(blank_state(),['/x']),['/x'])['watched'],{'/x':True})

if __name__=='__main__':unittest.main()
