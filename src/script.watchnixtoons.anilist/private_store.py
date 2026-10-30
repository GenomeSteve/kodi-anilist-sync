"""Optional authenticated private GitHub repository state, with optimistic CAS.

Never send credentials to github.com Pages, logs or the public add-on repo.
Fine-grained GitHub token needs Contents read/write to ONE *private* repo.
"""
import base64
import binascii
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from sync_protocol import blank_state, merge_state, validated_state


class StoreError(Exception):
    pass


class Conflict(StoreError):
    pass


class GitHubStore:
    def __init__(self, repo, token, transport=None):
        if not isinstance(repo, str) or '..' in repo or not re.fullmatch(r'[A-Za-z0-9_.-]{1,60}/[A-Za-z0-9_.-]{1,100}', repo):
            raise StoreError('Set owner/private-repo in Private sync settings')
        if not token or any(ch.isspace() for ch in token):
            raise StoreError('A GitHub fine-grained token is required')
        self.repo, self.token = repo, token
        self.transport = transport or self._request
        self.url = 'https://api.github.com/repos/%s/contents/sync/state.json' % repo
        self.meta_url = 'https://api.github.com/repos/%s' % repo
        self._checked_private = False

    def _request(self, method, payload=None):
        headers = {'Authorization': 'Bearer ' + self.token,
                   'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2022-11-28',
                   'User-Agent': 'WNT2-Private-Sync/0.5'}
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        if data is not None:
            headers['Content-Type'] = 'application/json'
        req = Request(self.meta_url if method == 'META' else self.url, data=data,
                      headers=headers, method='GET' if method == 'META' else method)
        try:
            with urlopen(req, timeout=12) as response:
                raw = response.read(350000)
                return json.loads(raw.decode('utf-8'))
        except HTTPError as exc:
            if exc.code == 404:
                return {'_missing': True}
            if exc.code in (409, 422):
                raise Conflict('Another device updated the state; retrying') from None
            # Do not log response contents: a proxy could echo private metadata.
            raise StoreError('GitHub API returned HTTP %s' % exc.code) from None
        except (OSError, URLError, ValueError) as exc:
            raise StoreError('Private store unavailable (%s)' % type(exc).__name__) from None

    def ensure_private(self):
        if not self._checked_private:
            info = self.transport('META')
            if info.get('private') is not True or info.get('full_name', '').lower() != self.repo.lower():
                raise StoreError('Refusing to write viewing history: repository must be private')
            self._checked_private = True

    def read(self):
        self.ensure_private()
        info = self.transport('GET')
        if info.get('_missing'):
            return blank_state(), None
        if info.get('type') != 'file' or not info.get('sha'):
            raise StoreError('Private sync file response is invalid')
        try:
            decoded = base64.b64decode(info['content'].replace('\n',''),validate=True)
            if len(decoded) > 250000:
                raise ValueError('Oversize')
            state = validated_state(json.loads(decoded.decode('utf-8')))
        except (ValueError, KeyError, TypeError, binascii.Error) as exc:
            raise StoreError('Private sync document cannot be parsed') from exc
        return state, info['sha']

    def merge_and_write(self, proposed, retries=3):
        """Fetch latest then CAS-write. A 409 reloads and *merges*, never overwrites."""
        validated_state(proposed)
        for attempt in range(retries):
            existing, sha = self.read()
            merged = merge_state(existing, proposed)
            if merged == existing:
                return merged
            data = {'message': 'Update private Kodi watched and resume state',
                    'content': base64.b64encode(json.dumps(merged, separators=(',', ':'),
                                                        sort_keys=True).encode()).decode()}
            if sha:
                data['sha'] = sha
            try:
                self.transport('PUT', data)
                return merged
            except Conflict:
                continue
        raise StoreError('Simultaneous private updates; safe retry deferred')
