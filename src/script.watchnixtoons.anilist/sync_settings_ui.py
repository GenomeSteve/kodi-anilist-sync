"""One-time opt-in setup. Keeps private GitHub tokens local to the Firestick."""
import os
import xbmcaddon
import xbmcgui
import xbmcvfs
from sync_protocol import episode_id
from private_store import GitHubStore, StoreError
from storage import read_json
from device_sync import local_records
from history_import import locate_myvideos

ADDON = xbmcaddon.Addon('script.watchnixtoons.anilist')
DIALOG = xbmcgui.Dialog()
TITLE = 'Background cross-device sync (beta)'


def run():
    while True:
        watched = ADDON.getSetting('auto_watched') == 'true'
        private = ADDON.getSetting('private_sync') == 'true'
        entries = [
            'Auto-restore watched ticks from AniList: %s' % ('ON' if watched else 'OFF'),
            'Private watched+resume sync: %s' % ('ON' if private else 'OFF'),
            'Set private GitHub repository',
            'Set private GitHub access token',
            'Test private connection (no writes)',
            'Enable rewatch for a particular episode',
            'Show background status',
            'Back'
        ]
        choice = DIALOG.select(TITLE, entries)
        if choice in (-1, 7):
            return
        if choice == 0:
            if not watched and not DIALOG.yesno(TITLE,
                 'Automatically add missing WatchNixtoons2 watched ticks for APPROVED AniList mappings, '
                 'while Kodi is idle? Existing watched ticks are never removed.'):
                continue
            ADDON.setSetting('auto_watched', 'false' if watched else 'true')
        elif choice == 1:
            if not private:
                if not ADDON.getSetting('private_repo').strip() or not ADDON.getSetting('private_token').strip():
                    DIALOG.ok(TITLE, 'Enter your private repository and token, then test the connection first.')
                    continue
                if not DIALOG.yesno(TITLE, 'Sync exact WNT2 episode ticks and resume bookmarks with '
                    'your PRIVATE GitHub repository? The token is stored locally in Kodi settings. '
                    'Each Firestick must use the same private repository.'):
                    continue
                try:
                    GitHubStore(ADDON.getSetting('private_repo').strip(),
                                ADDON.getSetting('private_token').strip()).read()
                except StoreError as exc:
                    DIALOG.ok(TITLE, str(exc))
                    continue
            ADDON.setSetting('private_sync', 'false' if private else 'true')
        elif choice == 2:
            value = DIALOG.input('GitHub private owner/repository name',
                                 ADDON.getSetting('private_repo')).strip()
            if value:
                ADDON.setSetting('private_repo', value)
        elif choice == 3:
            token = DIALOG.input('GitHub token: Contents read/write on PRIVATE repo only',
                                 type=xbmcgui.INPUT_ALPHANUM, option=xbmcgui.ALPHANUM_HIDE_INPUT).strip()
            if token:
                ADDON.setSetting('private_token', token)
        elif choice == 4:
            try:
                state, sha = GitHubStore(ADDON.getSetting('private_repo').strip(),
                                         ADDON.getSetting('private_token').strip()).read()
                DIALOG.ok(TITLE, 'Private connection OK. %d watched entries; %d resumes. '
                          'This test made no changes.' % (len(state['watched']), len(state['resumes'])))
            except StoreError as exc:
                DIALOG.ok(TITLE, str(exc))
        elif choice == 5:
            dirs, files = xbmcvfs.listdir('special://database')
            dbname = locate_myvideos(files)
            if not dbname:
                DIALOG.ok(TITLE, 'No Kodi episode records found for rewatch selection.')
                continue
            try:
                rows = local_records(xbmcvfs.translatePath('special://database/' + dbname))
            except Exception as exc:
                DIALOG.ok(TITLE, 'Cannot enumerate local episodes: %s' % type(exc).__name__)
                continue
            rows = sorted(rows, key=lambda x: (x['title'], x['season'], x['episode']))[:200]
            actions = ['Clear rewatch override'] + [
                '%s | Season %s, Episode %s' % (r['title'], r['season'], r['episode']) for r in rows]
            index = DIALOG.select('Choose exact local episode for a deliberate rewatch', actions)
            if index == 0:
                ADDON.setSetting('rewatch_episode', '')
            elif index > 0:
                key = episode_id(rows[index-1]['file'])
                if key and DIALOG.yesno(TITLE, 'Allow rewatch resume for %s? '
                    'Existing watched ticks and AniList episode counts will never be cleared.' % key):
                    ADDON.setSetting('rewatch_episode', key)
        elif choice == 6:
            profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
            state = read_json(os.path.join(profile, 'background.json'), {})
            DIALOG.ok(TITLE, 'Last status: %s\nLocal pending private changes: %s\n'
                      'Private viewing data is never stored in your public repository.' %
                      (state.get('last_status', 'No sync yet'),
                       len(state.get('pending', {}).get('resumes', {}))))
