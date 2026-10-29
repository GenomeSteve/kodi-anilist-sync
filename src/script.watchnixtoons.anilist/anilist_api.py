"""Tiny standard-library AniList client, with bounded network requests."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = 'https://graphql.anilist.co'
MEDIA_SEARCH = '''query($search:String!){Page(page:1,perPage:15){media(search:$search,type:ANIME){id episodes status seasonYear title{romaji english native} synonyms}}}'''
MEDIA_DETAILS = '''query($id:Int!){Media(id:$id,type:ANIME){id episodes status title{romaji english native} mediaListEntry{id progress status}}}'''
SAVE_PROGRESS = '''mutation($id:Int,$mediaId:Int!,$progress:Int!,$status:MediaListStatus!){SaveMediaListEntry(id:$id,mediaId:$mediaId,progress:$progress,status:$status){id progress status}}'''
VIEWER = 'query{Viewer{id name}}'


class APIError(Exception):
    pass


def graphql(query, variables=None, token=None):
    body = json.dumps({'query': query, 'variables': variables or {}}).encode('utf-8')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json',
               'User-Agent': 'WatchNixtoons2-AniList-Sync/0.1 (Kodi)'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(ENDPOINT, data=body, headers=headers, method='POST')
    try:
        with urlopen(request, timeout=9) as response:
            result = json.loads(response.read(150000).decode('utf-8'))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise APIError('AniList authorisation rejected. Check your token.') from None
        if exc.code == 429:
            raise APIError('AniList rate limit reached. Will retry later.') from None
        raise APIError('AniList returned HTTP %s.' % exc.code) from None
    except (URLError, ValueError, OSError) as exc:
        raise APIError('AniList connection failed (%s).' % type(exc).__name__) from None
    if result.get('errors'):
        # Avoid putting raw server responses or user credentials into Kodi logs.
        msg = (result['errors'][0] or {}).get('message', 'Unspecified API error')
        raise APIError('AniList rejected request: %s' % str(msg)[:130])
    return result.get('data') or {}


def viewer(token):
    return graphql(VIEWER, token=token).get('Viewer') or {}


def search(title, token=None):
    return ((graphql(MEDIA_SEARCH, {'search': title}, token).get('Page') or {}).get('media') or [])


def details(media_id, token):
    return graphql(MEDIA_DETAILS, {'id': int(media_id)}, token).get('Media') or {}


def save(media_id, entry_id, episode, status, token):
    variables = {'mediaId': int(media_id), 'progress': int(episode), 'status': status}
    if entry_id:
        variables['id'] = int(entry_id)
    return graphql(SAVE_PROGRESS, variables, token).get('SaveMediaListEntry') or {}
