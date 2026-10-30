"""Kodi UI interaction regressions with fake dialogs and API responses."""
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
from test_device_sync import item, remote


class FakeDialog:
    def __init__(self, answers=None, selections=None):
        self.answers=list(answers or [])
        self.selections=list(selections or [])
        self.messages=[]
    def yesno(self, *args, **kw): return self.answers.pop(0)
    def select(self, *args, **kw): return self.selections.pop(0)
    def ok(self, *args, **kw): self.messages.append(('ok',str(args)))
    def textviewer(self, *args, **kw): self.messages.append(('preview',str(args)))
    def input(self, *args, **kw): return '0'


class PreviewAndConsent(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.profile=self.temp.name
        self.dialog=FakeDialog()
        fakeaddon=ModuleType('xbmcaddon')
        outer=self
        class Addon:
            def __init__(s,name=None): pass
            def getAddonInfo(s,k): return outer.profile if k=='profile' else ''
            def getSetting(s,k): return 'valid-token' if k=='token' else 'true'
        fakeaddon.Addon=Addon
        fakegui=ModuleType('xbmcgui')
        fakegui.INPUT_NUMERIC=1
        fakegui.Dialog=lambda: outer.dialog
        fakevfs=ModuleType('xbmcvfs')
        fakevfs.translatePath=lambda path:path.replace('special://profile', outer.profile).replace('special://database',outer.profile+'/db')
        fakevfs.listdir=lambda path:([],['MyVideos121.db'])
        fakexbmc=ModuleType('xbmc')
        fakexbmc.executeJSONRPC=lambda p:json.dumps({'result':{'files':[]}})
        self.module_patch=patch.dict(sys.modules,{'xbmc':fakexbmc,'xbmcaddon':fakeaddon,'xbmcgui':fakegui,'xbmcvfs':fakevfs})
        self.module_patch.start()
        sys.modules.pop('device_sync_ui',None)
        self.ui=importlib.import_module('device_sync_ui')
        (Path(self.profile)/'mappings.json').write_text(json.dumps({'naruto|s1':{'id':77,'title':'Naruto','offset':0}}))
        self.records=[item(1),item(2)]
        self.remote=remote(2)
    def tearDown(self):
        sys.modules.pop('device_sync_ui',None)
        self.module_patch.stop()
        self.temp.cleanup()
    def test_initial_cancel_does_nothing(self):
        self.dialog=FakeDialog(answers=[False])
        self.ui.DIALOG=self.dialog
        with patch.object(self.ui, 'local_records') as query, patch.object(self.ui, 'details') as api, patch.object(self.ui,'apply_pull_plan') as apply:
            self.ui.execute_sync(lambda s:None)
        query.assert_not_called(); api.assert_not_called(); apply.assert_not_called()
    def test_series_cancel_without_network_write(self):
        self.dialog=FakeDialog(answers=[True],selections=[-1])
        self.ui.DIALOG=self.dialog
        with patch.object(self.ui,'local_records',return_value=self.records), patch.object(self.ui,'recent_series',return_value={}),patch.object(self.ui,'details') as api, patch.object(self.ui,'apply_pull_plan') as apply:
            self.ui.execute_sync(lambda s:None)
        api.assert_not_called(); apply.assert_not_called()
    def test_preview_cancel_leaves_ticks(self):
        self.dialog=FakeDialog(answers=[True,True,False],selections=[0,-1])
        self.ui.DIALOG=self.dialog
        with patch.object(self.ui,'local_records',return_value=self.records),patch.object(self.ui,'recent_series',return_value={}),patch.object(self.ui,'details',return_value=self.remote),patch.object(self.ui,'apply_pull_plan') as apply:
            self.ui.execute_sync(lambda s:None)
        apply.assert_not_called()
        self.assertTrue(any(t=='preview' for t,_ in self.dialog.messages))
    def test_confirmed_write_calls_only_once_with_consent(self):
        self.dialog=FakeDialog(answers=[True,True,True],selections=[0,-1])
        self.ui.DIALOG=self.dialog
        with patch.object(self.ui,'local_records',return_value=self.records),patch.object(self.ui,'recent_series',return_value={}),patch.object(self.ui,'details',return_value=self.remote) as api,patch.object(self.ui,'apply_pull_plan',return_value={'accepted':[1,2],'failed':[]}) as apply:
            self.ui.execute_sync(lambda s:None)
        self.assertEqual(api.call_count,2)
        self.assertEqual(apply.call_count,1)
        self.assertTrue(apply.call_args.kwargs['confirmed'])
    def test_ani_list_changed_after_confirmation_refuses(self):
        self.dialog=FakeDialog(answers=[True,True,True],selections=[0,-1])
        self.ui.DIALOG=self.dialog
        changed=remote(3)
        with patch.object(self.ui,'local_records',return_value=self.records),patch.object(self.ui,'recent_series',return_value={}),patch.object(self.ui,'details',side_effect=[self.remote,changed]),patch.object(self.ui,'apply_pull_plan') as apply:
            self.ui.execute_sync(lambda s:None)
        apply.assert_not_called()
    def test_local_watched_state_changed_refuses(self):
        self.dialog=FakeDialog(answers=[True,True,True],selections=[0,-1])
        self.ui.DIALOG=self.dialog
        changed=[item(1,watched=1),item(2)]
        with patch.object(self.ui,'local_records',side_effect=[self.records,changed]),patch.object(self.ui,'recent_series',return_value={}),patch.object(self.ui,'details',return_value=self.remote),patch.object(self.ui,'apply_pull_plan') as apply:
            self.ui.execute_sync(lambda s:None)
        apply.assert_not_called()
    def test_second_device_without_mapping_no_write_until_approved(self):
        (Path(self.profile)/'mappings.json').write_text('{}')
        self.dialog=FakeDialog(answers=[True,False],selections=[0,-1])
        self.ui.DIALOG=self.dialog
        with patch.object(self.ui,'local_records',return_value=self.records),patch.object(self.ui,'recent_series',return_value={}),patch.object(self.ui,'details') as api,patch.object(self.ui,'apply_pull_plan') as apply:
            self.ui.execute_sync(lambda s:{'id':77,'title':'Naruto','offset':0})
        api.assert_not_called();apply.assert_not_called()
    def test_ignored_mapping_no_write(self):
        (Path(self.profile)/'mappings.json').write_text(json.dumps({'naruto|s1':{'ignore':True}}))
        self.dialog=FakeDialog(answers=[True],selections=[0,-1])
        self.ui.DIALOG=self.dialog
        with patch.object(self.ui,'local_records',return_value=self.records),patch.object(self.ui,'recent_series',return_value={}),patch.object(self.ui,'details') as api,patch.object(self.ui,'apply_pull_plan') as apply:
            self.ui.execute_sync(lambda s:None)
        api.assert_not_called();apply.assert_not_called()

if __name__=='__main__':unittest.main()
