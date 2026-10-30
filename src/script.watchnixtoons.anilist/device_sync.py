"""Conservative, user-invoked AniList -> local WatchNixtoons2 watched-tick sync.

This module is NEVER imported by the background tracking service. All WNT2
filesystem access is read-only. Kodi watched updates use JSON-RPC, gated by
explicit UI approval, and are made only to recognisable WNT2 playback URLs.
"""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote, urlencode

from core import mapping_key
from watched_db import parse_watched_url

MAX_DATABASE_ROWS = 25000
MAX_DIRECTORY_ROWS = 500
MAX_WRITES = 50
PLUGIN_IDS = ('plugin.video.watchnixtoons2', 'plugin.video.watchnixtoons2.kodi19')


class DeviceSyncError(Exception):
    pass


def record_for_url(url, playcount=0):
    data = parse_watched_url(url)
    if not data:
        return None
    result = dict(data)
    result.update({'key': mapping_key(data['title'], data['season']),
                   'file': url, 'playcount': max(0, int(playcount or 0))})
    return result


def local_records(database_path, limit=MAX_DATABASE_ROWS):
    """Read pre-existing plugin file rows; fail closed on truncated datasets."""
    if not database_path:
        raise DeviceSyncError('Kodi video database missing')
    uri = 'file:%s?mode=ro' % quote(str(Path(database_path).resolve()), safe='/')
    try:
        with closing(sqlite3.connect(uri, timeout=3, uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            rows = db.execute('SELECT strFilename, playCount FROM files '
                              'WHERE strFilename LIKE ? LIMIT ?',
                              ('%plugin.video.watchnixtoons2%actionResolve%', limit + 1)).fetchall()
    except (sqlite3.Error, OSError) as e:
        raise DeviceSyncError('Unable to read Kodi watched status: %s' % type(e).__name__) from None
    if len(rows) > limit:
        raise DeviceSyncError('Too many Kodi records; no partial sync allowed')
    return [data for path, count in rows if (data := record_for_url(path, count))]


def series_directory(series_url, plugin_id='plugin.video.watchnixtoons2'):
    """Build a restricted, non-playing request to WNT2's episode listing."""
    if plugin_id not in PLUGIN_IDS or not isinstance(series_url, str):
        raise DeviceSyncError('Unrecognised WatchNixtoons2 source')
    if (not series_url.startswith('/') or series_url.startswith('//') or '\\' in series_url
            or any(ord(ch) < 32 for ch in series_url) or '..' in series_url):
        raise DeviceSyncError('Unrecognised WatchNixtoons2 series path')
    return 'plugin://%s/?%s' % (plugin_id, urlencode({'action': 'actionEpisodesMenu', 'url': series_url}))


def rpc_call(execute, method, params):
    """Inject Kodi xbmc.executeJSONRPC for deterministic offline testing."""
    try:
        reply = json.loads(execute(json.dumps({'jsonrpc': '2.0', 'id': 1,
                                               'method': method, 'params': params})))
    except (ValueError, TypeError) as exc:
        raise DeviceSyncError('Kodi JSON-RPC returned invalid JSON') from exc
    if not isinstance(reply, dict) or reply.get('error') is not None or 'result' not in reply:
        raise DeviceSyncError('Kodi JSON-RPC %s failed: %s' % (method, str(reply.get('error'))[:100]))
    return reply['result']


def listing_records(execute, series_url, plugin_id='plugin.video.watchnixtoons2'):
    """Discover exact playable paths from WNT2; never play or scrape them directly."""
    directory = series_directory(series_url, plugin_id)
    result = rpc_call(execute, 'Files.GetDirectory',
                      {'directory': directory, 'media': 'video', 'properties': ['playcount']})
    files = result.get('files') if isinstance(result, dict) else None
    if not isinstance(files, list) or len(files) > MAX_DIRECTORY_ROWS:
        raise DeviceSyncError('Episode listing is missing or too large to verify')
    output = []
    for entry in files:
        if not isinstance(entry, dict) or entry.get('filetype') != 'file':
            continue
        data = record_for_url(entry.get('file'), entry.get('playcount', 0))
        if data:
            output.append(data)
    return output


def merge_records(*lists):
    """Merge DB and current addon listing, with an existing watched tick winning."""
    seen = {}
    for records in lists:
        for item in records:
            uri = item['file']
            old = seen.get(uri)
            if not old or item['playcount'] > old['playcount']:
                seen[uri] = item
    return list(seen.values())


def make_pull_plan(records, key, mapping, ani_entry, max_writes=MAX_WRITES):
    """Only map a known AniList series to exact playable local WNT2 episode URLs."""
    if not isinstance(mapping, dict) or mapping.get('ignore') or not mapping.get('id'):
        raise DeviceSyncError('An approved AniList mapping is required')
    if int(mapping['id']) != int(ani_entry.get('id') or 0):
        raise DeviceSyncError('AniList identity does not match the approved mapping')
    progress = int((ani_entry.get('mediaListEntry') or {}).get('progress') or 0)
    count = ani_entry.get('episodes')
    offset = int(mapping.get('offset', 0) or 0)
    if not key or offset < 0 or progress < 0 or (count is not None and progress > int(count)):
        raise DeviceSyncError('Ambiguous progress, episode count or season offset')
    chosen, skipped_watched, skipped_other = [], 0, 0
    for item in merge_records(records):
        validated = record_for_url(item.get('file'), item.get('playcount', 0))
        if not validated or validated['key'] != key:
            skipped_other += 1
            continue
        remote_episode = validated['episode'] - offset
        if remote_episode < 1 or remote_episode > progress:
            skipped_other += 1
        elif validated['playcount'] > 0:
            skipped_watched += 1
        else:
            chosen.append(validated)
    chosen.sort(key=lambda item: (item['episode'], item['file']))
    if len(chosen) > max_writes:
        raise DeviceSyncError('Over %d possible updates: refusing a partial batch' % max_writes)
    return {'key': key, 'anilist_id': int(mapping['id']), 'progress': progress,
            'offset': offset, 'to_mark': chosen, 'already_watched': skipped_watched,
            'not_eligible': skipped_other}


def apply_pull_plan(plan, execute, confirmed=False):
    """Sole mutation path. No direct SQL updates and no unwatched changes."""
    if not confirmed:
        raise DeviceSyncError('Explicit confirmation required before any writes')
    files = plan.get('to_mark', [])
    if len(files) > MAX_WRITES:
        raise DeviceSyncError('Batch exceeds maximum writes')
    succeeded, failed = [], []
    for item in files:
        valid = record_for_url(item.get('file'))
        if (not valid or valid['key'] != plan.get('key') or
                valid['episode'] - int(plan['offset']) not in range(1, int(plan['progress']) + 1)):
            failed.append({'episode': item.get('episode'), 'reason': 'Unsafe or mismatched path'})
            continue
        try:
            # Kodi owns all changes. We never touch sqlite or modify the add-on.
            rpc_call(execute, 'Files.SetFileDetails',
                     {'file': valid['file'], 'media': 'video', 'playcount': 1})
            # Kodi may create/modify file records only after episode listing resolves.
            # A successful RPC is NOT proof that a tick is visible in the UI.
            succeeded.append(valid['episode'])
        except DeviceSyncError as exc:
            failed.append({'episode': valid['episode'], 'reason': str(exc)})
    return {'accepted': succeeded, 'failed': failed,
            'requires_visual_verification': bool(succeeded)}
