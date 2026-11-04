import sys, unittest, base64, json
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]/'src'/'script.watchnixtoons.anilist'
sys.path.insert(0,str(BASE))
from private_store import GitHubStore, StoreError, Conflict
from sync_protocol import blank_state,add_watched,add_resume

class FakeHub:
    def __init__(self, private=True):
        self.private=private;self.state=None;self.rev=0;self.fail=0;self.calls=[]
    def __call__(self, method, payload=None):
        self.calls.append(method)
        if method=='META':return {'private':self.private,'full_name':'Owner/Private'}
        if method=='GET':
            if self.state is None:return {'_missing':True}
            return {'type':'file','sha':str(self.rev),'content':base64.b64encode(json.dumps(self.state).encode()).decode()}
        if method=='PUT':
            if self.fail:
                self.fail-=1;raise Conflict('Simulated collision')
            if self.state is not None and payload.get('sha')!=str(self.rev):raise Conflict('Stale')
            if self.state is None and 'sha' in payload:raise Conflict('Missing')
            self.state=json.loads(base64.b64decode(payload['content']))
            self.rev+=1;return {}
        raise AssertionError(method)

class Store(unittest.TestCase):
    def setUp(self):self.hub=FakeHub();self.store=GitHubStore('Owner/Private','secret',transport=self.hub)
    def test_private_restriction(self):
        h=FakeHub(private=False)
        with self.assertRaises(StoreError):GitHubStore('Owner/Private','secret',transport=h).read()
        self.assertNotIn('PUT',h.calls)
    def test_bad_repo(self):
        with self.assertRaises(StoreError):GitHubStore('../bad','token')
    def test_bad_secret(self):
        with self.assertRaises(StoreError):GitHubStore('Owner/Private','token with spaces')
    def test_missing_state_initialises_blank(self):self.assertEqual(self.store.read(),(blank_state(),None))
    def test_writes_when_no_state(self):
        p=add_watched(blank_state(),['/naruto-episode-1'])
        self.store.merge_and_write(p)
        self.assertEqual(self.hub.state,p)
    def test_no_duplicate_write(self):
        p=add_watched(blank_state(),['/1']);self.store.merge_and_write(p)
        rev=self.hub.rev;self.store.merge_and_write(p)
        self.assertEqual(self.hub.rev,rev)
    def test_retry_collision(self):
        self.hub.fail=1
        p=add_watched(blank_state(),['/one'])
        self.store.merge_and_write(p)
        self.assertEqual(self.hub.state,p)
    def test_collision_exhaustion(self):
        self.hub.fail=20
        with self.assertRaises(StoreError):self.store.merge_and_write(add_watched(blank_state(),['/one']),retries=3)
    def test_two_devices_union(self):
        one=add_watched(blank_state(),['/one']);two=add_watched(blank_state(),['/two'])
        self.store.merge_and_write(one)
        GitHubStore('Owner/Private','other-token',transport=self.hub).merge_and_write(two)
        self.assertEqual(set(self.hub.state['watched']),{'/one','/two'})
    def test_two_devices_latest_resume(self):
        e1={'at':200,'device':'A','counter':1}
        e2={'at':300,'device':'B','counter':1}
        a=add_resume(blank_state(),'/x',300,1000,e1)
        b=add_resume(blank_state(),'/x',100,1000,e2)
        self.store.merge_and_write(a)
        GitHubStore('Owner/Private','another',transport=self.hub).merge_and_write(b)
        self.assertEqual(self.hub.state['resumes']['/x']['position'],100)
    def test_no_secrets_in_file(self):
        self.store.merge_and_write(add_watched(blank_state(),['/naruto']))
        self.assertNotIn('secret',json.dumps(self.hub.state))

if __name__=='__main__':unittest.main()
