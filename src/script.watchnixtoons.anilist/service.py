"""Kodi service: tracks WatchNixtoons2 playback, queues, then syncs to AniList.

Does not scrape streams, change playback, or write to WatchNixtoons2 data.
"""
import json
import os
import time
import threading

import xbmc
import xbmcaddon
import xbmcvfs

from core import normalise, mapping_key, source_matches, exact_candidate, desired_progress
from storage import read_json, write_json
from anilist_api import APIError, search, details, save
from watched_db import recent_watched

ADDON = xbmcaddon.Addon('script.watchnixtoons.anilist')
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
STATE_FILE = os.path.join(PROFILE, 'state.json')
MAPPINGS_FILE = os.path.join(PROFILE, 'mappings.json')
DIAG_FILE = os.path.join(PROFILE, 'diagnostics.json')
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
        self.last_db_check = 0
        self.diagnostics = read_json(DIAG_FILE, {})
        self.diagnostics.setdefault('last_event', 'Service started; waiting for a watched episode')
        self.search_cooldown = {}
        self.state = read_json(STATE_FILE, {'pending': {}, 'done': {}})
        self.state.setdefault('pending', {})
        self.state.setdefault('done', {})

    def note(self, stage, detail=''):
        current = {'stage': stage, 'detail': detail}
        if (self.diagnostics.get('stage'), self.diagnostics.get('detail')) != (stage, detail):
            self.diagnostics.update(current)
            self.diagnostics['updated'] = time.strftime('%Y-%m-%d %H:%M:%S')
            write_json(DIAG_FILE, self.diagnostics)
            log('%s: %s' % (stage, detail))

    def scan_watched_database(self, now):
        """Fallback when the upstream add-on omitted episode metadata."""
        if now - self.last_db_check < 20:
            return
        self.last_db_check = now
        _dirs, filenames = xbmcvfs.listdir('special://database')
        candidates = sorted((f for f in filenames if f.startswith('MyVideos') and f.endswith('.db')),
                            key=lambda s: int(''.join(c for c in s if c.isdigit()) or 0), reverse=True)
        if not candidates:
            self.note('Waiting for Kodi database', 'No MyVideos database found')
            return
        path = xbmcvfs.translatePath('special://database/' + candidates[0])
        for item in recent_watched(path, now):
            # A database record is accepted only if Kodi marked the WNT2 episode
            # watched, with a recent lastPlayed and an explicit episode in its URL.
            item['key'] = mapping_key(item['title'], item['season'])
            item['first_seen'] = int(now)
            self.record(item, origin='Kodi watched database')

    def capture(self, now):
        info = playback_info(self.player)
        if not info or not info[0] or info[2] < 1:
            if last_nixtoons_entry(now):
                self.note('Awaiting Kodi watched tick', 'Playback metadata has no episode number; read-only database fallback is enabled')
            return None
        name, season, episode = info
        recent = last_nixtoons_entry(now)
        if not recent or not source_matches(name, recent['name']):
            return None
        return {'title': name, 'season': season, 'episode': episode,
                'key': mapping_key(name, season), 'first_seen': int(now)}

    def record(self, item, origin="playback"):

        event_id = '%s|e%s' % (item['key'], item['episode'])
        if event_id not in self.state['done'] and event_id not in self.state['pending']:
            self.state['pending'][event_id] = item
            write_json(STATE_FILE, self.state)
            self.note('Queued episode', '%s episode %s (%s)' % (item['title'], item['episode'], origin))

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
                    self.note('Review required', '%s (confirm AniList series in add-on)' % event['title'])
                    continue
                mapping = {'id': chosen['id'], 'title': (chosen.get('title') or {}).get('english')
                           or (chosen.get('title') or {}).get('romaji') or event['title'], 'offset': 0}
                mappings[key] = mapping
                write_json(MAPPINGS_FILE, mappings)
                self.note('Matched series', '%s to AniList #%s' % (event['title'], mapping['id']))
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
                self.note('AniList updated', 'AniList #%s episode %s' % (anime['id'], desired))
            self.note('Sync confirmed', '%s episode %s (AniList #%s)' % (event['title'], desired, anime['id']))
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
                self.active = self.capture(now)
                if self.active:
                    self.pending_session = True
                # Important: never return early. Database detection and queued
                # AniList requests must keep running even with incomplete tags.
            if self.active:
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

        # Kodi's own watched ticks are our independent fallback for missing
        # metadata; safe to check both during and after playback.
        self.scan_watched_database(now)
        if now - self.last_reconcile >= 45:
            self.last_reconcile = now
            self.reconcile()


def run():
    log('Started (Kodi background service).')
    monitor = xbmc.Monitor()
    tracker = Tracker()
    from auto_sync import BackgroundEngine
    background = BackgroundEngine(ADDON, xbmc, xbmcvfs, PROFILE)
    background_worker = None
    def run_optional_background():
        try:
            background.tick(time.time(), tracker.player.isPlayingVideo())
        except Exception as exc:
            kind = type(exc).__name__
            background.state['stats']['last_error'] = '%s (%s)' % (kind, time.strftime('%H:%M:%S'))
            background.note('Private sync failed: %s; retrying safely' % kind)
            log('Optional background sync error: %s' % kind, xbmc.LOGWARNING)
    tracker.note('Service running', 'Waiting for WatchNixtoons2 watched episodes')
    while not monitor.abortRequested():
        try:
            if ADDON.getSetting('enabled') != 'false':
                tracker.tick(time.time())
        except (APIError, ValueError, OSError) as exc:
            if time.time() - tracker.last_warn > 180:
                tracker.note('Retrying after error', str(exc))
                log(str(exc), xbmc.LOGWARNING)
                tracker.last_warn = time.time()
        except Exception as exc:
            if time.time() - tracker.last_warn > 180:
                tracker.note('Service error', type(exc).__name__)
                log('Unexpected tracker error: %s' % type(exc).__name__, xbmc.LOGERROR)
                tracker.last_warn = time.time()
        # Separate worker so GitHub/AniList outages cannot block the existing
        # 2-second outgoing playback monitor. Never start overlapping workers.
        if background_worker is None or not background_worker.is_alive():
            if ADDON.getSetting('auto_watched') == 'true' or ADDON.getSetting('private_sync') == 'true':
                background_worker = threading.Thread(target=run_optional_background,
                                                     name='WNT2OptionalSync', daemon=True)
                background_worker.start()
        if monitor.waitForAbort(2):
            break
    log('Stopped.')


if __name__ == '__main__':
    run()
