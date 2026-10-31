"""Opt-in Kodi background receiver and private cross-device bookmark bridge.

All write operations use Kodi JSON-RPC; never touch the SQLite database.
Per-series AniList mappings must already be approved by the user. The original
outgoing service stays independent, and every new mode starts disabled.
"""
import json
import os
import time
import uuid

from anilist_api import details
from core import mapping_key, source_matches
from passive_resume import selected_episode, verified_source
from device_sync import (DeviceSyncError, apply_pull_plan,
                         local_records, make_pull_plan, merge_records, rpc_call)
from history_import import locate_myvideos
from private_store import GitHubStore, StoreError
from storage import read_json, write_json
from sync_protocol import (SyncStateError, add_resume, add_watched, blank_state,
                           episode_id, incoming_resume, merge_state, validate_position)


PULL_INTERVAL = 900             # 15 min; AniList API rate-conscious
PRIVATE_INTERVAL = 90           # 1.5 min; smaller network footprint
MAX_AUTO_WRITES = 15           # per sync cycle
MAX_LOCAL_LOOKUPS = 90


class BackgroundEngine:
    def __init__(self, addon, xbmc, xbmcvfs, profile):
        self.addon, self.xbmc, self.vfs = addon, xbmc, xbmcvfs
        self.profile = profile
        self.state_path = os.path.join(profile, 'background.json')
        self.mappings_path = os.path.join(profile, 'mappings.json')
        self.state = read_json(self.state_path, {})
        self.state.setdefault('device', str(uuid.uuid4()))
        self.state.setdefault('last_pull', 0)
        self.state.setdefault('last_private', 0)
        self.state.setdefault('last_capture', 0)
        self.state.setdefault('last_flush', 0)
        self.state.setdefault('counter', 0)
        self.state.setdefault('observed', {})
        self.state.setdefault('pending', blank_state())
        self.state.setdefault('last_status', 'Background features off')
        self.state.setdefault('stats', {})
        self._remote = None
        self._selected = None
        self._selected_attempt = None
        self._playback_restored = None
        write_json(self.state_path, self.state)

    def enabled(self, key):
        return self.addon.getSetting(key) == 'true'

    def note(self, value):
        self.state['last_status'] = value[:180]
        write_json(self.state_path, self.state)

    def metric(self, field, count=1, direction=None):
        stats = self.state['stats']
        stats[field] = int(stats.get(field, 0)) + count
        if direction:
            stats['last_' + direction] = time.strftime('%Y-%m-%d %H:%M:%S')
        write_json(self.state_path, self.state)

    def observe_selected(self, now):
        """Passively identify a WNT2 episode currently highlighted in Kodi.

        No plugin directory calls. On Kodi builds where a plugin URL is not yet
        a database file, keep the exact selection for a verified seek on start.
        """
        url = selected_episode(self.xbmc)
        if not url:
            return
        key = episode_id(url)
        if not self._selected or self._selected['url'] != url:
            self._selected = {'url': url, 'key': key, 'at': now}
            self._selected_attempt = None
            self._playback_restored = None
            self.metric('episodes_recognised')
        point = (self._remote or {}).get('resumes', {}).get(key)
        if not point or key in (self._remote or {}).get('watched', {}):
            return
        # Retry a failed early bookmark after the user returns to this screen,
        # but don't hammer Kodi's video database every two seconds.
        if self._selected_attempt and now - self._selected_attempt < 60:
            return
        self._selected_attempt = now
        existing = self._bookmark(url)
        if existing and existing['position'] > 30:
            if abs(existing['position'] - point['position']) < 2:
                self.state['observed'][key] = {
                    'signature': '%s/%s' % (existing['position'], existing['total']),
                    'at': point['event']['at']}
                write_json(self.state_path, self.state)
            return
        fresh = incoming_resume(0, point, watched=False)
        if not fresh:
            return
        try:
            self._write_resume(url, fresh)
            confirmed = self._bookmark(url)
            if confirmed and abs(confirmed['position'] - fresh['position']) < 2:
                self._playback_restored = key
                self.state['observed'][key] = {
                    'signature': '%s/%s' % (confirmed['position'], confirmed['total']),
                    'at': point['event']['at']}
                self.metric('resumes_downloaded', direction='download')
                self.note('Browse restore confirmed for selected episode')
        except DeviceSyncError:
            # A brand-new WNT2 plugin URL may not exist in MyVideos yet.
            # The verified on-playback seek is the safe fallback.
            self.note('Episode recognised; bookmark will be checked on playback')

    def apply_playback_resume(self, player, now):
        """Resume a first-time episode only with exact, recently verified source.

        The source is the user-selected WNT2 ListItem, never a CDN URL. Never
        seek unrelated content, override an existing local bookmark, or jump a
        currently playing episode that's already progressed normally.
        """
        if not self._selected or self._playback_restored == self._selected['key']:
            return
        point = (self._remote or {}).get('resumes', {}).get(self._selected['key'])
        if not point or self._selected['key'] in (self._remote or {}).get('watched', {}):
            return
        if not verified_source(player, self._selected, self.vfs, now):
            return
        try:
            current, total = float(player.getTime()), float(player.getTotalTime())
            if current > 25 or current < 0 or total < 60:
                return
            if abs(total - float(point['total'])) > max(45, float(point['total']) * .12):
                return
            local = self._bookmark(self._selected['url'])
            if local and abs(local['position'] - point['position']) > 3:
                # A nontrivial local bookmark of unknown age belongs to Kodi.
                return
            player.seekTime(float(point['position']))
            self._playback_restored = self._selected['key']
            self.state['observed'][self._selected['key']] = {
                'signature': '%s/%s' % (point['position'], point['total']),
                'at': point['event']['at']}
            self.metric('resumes_downloaded', direction='download')
            self.note('Verified first-playback restore to %d seconds' % point['position'])
        except (AttributeError, RuntimeError, ValueError, TypeError):
            return

    def records(self):
        _dirs, files = self.vfs.listdir('special://database')
        database = locate_myvideos(files)
        if not database:
            return []
        return local_records(self.vfs.translatePath('special://database/' + database))

    def recent_series(self):
        result = {}
        for name in ('plugin.video.watchnixtoons2', 'plugin.video.watchnixtoons2.kodi19'):
            path = self.vfs.translatePath('special://profile/addon_data/%s/recently_watched.dat' % name)
            try:
                with open(path, encoding='utf-8') as file:
                    data = json.load(file)
                if isinstance(data, dict):
                    for entry in data.values():
                        if not isinstance(entry, dict):
                            continue
                        title, url = entry.get('name'), entry.get('url')
                        if isinstance(title, str) and isinstance(url, str) and url.startswith('/'):
                            result[mapping_key(title, 1)] = (url, name)
            except (OSError, ValueError, TypeError):
                continue
        return result

    def known_episodes(self, include_listings=False):
        """Indexed episodes only; background sync must never launch WNT2.

        Querying a plugin:// episode listing via Kodi Files.GetDirectory
        launches WatchNixtoons2 and may produce pop-up errors or site load
        while the user is browsing. The explicit manual restore tool still
        offers episode-list discovery. Background work only uses Kodi's
        existing video database and cannot request new upstream content.
        """
        return merge_records(self.records())

    def pull_anilist(self):
        token = self.addon.getSetting('token').strip()
        if not token:
            self.note('AniList not connected')
            return
        mappings = read_json(self.mappings_path, {})
        records = self.known_episodes(include_listings=False)
        by_key = {}
        for record in records:
            by_key.setdefault(record['key'], []).append(record)
        made = 0
        # Only series approved in the user-facing mapping editor. Never guess.
        for key, mapping in list(sorted(mappings.items()))[:25]:
            if key not in by_key or not isinstance(mapping, dict) or not mapping.get('id'):
                continue
            if mapping.get('ignore'):
                continue
            remote = details(mapping['id'], token)
            plan = make_pull_plan(by_key[key], key, mapping, remote, max_writes=MAX_AUTO_WRITES)
            if made + len(plan['to_mark']) > MAX_AUTO_WRITES:
                self.note('Auto tick limit reached; other series deferred')
                break
            # Only when opt-in enabled; this is the same reviewed safe primitive as v0.4.
            result = apply_pull_plan(plan, self.xbmc.executeJSONRPC, confirmed=True)
            made += len(result['accepted'])
            if result['failed']:
                self.note('Some watched ticks were refused by Kodi')
        self.note('AniList auto-pull finished; %s new local ticks' % made)

    def _bookmark(self, url):
        try:
            reply = rpc_call(self.xbmc.executeJSONRPC, 'Files.GetFileDetails',
                             {'file': url, 'media': 'video', 'properties': ['resume', 'playcount']})
            details_ = reply.get('filedetails') or {}
            resume = details_.get('resume') or {}
            return validate_position(resume.get('position'), resume.get('total'))
        except (DeviceSyncError, AttributeError):
            return None

    def _write_resume(self, url, resume):
        rpc_call(self.xbmc.executeJSONRPC, 'Files.SetFileDetails',
                 {'file': url, 'media': 'video', 'resume': resume})

    def private_sync(self):
        repo = self.addon.getSetting('private_repo').strip()
        token = self.addon.getSetting('private_token').strip()
        if not repo or not token:
            self.note('Private sync not configured; resume sync disabled')
            return
        store = GitHubStore(repo, token)
        remote, _sha = store.read()
        pending = self.state['pending']
        observed = self.state['observed']
        records = self.known_episodes(include_listings=False)
        local = {episode_id(r['file']): r for r in records if episode_id(r['file'])}
        # Publish actual watched *sets*, including cartoons. This never relies on
        # AniList's contiguous episode count, and can't clear remote watched ticks.
        new_watched = [key for key, rec in local.items() if rec['playcount'] > 0]
        proposed = add_watched(pending, new_watched)
        seen = 0
        for key, record in local.items():
            if seen >= MAX_LOCAL_LOOKUPS:
                break
            if record['playcount'] > 0:
                continue
            seen += 1
            position = self._bookmark(record['file'])
            if not position:
                continue
            signature = '%s/%s' % (position['position'], position['total'])
            previous = observed.get(key)
            if isinstance(previous, str):
                previous = {'signature': previous, 'at': 0}
            if previous is None:
                # Crucial: initial scan isn't proof of *new* playback; avoid
                # older dormant Firesticks overriding a more recent remote position.
                observed[key] = {'signature': signature, 'at': 0}
                continue
            old_signature = previous.get('signature', '')
            if old_signature == signature:
                continue
            try:
                old_position, old_total = map(float, old_signature.split('/'))
                if abs(old_position - position['position']) < 0.5 and abs(old_total - position['total']) < 0.5:
                    continue
            except (ValueError, AttributeError):
                pass
            observed[key] = {'signature': signature, 'at': time.time()}
            self.state['counter'] += 1
            event = {'at': time.time(), 'device': self.state['device'],
                     'counter': self.state['counter']}
            proposed = add_resume(proposed, key, position['position'], position['total'], event,
                                  rewatch=(self.addon.getSetting('rewatch_episode') == key))
        self.state['observed'] = observed
        self.state['pending'] = proposed
        write_json(self.state_path, self.state)  # durable offline queue BEFORE network write
        updated = store.merge_and_write(proposed)
        self._remote = updated
        newly_sent = sum(1 for key in proposed['watched'] if key not in remote['watched']
                         and key in updated['watched'])
        newer_positions = sum(1 for key, point in proposed['resumes'].items()
            if key in updated['resumes'] and updated['resumes'][key]['event'] == point['event']
            and (key not in remote['resumes'] or remote['resumes'][key]['event'] != point['event']))
        if newly_sent:
            self.metric('watched_uploaded', newly_sent, 'upload')
        if newer_positions:
            self.metric('resumes_uploaded', newer_positions, 'upload')
        # Restore exact per-episode watched ticks from either Firestick, even
        # for cartoons that AniList cannot represent. Never clear watched marks.
        marked = 0
        for key, record in local.items():
            if marked >= MAX_AUTO_WRITES:
                break
            if key in updated['watched'] and record['playcount'] == 0:
                rpc_call(self.xbmc.executeJSONRPC, 'Files.SetFileDetails',
                         {'file': record['file'], 'media': 'video', 'playcount': 1})
                marked += 1
                record['playcount'] = 1
        # Only create bookmarks on already trusted local episode paths. Do not
        # overwrite meaningful local bookmarks if their observed event is newer.
        applied = 0
        for key, record in local.items():
            if applied >= MAX_AUTO_WRITES:
                break
            point = updated['resumes'].get(key)
            if not point:
                continue
            already = self._bookmark(record['file'])
            previous = observed.get(key) or {}
            if isinstance(previous, str):
                previous = {'signature': previous, 'at': 0}
            # The latest *event* wins, even if its time-in-video is smaller.
            # A locally active bookmark is protected if its observed event is newer.
            # If Kodi already has a meaningful bookmark but we have no
            # timestamped observation of it, its age is unknown. Never replace
            # it with a remote bookmark merely because the remote event has
            # a timestamp. The next genuine local position change can create
            # a trustworthy observation and be merged normally.
            previous_at = float(previous.get('at') or 0)
            if already and previous_at <= 0:
                continue
            if point['event']['at'] <= previous_at:
                continue
            fresh = incoming_resume(0 if previous_at > 0 else
                                    (already or {}).get('position', 0), point,
                                    watched=record['playcount'] > 0,
                                    rewatch=self.addon.getSetting('rewatch_episode') == key)
            if fresh:
                self._write_resume(record['file'], fresh)
                observed[key] = {'signature': '%s/%s' % (fresh['position'], fresh['total']),
                                 'at': point['event']['at']}
                applied += 1
        if marked:
            self.metric('watched_downloaded', marked, 'download')
        if applied:
            self.metric('resumes_downloaded', applied, 'download')
        self.state['pending'] = blank_state()
        self.state['observed'] = observed
        write_json(self.state_path, self.state)
        self.note('Private sync complete; %s exact ticks and %s resumes applied' % (marked, applied))

    def _verified_playback(self, player, now):
        """Never guess an episode from CDN URL or an unrelated player."""
        try:
            tag = player.getVideoInfoTag()
            title = tag.getTVShowTitle()
            episode = int(tag.getEpisode())
            season = max(1, int(tag.getSeason() or 1))
            if not title or episode < 1:
                return None
            # WatchNixtoons2 rewrites its *series* history when resolving a
            # stream. Require a recently changed, matching source entry.
            source_ok = False
            for name in ('plugin.video.watchnixtoons2', 'plugin.video.watchnixtoons2.kodi19'):
                path = self.vfs.translatePath('special://profile/addon_data/%s/recently_watched.dat' % name)
                try:
                    if abs(now - os.stat(path).st_mtime) > 300:
                        continue
                    with open(path, encoding='utf8') as file:
                        recent = json.load(file)
                    if isinstance(recent, dict) and any(
                            isinstance(x, dict) and source_matches(title, x.get('name',''))
                            for x in recent.values()):
                        source_ok = True
                except (OSError, ValueError):
                    continue
            if not source_ok:
                return None
            key = mapping_key(title, season)
            possible = [r for r in self.records()
                        if r['key'] == key and r['episode'] == episode]
            # Ambiguous dub/sub streams must never share a guessed bookmark.
            if len(possible) != 1:
                return None
            point = validate_position(player.getTime(), player.getTotalTime())
            return (episode_id(possible[0]['file']), point) if point else None
        except (AttributeError, ValueError, TypeError, OSError):
            return None

    def capture_playback(self, player, now):
        if now - self.state.get('last_capture', 0) < 12:
            return
        self.state['last_capture'] = now
        match = self._verified_playback(player, now)
        if not match and self._selected and verified_source(player, self._selected, self.vfs, now):
            # The browser already gave us the exact dub/sub episode identity.
            # This is still source-verified, never a guess from a CDN stream.
            try:
                point = validate_position(player.getTime(), player.getTotalTime())
                match = (self._selected['key'], point) if point else None
            except (AttributeError, RuntimeError, ValueError, TypeError):
                pass
        if not match or not match[0]:
            return
        key, point = match
        remote_point = (self._remote or {}).get('resumes', {}).get(key)
        # Prevent an early restart at 0 from overwriting a newer remote
        # bookmark before it can be applied. Genuine rewinds require replay
        # beyond a full minute or an explicit rewatch selection.
        if (remote_point and self._playback_restored != key and
                point['position'] < remote_point['position'] and
                now - (self._selected or {}).get('at', 0) < 120):
            return
        self.state['counter'] += 1
        event = {'at': now, 'device': self.state['device'], 'counter': self.state['counter']}
        self.state['pending'] = add_resume(self.state['pending'], key,
            point['position'], point['total'], event,
            rewatch=(self.addon.getSetting('rewatch_episode') == key))
        if key in self.state['pending']['resumes'] and self.state['pending']['resumes'][key]['event'] == event:
            # This active observation has a trusted timestamp, so a newer
            # event from the other Firestick can subsequently replace it.
            self.state['observed'][key] = {
                'signature': '%s/%s' % (point['position'], point['total']), 'at': now}
        # An in-progress event can be flushed without polling Kodi files. On
        # pause it remains at the latest captured point; stopping also saves a
        # normal Kodi resume bookmark for the subsequent idle reconciliation.
        write_json(self.state_path, self.state)

    def flush_playback(self, now):
        if now - self.state.get('last_flush', 0) < 60:
            return
        self.state['last_flush'] = now
        write_json(self.state_path, self.state)
        if not self.state['pending']['resumes']:
            return
        store = GitHubStore(self.addon.getSetting('private_repo').strip(),
                            self.addon.getSetting('private_token').strip())
        pending = self.state['pending']
        uploaded = store.merge_and_write(pending)
        changed = sum(1 for key, point in pending['resumes'].items()
                      if key in uploaded['resumes'] and uploaded['resumes'][key]['event'] == point['event'])
        self._remote = uploaded
        if changed:
            self.metric('resumes_uploaded', changed, 'upload')
        self.state['pending'] = blank_state()
        write_json(self.state_path, self.state)

    def tick(self, now, is_playing=False):
        # Deliberately avoid background receiving while a stream is playing.
        # Never block the existing outgoing AniList tracker on network delays.
        if is_playing:
            if self.enabled('private_sync'):
                player = self.xbmc.Player()
                self.apply_playback_resume(player, now)
                self.capture_playback(player, now)
                self.flush_playback(now)
            return
        if self.enabled('auto_watched') and now - self.state['last_pull'] >= PULL_INTERVAL:
            self.state['last_pull'] = now
            write_json(self.state_path, self.state)
            self.pull_anilist()
        if self.enabled('private_sync') and now - self.state['last_private'] >= PRIVATE_INTERVAL:
            self.state['last_private'] = now
            write_json(self.state_path, self.state)
            self.private_sync()
        if self.enabled('private_sync'):
            self.observe_selected(now)
