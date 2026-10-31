"""Passive Kodi UI episode identification for private cross-device resume.

Observes already-rendered selected ListItems; NEVER calls plugin:// directories.
No requests to streaming hosts and no guessed show/episode identities.
"""
import json
import os
import time
from core import normalise
from device_sync import record_for_url
from sync_protocol import episode_id


def selected_episode(xbmc):
    """Return an exact WNT2 episode URL selected in Kodi's current directory."""
    folder = (xbmc.getInfoLabel('Container.FolderPath') or '').lower()
    candidates = (xbmc.getInfoLabel('ListItem.FileNameAndPath'),
                  xbmc.getInfoLabel('ListItem.Path'))
    # Some skins don't publish FolderPath; the selected file is independently
    # checked against the exact WNT2 plugin action before it is accepted.
    if folder and not folder.startswith('plugin://plugin.video.watchnixtoons2'):
        return None
    for url in candidates:
        if episode_id(url):
            return url
    return None


def _same_series(a, b):
    """Restrict matching to the source name, allowing the common 'TV' suffix."""
    def name(value):
        words = normalise(value).split()
        while words and words[-1] in ('tv', 'series', 'animation'):
            words.pop()
        return ' '.join(words)
    return bool(name(a)) and name(a) == name(b)


def verified_source(player, selection, vfs, now):
    """Verify the exact browser choice belongs to the playback being opened.

    A selected URL alone is not proof a later CDN stream is the same episode.
    Require same playing plugin path OR recent source addon activity, plus
    compatible metadata when metadata exists. Other addon plugin URLs reject.
    """
    if not selection or now - selection['at'] > 120 or now < selection['at'] - 5:
        return False
    url = selection['url']
    record = record_for_url(url)
    if not record:
        return False
    try:
        item = player.getPlayingItem()
        play_path = item.getPath()
        if play_path and episode_id(play_path) == episode_id(url):
            return True
    except (AttributeError, RuntimeError, TypeError):
        pass
    try:
        playing = player.getPlayingFile()
        if playing.startswith('plugin://'):
            return episode_id(playing) == episode_id(url)
    except (AttributeError, RuntimeError, TypeError):
        pass
    try:
        tag = player.getVideoInfoTag()
        episode = int(tag.getEpisode() or 0)
        series = tag.getTVShowTitle() or ''
        if episode > 0 and episode != record['episode']:
            return False
        if series and not _same_series(series, record['title']):
            return False
    except (AttributeError, ValueError, TypeError, RuntimeError):
        pass
    for addon in ('plugin.video.watchnixtoons2', 'plugin.video.watchnixtoons2.kodi19'):
        path = vfs.translatePath('special://profile/addon_data/%s/recently_watched.dat' % addon)
        try:
            stamp = os.stat(path).st_mtime
            if not (selection['at'] - 10 <= stamp <= now + 5):
                continue
            with open(path, 'r', encoding='utf-8') as handle:
                history = json.load(handle)
            if not isinstance(history, dict):
                continue
            if any(isinstance(entry, dict) and _same_series(entry.get('name', ''), record['title'])
                   for entry in history.values()):
                return True
        except (OSError, ValueError, TypeError):
            continue
    return False
