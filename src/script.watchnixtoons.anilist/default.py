"""Small Fire TV-friendly setup and review menu, launched from Program add-ons."""
import os
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from core import parse_token
from anilist_api import viewer, search, details, APIError
from storage import read_json, write_json
from watched_db import recent_watched

ADDON = xbmcaddon.Addon('script.watchnixtoons.anilist')
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
STATE = os.path.join(PROFILE, 'state.json')
MAPPINGS = os.path.join(PROFILE, 'mappings.json')
DIAGNOSTICS = os.path.join(PROFILE, 'diagnostics.json')
DIALOG = xbmcgui.Dialog()
TITLE = 'WatchNixtoons2 -> AniList'


def ok(message):
    DIALOG.ok(TITLE, str(message))


def get_data():
    return read_json(STATE, {'pending': {}, 'done': {}}), read_json(MAPPINGS, {})


def authorise():
    options = ['Step 1: How to create an AniList application',
               'Step 2: Enter your client ID / show sign-in URL',
               'Step 3: Paste AniList access token',
               'Disconnect AniList (delete saved token)', 'Back']
    while True:
        pick = DIALOG.select('AniList authorisation', options)
        if pick in (-1, 4):
            return
        if pick == 0:
            DIALOG.textviewer('AniList: create an application',
                'On a phone or computer:\n\n'
                '1. Go to https://anilist.co/settings/developer\n'
                '2. Create a New Application. Name it WNT2 Fire TV Sync.\n'
                '3. Set Redirect URL to EXACTLY:\n'
                'https://anilist.co/api/v2/oauth/pin\n\n'
                'AniList gives you a Client ID and a Client Secret.\n'
                'Use only the Client ID. Never enter the Client Secret here.\n'
                'The authorisation token is private and gives access to your AniList account.')
        elif pick == 1:
            client = DIALOG.input('Enter AniList Client ID (numbers only)', ADDON.getSetting('client_id'))
            client = client.strip()
            if not client:
                continue
            if not client.isdigit():
                ok('Client ID must contain digits only.')
                continue
            ADDON.setSetting('client_id', client)
            DIALOG.textviewer('Open this on your PHONE browser',
                'Visit this URL on your phone (not Kodi):\n\n'
                'https://anilist.co/api/v2/oauth/authorize?client_id=%s&response_type=token\n\n'
                'Log in to AniList and approve the app. Copy the access token '
                'displayed on the PIN page. Paste it in Step 3 using the '
                'Fire TV mobile remote app keyboard.\n\n'
                'Do not share the access token in chats or screenshots.' % client)
        elif pick == 2:
            raw = DIALOG.input('Paste AniList access token', type=xbmcgui.INPUT_ALPHANUM,
                               option=xbmcgui.ALPHANUM_HIDE_INPUT)
            token = parse_token(raw)
            if not token:
                continue
            try:
                user = viewer(token)
                if not user.get('id'):
                    raise APIError('AniList did not return your account.')
            except APIError as exc:
                ok('Not connected: %s' % exc)
                continue
            ADDON.setSetting('token', token)
            ok('Connected to AniList as %s. Playback sync is enabled.' % user.get('name', 'your account'))
        elif pick == 3:
            if DIALOG.yesno(TITLE, 'Delete the AniList access token stored on this Firestick?'):
                ADDON.setSetting('token', '')
                ok('Disconnected. WatchNixtoons2 is unchanged.')


def choose_anime(series_title):
    """Human confirmation is mandatory for ambiguous titles."""
    token = ADDON.getSetting('token').strip()
    if not token:
        ok('Connect AniList first.')
        return None
    query = series_title
    while True:
        try:
            results = search(query, token)
        except APIError as exc:
            ok(str(exc))
            return None
        labels = []
        for item in results:
            t = item.get('title') or {}
            name = t.get('english') or t.get('romaji') or 'Unknown'
            suffix = ' | %s | %s episodes | AniList #%s' % (
                item.get('seasonYear') or '?', item.get('episodes') or '?', item['id'])
            labels.append(name + suffix)
        action = DIALOG.select('Select the CORRECT AniList series', labels + [
            '[Search another title]', '[Enter AniList ID manually]', '[Cancel]'])
        if action < 0 or action == len(labels) + 2:
            return None
        if action == len(labels):
            query = DIALOG.input('Search AniList for series', query).strip()
            if not query:
                return None
            continue
        if action == len(labels) + 1:
            entered = DIALOG.input('AniList ID (from anime page URL)').strip()
            if not entered.isdigit():
                continue
            try:
                item = details(int(entered), token)
            except APIError as exc:
                ok(str(exc))
                continue
        else:
            item = results[action]
        if not item.get('id'):
            ok('Could not find that anime. Try searching again.')
            continue
        t = item.get('title') or {}
        name = t.get('english') or t.get('romaji') or str(item['id'])
        if DIALOG.yesno(TITLE, 'Link "%s" to AniList "%s" (ID %s)?' % (
                series_title, name, item['id'])):
            return {'id': int(item['id']), 'title': name, 'offset': 0}


def map_pending():
    while True:
        state, mappings = get_data()
        pending = list(state.get('pending', {}).values())
        grouped = {}
        for item in pending:
            key = item['key']
            if key not in grouped:
                grouped[key] = {'title': item['title'], 'season': item['season'], 'episodes': []}
            grouped[key]['episodes'].append(item['episode'])
        not_mapped = [(k, d) for k, d in grouped.items() if k not in mappings]
        if not not_mapped:
            ok('No unmatched titles. Pending events for already mapped titles will retry automatically.')
            return
        labels = ['%s (site season %s) - episodes %s' % (
            d['title'], d['season'], ', '.join(map(str, sorted(set(d['episodes'])))))
                  for _, d in not_mapped]
        pick = DIALOG.select('Series requiring confirmation (%s)' % len(labels), labels)
        if pick < 0:
            return
        key, info = not_mapped[pick]
        chosen = DIALOG.select(info['title'], ['Find AniList match', 'Ignore this series', 'Back'])
        if chosen == 0:
            mapping = choose_anime(info['title'])
            if mapping:
                offset = DIALOG.input('Number of site episodes BEFORE this AniList season (usually 0)',
                                      '0', type=xbmcgui.INPUT_NUMERIC)
                if offset and offset.isdigit():
                    mapping['offset'] = int(offset)
                mappings = read_json(MAPPINGS, {})
                mappings[key] = mapping
                write_json(MAPPINGS, mappings)
                ok('Saved. Background sync will process queued episodes shortly.')
        elif chosen == 1 and DIALOG.yesno(TITLE, 'Ignore this series for AniList syncing?'):
            mappings[key] = {'ignore': True}
            write_json(MAPPINGS, mappings)


def edit_mappings():
    while True:
        mappings = read_json(MAPPINGS, {})
        keys = sorted(mappings)
        if not keys:
            ok('No mappings yet. Watch a complete episode, then review pending series.')
            return
        labels = ['%s -> %s' % (k, '[Ignored]' if m.get('ignore') else
                                '%s (ID %s, offset %s)' % (m.get('title'), m.get('id'), m.get('offset', 0)))
                  for k, m in sorted(mappings.items())]
        pick = DIALOG.select('Mapped series', labels)
        if pick < 0:
            return
        key = keys[pick]
        action = DIALOG.select(key, ['Change AniList match', 'Change episode offset',
                                     'Remove mapping', 'Back'])
        if action == 0:
            new = choose_anime(key.split('|s')[0])
            if new:
                mappings[key] = new
                write_json(MAPPINGS, mappings)
        elif action == 1:
            old = mappings[key]
            if old.get('ignore'):
                ok('Ignored titles have no episode offset.')
                continue
            offset = DIALOG.input('Subtract this number from WatchNixtoons2 episode number',
                                  str(old.get('offset', 0)), type=xbmcgui.INPUT_NUMERIC)
            if offset and offset.isdigit():
                mappings[key]['offset'] = int(offset)
                write_json(MAPPINGS, mappings)
        elif action == 2 and DIALOG.yesno(TITLE, 'Remove this mapping? Already synced episodes are not undone.'):
            del mappings[key]
            write_json(MAPPINGS, mappings)


def diagnostics():
    state, mappings = get_data()
    diag = read_json(DIAGNOSTICS, {})
    sources = []
    for source in ('plugin.video.watchnixtoons2.kodi19', 'plugin.video.watchnixtoons2'):
        p = xbmcvfs.translatePath('special://profile/addon_data/%s/recently_watched.dat' % source)
        sources.append('%s: %s' % (source, 'FOUND' if os.path.isfile(p) else 'Not found'))
    db_status = 'No database located'
    try:
        _dirs, files = xbmcvfs.listdir('special://database')
        dbs = sorted((f for f in files if f.startswith('MyVideos') and f.endswith('.db')),
                     key=lambda f: int(''.join(c for c in f if c.isdigit()) or 0), reverse=True)
        if dbs:
            path = xbmcvfs.translatePath('special://database/' + dbs[0])
            events = recent_watched(path, limit=30)
            db_status = '%s: %s recognised recent watched episode(s)' % (dbs[0], len(events))
            if events:
                last = events[0]
                db_status += '\nMost recent: %s, episode %s' % (last['title'], last['episode'])
    except Exception as exc:
        db_status = 'Could not read watched database: %s' % type(exc).__name__
    DIALOG.textviewer('Tracking diagnostics',
        'AniList: %s\nSync: %s\nThreshold: %s%%\nQueued episodes: %s\nSynced or ignored events: %s\nMappings: %s\n'
        'Last service status: %s\nDetails: %s\nUpdated: %s\n\n'
        'Kodi watched database: %s\n\nWatchNixtoons2 histories:\n%s\n\n'
        'If a detected episode is queued but not synced, use Review unmatched series. '
        'If the last service status is missing, restart Kodi to start the background service. '
        'Logs are tagged [WNT2 AniList Sync].' % (
            'Connected (token present)' if ADDON.getSetting('token') else 'Not connected',
            'On' if ADDON.getSetting('enabled') != 'false' else 'Off',
            ADDON.getSetting('threshold') or '85', len(state.get('pending', {})),
            len(state.get('done', {})), len(mappings), diag.get('stage', 'No service status yet'),
            diag.get('detail', 'None'), diag.get('updated', 'Unknown'), db_status, '\n'.join(sources)))


def run():
    while True:
        try:
            state, mappings = get_data()
            token = ADDON.getSetting('token').strip()
            enabled = ADDON.getSetting('enabled') != 'false'
            choices = [
                '%s background synchronisation' % ('Disable' if enabled else 'Enable'),
                'AniList account: %s' % ('Connected' if token else 'Connect'),
                'Review unmatched series (%s)' % len({v['key'] for v in state.get('pending', {}).values()
                                                     if v['key'] not in mappings}),
                'View/change anime mappings (%s)' % len(mappings),
                'Set watched threshold (%s%%)' % (ADDON.getSetting('threshold') or '85'),
                'View diagnostics', 'Test AniList authorisation', 'Historical watched import (manual)', 'Exit'
            ]
            selected = DIALOG.select(TITLE, choices)
            if selected in (-1, 8):
                return
            if selected == 0:
                ADDON.setSetting('enabled', 'false' if enabled else 'true')
            elif selected == 1:
                authorise()
            elif selected == 2:
                map_pending()
            elif selected == 3:
                edit_mappings()
            elif selected == 4:
                raw = DIALOG.input('Playback completion threshold (50-95%)',
                                   ADDON.getSetting('threshold') or '85', type=xbmcgui.INPUT_NUMERIC)
                if raw.isdigit() and 50 <= int(raw) <= 95:
                    ADDON.setSetting('threshold', raw)
                else:
                    ok('Enter a number between 50 and 95.')
            elif selected == 5:
                diagnostics()
            elif selected == 7:
                from historical_ui import run as history_import_run
                history_import_run(choose_anime)
            elif selected == 6:
                if not token:
                    ok('Not connected. Open AniList account first.')
                else:
                    try:
                        account = viewer(token)
                        ok('AniList API working. Signed in as %s.' % account.get('name', 'Unknown'))
                    except APIError as exc:
                        ok('AniList API error: %s' % exc)
        except (ValueError, OSError) as exc:
            ok('Could not read or write tracking data: %s' % exc)
            return


if __name__ == '__main__':
    run()
