"""Manual, opt-in AniList -> local watched tick restore.

Never invoked by service.py. Never attempts to mark a tick without showing
its series/episode details and obtaining a separate user confirmation.
"""
import json
import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from anilist_api import APIError, details
from core import mapping_key
from device_sync import (DeviceSyncError, local_records, listing_records,
                         make_pull_plan, apply_pull_plan, PLUGIN_IDS)
from history_import import locate_myvideos
from storage import read_json, write_json

ADDON = xbmcaddon.Addon('script.watchnixtoons.anilist')
DIALOG = xbmcgui.Dialog()
TITLE = 'Cross-device watched ticks'
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
MAPPINGS_PATH = os.path.join(PROFILE, 'mappings.json')
RECENT_PATHS = [xbmcvfs.translatePath('special://profile/addon_data/%s/recently_watched.dat' % addon)
                for addon in PLUGIN_IDS]


def recent_series():
    """Show folders recorded by WatchNixtoons2 on THIS device; no network calls."""
    result = {}
    for path in RECENT_PATHS:
        try:
            with open(path, encoding='utf-8') as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                continue
            for item in data.values():
                if not isinstance(item, dict) or not item.get('name') or not item.get('url'):
                    continue
                source = item['url']
                if not isinstance(source, str) or not source.startswith('/') or source.startswith('//'):
                    continue
                key = mapping_key(item['name'], 1)
                result[key] = {'key': key, 'name': item['name'], 'url': source}
        except (OSError, ValueError):
            continue
    return result


def indexed_database():
    _dirs, files = xbmcvfs.listdir('special://database')
    newest = locate_myvideos(files)
    if not newest:
        raise DeviceSyncError('No Kodi MyVideos database found')
    return xbmcvfs.translatePath('special://database/' + newest)


def execute_sync(choose_anime):
    if not DIALOG.yesno(TITLE,
                        'Preview AniList watched progress on THIS Firestick? '
                        'Nothing is changed until you explicitly approve an episode list.'):
        return
    token = ADDON.getSetting('token').strip()
    if not token:
        DIALOG.ok(TITLE, 'Connect this Firestick to the SAME AniList account first.')
        return
    try:
        records = local_records(indexed_database())
    except (DeviceSyncError, OSError) as exc:
        DIALOG.ok(TITLE, str(exc))
        return
    recently = recent_series()
    mappings = read_json(MAPPINGS_PATH, {})
    known = {item['key']: item['title'] for item in records}
    for key, item in recently.items():
        known[key] = item['name']
    if not known:
        DIALOG.ok(TITLE, 'No local series found. Open the anime episode list in WatchNixtoons2, '
                  'return here and try again. No records were modified.')
        return
    while True:
        keys = sorted(known)
        selection = DIALOG.select('Choose a series to restore watched ticks',
                                  ['%s %s' % (known[k], '[Mapped]' if k in mappings else '[Needs mapping]')
                                   for k in keys])
        if selection < 0:
            return
        key = keys[selection]
        mapping = mappings.get(key)
        if mapping and mapping.get('ignore'):
            DIALOG.ok(TITLE, 'This series is ignored in AniList mappings.')
            continue
        if not mapping or not mapping.get('id'):
            mapping = choose_anime(known[key])
            if not mapping:
                continue
            # No guessing later seasons or cross-season episode numbering.
            if not key.endswith('|s1'):
                raw = DIALOG.input('Episodes BEFORE this AniList season (number)', '0',
                                   type=xbmcgui.INPUT_NUMERIC)
                if not raw.isdigit():
                    continue
                mapping = dict(mapping, offset=int(raw))
            if not DIALOG.yesno(TITLE, 'Save this AniList mapping on this Firestick? '
                                'This does not alter any watched ticks.'):
                continue
            mappings = read_json(MAPPINGS_PATH, {})
            mappings[key] = mapping
            write_json(MAPPINGS_PATH, mappings)
        else:
            if not DIALOG.yesno(TITLE, 'Use existing AniList mapping %s (ID %s)?' %
                                (mapping.get('title', 'Unknown'), mapping['id'])):
                continue
        try:
            remote = details(mapping['id'], token)
            if int(remote.get('id') or 0) != int(mapping['id']):
                raise DeviceSyncError('AniList did not confirm the selected title')
            available = list(records)
            warning = ''
            # Resolve episode listing to include episodes not present in the local DB.
            # If Kodi or the video addon cannot enumerate it, we do not invent URLs.
            if key in recently:
                try:
                    listed = listing_records(xbmc.executeJSONRPC, recently[key]['url'])
                    available.extend(listed)
                except DeviceSyncError as exc:
                    warning = 'Episode listing unavailable (%s). Existing Kodi paths only.' % exc
            plan = make_pull_plan(available, key, mapping, remote)
        except (DeviceSyncError, APIError, ValueError) as exc:
            DIALOG.ok(TITLE, 'Unable to prepare safe preview. Nothing changed: %s' % exc)
            continue
        lines = ['Series: %s' % known[key],
                 'AniList ID: %s' % plan['anilist_id'],
                 'AniList completed-through episode: %s' % plan['progress'],
                 'Source episode offset: %s' % plan['offset'],
                 'Already ticked locally: %s' % plan['already_watched'],
                 'Eligible ticks to add: %s' % len(plan['to_mark']),
                 'Only exact recognised WatchNixtoons2 playback URLs are eligible.',
                 'This cannot sync cartoons not represented in AniList.',
                 warning, '', 'EPISODES PROPOSED:']
        lines += ['Episode %s' % item['episode'] for item in plan['to_mark']]
        DIALOG.textviewer('PREVIEW ONLY: no changes made', '\n'.join(lines))
        if not plan['to_mark']:
            continue
        if not DIALOG.yesno(TITLE,
                            'Mark %d matching local episode(s) watched? '
                            'This only affects THIS Firestick. '
                            'Previously watched ticks will not be cleared.' % len(plan['to_mark']),
                            yeslabel='Mark watched', nolabel='Cancel'):
            continue
        try:
            # Re-read remote status and local DB AFTER confirmation; refuse changes
            # if the remote identity/progress or local snapshot changed.
            fresh = details(mapping['id'], token)
            if int(fresh.get('id') or 0) != int(mapping['id']):
                raise DeviceSyncError('AniList title changed; preview again')
            if (fresh.get('mediaListEntry') or {}).get('progress') != \
                    (remote.get('mediaListEntry') or {}).get('progress'):
                raise DeviceSyncError('AniList progress changed; please preview again')
            fresh_records = local_records(indexed_database())
            fresh_plan = make_pull_plan(fresh_records +
                [item for item in available if item['file'] not in {r['file'] for r in records}],
                key, mapping, fresh)
            if [i['file'] for i in fresh_plan['to_mark']] != [i['file'] for i in plan['to_mark']]:
                raise DeviceSyncError('Local watched status changed; preview again')
            result = apply_pull_plan(fresh_plan, xbmc.executeJSONRPC, confirmed=True)
            DIALOG.ok(TITLE, 'Kodi accepted %d watched-tick update(s); %d failed. '
                      'Open WatchNixtoons2 to verify the tick icons. '
                      'No AniList progress was changed. Errors: %s' %
                      (len(result['accepted']), len(result['failed']),
                       '; '.join(i['reason'] for i in result['failed'])[:600] or 'none'))
        except (DeviceSyncError, APIError, ValueError, OSError) as exc:
            DIALOG.ok(TITLE, 'No further changes attempted: %s' % exc)
