"""Opt-in historical AniList importer. Never run by the background service."""
import os

import xbmcaddon
import xbmcgui
import xbmcvfs

from history_import import HistoryError, locate_myvideos, read_history, make_plan, import_confirmed
from anilist_api import APIError, details, save
from storage import read_json

ADDON = xbmcaddon.Addon('script.watchnixtoons.anilist')
DIALOG = xbmcgui.Dialog()
TITLE = 'AniList historical import'
MAPPINGS_FILE = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), 'mappings.json')


def run(choose_anime):
    """The only entrypoint: interactive selection followed by explicit consent."""
    if not DIALOG.yesno(TITLE,
                        'Read your existing WatchNixtoons2 watched ticks? '
                        'This scan does not change Kodi or AniList.'):
        return
    token = ADDON.getSetting('token').strip()
    if not token:
        DIALOG.ok(TITLE, 'Please connect your AniList account first.')
        return
    try:
        _dirs, filenames = xbmcvfs.listdir('special://database')
        newest = locate_myvideos(filenames)
        if not newest:
            raise HistoryError('No Kodi MyVideos database found.')
        source = xbmcvfs.translatePath('special://database/' + newest)
        groups = read_history(source)
    except (HistoryError, OSError) as exc:
        DIALOG.ok(TITLE, str(exc))
        return
    if not groups:
        DIALOG.ok(TITLE, 'No historical episodes could be identified from Kodi watched ticks. '
                  'Recent series history alone is not evidence that an episode was watched.')
        return
    keys = sorted(groups)
    while True:
        names = ['%s · season %d · %d watched tick(s)' %
                 (groups[key]['title'], groups[key]['season'], len(groups[key]['episodes']))
                 for key in keys]
        choice = DIALOG.select('Historical import: choose ONE series (%d found)' % len(keys),
                               names + ['[Finish without further changes]'])
        if choice < 0 or choice == len(keys):
            return
        group = groups[keys[choice]]
        mappings = read_json(MAPPINGS_FILE, {})
        mapping = mappings.get(group['key'])
        if mapping and mapping.get('ignore'):
            DIALOG.ok(TITLE, 'This series is ignored in your existing sync mappings.')
            continue
        if mapping and mapping.get('id'):
            if not DIALOG.yesno(TITLE, 'Use your existing mapping to %s (AniList ID %s)?' %
                                (mapping.get('title', 'this anime'), mapping['id'])):
                continue
        else:
            DIALOG.ok(TITLE, 'Please choose the correct AniList title. '
                      'This will not change your normal playback mappings.')
            mapping = choose_anime(group['title'])
            if not mapping:
                continue
            if group['season'] != 1:
                DIALOG.ok(TITLE, 'This appears to be a later season. Verify the AniList season '
                          'and account for any episode numbering differences.')
                raw = DIALOG.input('How many source episodes precede this AniList season?',
                                   '0', type=xbmcgui.INPUT_NUMERIC)
                if not raw or not raw.isdigit():
                    continue
                mapping = dict(mapping, offset=int(raw))
        try:
            anime = details(mapping['id'], token)
            if not anime or int(anime.get('id', 0)) != int(mapping['id']):
                raise HistoryError('AniList did not confirm the selected series.')
            existing = anime.get('mediaListEntry') or {}
            plan = make_plan(group['episodes'], mapping.get('offset', 0),
                             existing.get('progress') or 0, anime.get('episodes'))
        except (APIError, HistoryError) as exc:
            DIALOG.ok(TITLE, 'Preview unavailable. Nothing changed: %s' % str(exc))
            continue
        # Always show detected episode evidence, gaps and proposed progress.
        source_episodes = ', '.join(str(n) for n in group['episodes'])
        details_text = ('Kodi: %s · site season %s\n'
                        'Watched episode ticks: %s\n'
                        'AniList ID: %s\n'
                        'AniList progress: %s\n'
                        'Proposed progress: %s\n'
                        'Episode offset: %s\n'
                        'Decision: %s\n\n'
                        'No change to WatchNixtoons2 or Kodi history. '
                        'AniList is only changed if you approve the next prompt.') % (
                            group['title'], group['season'], source_episodes[:1600], anime['id'],
                            plan['before'], plan['after'], mapping.get('offset', 0), plan['reason'])
        DIALOG.textviewer('Historical import preview (read only)', details_text)
        if not plan['changed']:
            continue
        if not DIALOG.yesno(TITLE,
                            'Update AniList ID %s from episode %d to %d? '
                            'This is an irreversible change to your AniList watchlist.' %
                            (anime['id'], plan['before'], plan['after']),
                            yeslabel='Update AniList', nolabel='Cancel'):
            continue
        try:
            # Check again to avoid stale preview accidentally overwriting
            # progress from the existing background service or another client.
            fresh = details(mapping['id'], token)
            fresh_progress = int((fresh.get('mediaListEntry') or {}).get('progress') or 0)
            new_plan = make_plan(group['episodes'], mapping.get('offset', 0),
                                 fresh_progress, fresh.get('episodes'))
            if fresh_progress != plan['before'] or new_plan['after'] != plan['after']:
                DIALOG.ok(TITLE, 'AniList progress changed since preview. No update made. '
                          'Please preview this series again.')
                continue
            outcome = import_confirmed(group, mapping, fresh, token, True, save)
            if outcome['outcome'] == 'updated':
                DIALOG.ok(TITLE, 'Imported: AniList progress %d → %d. '
                          'Your Kodi playback settings were not changed.' %
                          (outcome['before'], outcome['after']))
            else:
                DIALOG.ok(TITLE, 'Nothing imported: %s' % outcome.get('reason', outcome['outcome']))
        except (APIError, HistoryError) as exc:
            DIALOG.ok(TITLE, 'Import failed or was not confirmed. Check AniList before retrying: %s' % exc)
