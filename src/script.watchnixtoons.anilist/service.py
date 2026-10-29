"""Kodi service: tracks WatchNixtoons2 playback, queues, then syncs to AniList.

Does not scrape streams, change playback, or write to WatchNixtoons2 data.
"""
import json
import os
import time

import xbmc
import xbmcaddon
import xbmcvfs

from core import normalise, mapping_key, source_matches, exact_candidate, desired_progress
from storage import read_json, write_json
from anilist_api import APIError, search, details, save

ADDON = xbmcaddon.Addon('script.watchnixtoons.anilist')
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
STATE_FILE = os.path.join(PROFILE, 'state.json')
MAPPINGS_FILE = os.path.join(PROFILE, 'mappings.json')
SOURCES = [
    xbmcvfs.translatePath('special://profile/addon_data/plugin.video.watchnixtoons2.kodi19/recently_watched.dat'),
    xbmcvfs.translatePath('special://profile/addon_data/plugin.video.watchnixtoons2/recently_watched.dat'),
]


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[WNT2 AniList Sync] %s' % message, level)


def last_nixtoons_entry(now):
    """Recently watched is a *series* history, NOT an episode completed record."""
    found = None
    for path in SOURCES:
        try:
            timestamp = os.stat(path).st_mtime
            if abs(now - timestamp) > 180:
                continue
            with open(path, 'r', encoding='utf-8') as handle:
                content = json.load(handle)
            if not isinstance(content, dict) or not content:
                continue
            last = list(content.values())[-1]
            if not isinstance(last, dict) or not last.get('name'):
                continue
            candidate = {'name': last['name'], 'url': last.get('url', ''), 'modified': timestamp}
            if found is None or timestamp > found['modified']:
                found = candidate
        except (OSError, ValueError, TypeError):
            continue
    return found


def playback_info(player):
    try:
        tag = player.getVideoInfoTag()
        title = tag.getTVShowTitle() or xbmc.getInfoLabel('VideoPlayer.TVShowTitle')
        episode = int(tag.getEpisode() or 0)
        season = int(tag.getSeason() or 1)
        return (title, max(1, season), episode)
    except Exception:
        return None


def progress_info(player):
    try:
        duration = float(player.getTotalTime())
        watched = float(player.getTime())
        if duration < 60 or watched < 0:
            return 0.0
        return min(1.0, watched / duration)
    except Exception:
        return 0.0


class Tracker:
    def __init__(self):
        self.player = xbmc.Player()
        self.active = None
        self.pending_session = False
        self.current_file = None
        self.last_reconcile = 0
        self.last_warn = 0
        self.search_cooldown = {}
        self.state = read_json(STATE_FILE, {'pending': {}, 'done': {}})
        self.state.setdefault('pending', {})
        self.state.setdefault('done', {})

    def capture(self, now):
        info = playback_info(self.player)
        if not info or not info[0] or info[2] < 1:
            return None
        name, season, episode = info
        recent = last_nixtoons_entry(now)
        if not recent or not source_matches(name, recent['name']):
            return None
        return {'title': name, 'season': season, 'episode': episode,
                'key': mapping_key(name, season), 'first_seen': int(now)}

    def record(self, item):
        event_id = '%s|e%s' % (item['key'], item['episode'])
        if event_id not in self.state['done'] and event_id not in self.state['pending']:
            self.state['pending'][event_id] = item
            write_json(STATE_FILE, self.state)
            log('Queued completed playback for %s episode %s.' % (item['title'], item['episode']))

    def reconcile(self):
        token = ADDON.getSetting('token').strip()
        if not token:
            return
        mappings = read_json(MAPPINGS_FILE, {})
        # Process configured matches first, so unresolved titles never block others.
        ordered = sorted(self.state['pending'].items(),
                         key=lambda kv: 0 if kv[1]['key'] in mappings else 1)
        for event_id, event in ordered[:20]:
            key = event['key']
            if mappings.get(key, {}).get('ignore'):
                del self.state['pending'][event_id]
                self.state['done'][event_id] = {'ignored': True}
                write_json(STATE_FILE, self.state)
                continue
            mapping = mappings.get(key)
            if not mapping:
                if time.time() < self.search_cooldown.get(key, 0):
                    continue
                # Only first-season, unambiguous exact matches are mapped silently.
                # Later seasons and unfamiliar/differently titled anime require review.
                results = search(event['title'], token)
                chosen = exact_candidate(event['title'], event['season'], event['episode'], results)
                if not chosen:
                    self.search_cooldown[key] = time.time() + 900
                    continue
                mapping = {'id': chosen['id'], 'title': (chosen.get('title') or {}).get('english')
                           or (chosen.get('title') or {}).get('romaji') or event['title'], 'offset': 0}
                mappings[key] = mapping
                write_json(MAPPINGS_FILE, mappings)
                log('Matched %s to AniList #%s (exact title).' % (event['title'], mapping['id']))
            desired = int(event['episode']) - int(mapping.get('offset') or 0)
            if desired < 1:
                log('Pending offset correction for %s.' % key)
                continue
            anime = details(mapping['id'], token)
            if not anime:
                continue
            anime_episode_count = anime.get('episodes')
            if anime_episode_count is not None and desired > anime_episode_count:
                # A season split or mismatch: never write an impossible progress value.
                continue
            update = desired_progress(anime.get('mediaListEntry'), desired,
                                      anime_episode_count, anime.get('status'))
            if update:
                entry = anime.get('mediaListEntry') or {}
                result = save(anime['id'], entry.get('id'), update[0], update[1], token)
                if result.get('progress', 0) < desired:
                    raise APIError('AniList did not confirm the progress update.')
                log('Synced AniList #%s up to episode %s.' % (anime['id'], desired))
            self.state['done'][event_id] = {'anilist_id': anime['id'], 'episode': desired}
            del self.state['pending'][event_id]
            # Keep the file compact on the Firestick.
            while len(self.state['done']) > 500:
                del self.state['done'][next(iter(self.state['done']))]
            write_json(STATE_FILE, self.state)

    def tick(self, now):
        if self.player.isPlayingVideo():
            try:
                playing_file = self.player.getPlayingFile()
            except Exception:
                playing_file = None
            if playing_file and self.current_file and playing_file != self.current_file:
                self.active = None
                self.pending_session = False
            if playing_file:
                self.current_file = playing_file
            if not self.active:
                if not self.pending_session:
                    self.active = self.capture(now)
                    if self.active:
                        self.pending_session = True
                if not self.active:
                    # Kodi may take a moment to initialise playback info tags.
                    return
            ratio = progress_info(self.player)
            try:
                threshold = min(95, max(50, int(ADDON.getSetting('threshold') or '85'))) / 100.0
            except ValueError:
                threshold = 0.85
            if ratio >= threshold and not self.active.get('recorded'):
                self.record(self.active)
                self.active['recorded'] = True
        else:
            self.active = None
            self.pending_session = False
            self.current_file = None

        if now - self.last_reconcile >= 45:
            self.last_reconcile = now
            self.reconcile()


def run():
    log('Started (Kodi background service).')
    monitor = xbmc.Monitor()
    tracker = Tracker()
    while not monitor.abortRequested():
        try:
            if ADDON.getSetting('enabled') != 'false':
                tracker.tick(time.time())
        except (APIError, ValueError, OSError) as exc:
            if time.time() - tracker.last_warn > 180:
                log(str(exc), xbmc.LOGWARNING)
                tracker.last_warn = time.time()
        except Exception as exc:
            if time.time() - tracker.last_warn > 180:
                log('Unexpected tracker error: %s' % type(exc).__name__, xbmc.LOGERROR)
                tracker.last_warn = time.time()
        if monitor.waitForAbort(2):
            break
    log('Stopped.')


if __name__ == '__main__':
    run()
