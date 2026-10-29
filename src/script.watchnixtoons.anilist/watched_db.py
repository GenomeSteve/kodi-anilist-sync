"""Read-only fallback for Kodi watched ticks saved by WatchNixtoons2.

WatchNixtoons2 records playcount in Kodi's MyVideos database. On some versions
its player metadata lacks an episode number, so we only queue records with a
watch timestamp and an original WatchNixtoons2 playback URL containing an
explicit episode number. We never write to Kodi's database.
"""
import calendar
import os
import re
import sqlite3
import time
from datetime import datetime
from urllib.parse import parse_qs, unquote, urlparse

PLUGIN_ID = 'plugin.video.watchnixtoons2'


def parse_watched_url(filename):
    """Return (show_title, season, episode) for an unambiguous WNT2 Kodi URL."""
    if not isinstance(filename, str) or not filename:
        return None
    parsed = urlparse(filename)
    if parsed.scheme != 'plugin' or parsed.netloc not in (PLUGIN_ID, PLUGIN_ID + '.kodi19'):
        return None
    args = parse_qs(parsed.query)
    if args.get('action', [''])[0] != 'actionResolve':
        return None
    source = args.get('url', [''])[0]
    for _ in range(2):
        if '%' in source:
            source = unquote(source)
    path = urlparse(source).path.rstrip('/').split('/')[-1]
    # WNT2 page addresses tend to end in -episode-12-english-subbed.
    match = re.search(r'(?i)(?:^|[-_\s])(?:episode|ep)[-_\s]*0*(\d{1,4})(?=$|[-_\s])', path)
    if not match:
        # Other anime pages use an S01E12 or 1x12 suffix.
        match = re.search(r'(?i)(?:^|[-_\s])s(\d{1,2})e0*(\d{1,4})(?=$|[-_\s])', path)
        if not match:
            return None
        title = path[:match.start()].strip('-_ ')
        season, episode = int(match.group(1)), int(match.group(2))
    else:
        title = path[:match.start()].strip('-_ ')
        episode = int(match.group(1))
        season_match = re.search(r'(?i)(?:^|[-_\s])season[-_\s]*(\d{1,2})$', title)
        season = int(season_match.group(1)) if season_match else 1
        if season_match:
            title = title[:season_match.start()]
    title = re.sub(r'(?i)(?:[-_](?:english|dubbed|subbed|dub|sub))+$', '', title).strip('-_ ')
    title = re.sub(r'[-_]+', ' ', title).strip()
    if not title or episode < 1 or episode > 3000 or season < 1:
        return None
    return {'title': title, 'season': season, 'episode': episode}


def recent_timestamp(value, now=None):
    """Kodi has used UTC and local time for lastPlayed across installations."""
    if not value:
        return False
    now = time.time() if now is None else now
    try:
        stamp = time.strptime(value[:19], '%Y-%m-%d %H:%M:%S')
        local = time.mktime(stamp)
        utc = calendar.timegm(stamp)
        return min(abs(now - local), abs(now - utc)) < 7200
    except (ValueError, TypeError, OverflowError):
        return False


def recent_watched(database_path, now=None, limit=30):
    """Return only newly marked watched entries with verifiable plugin paths."""
    if not database_path or not os.path.isfile(database_path):
        return []
    now = time.time() if now is None else now
    connection = None
    try:
        # Read-only SQLite: Kodi alone owns the database and its watched state.
        connection = sqlite3.connect('file:%s?mode=ro' % database_path, uri=True, timeout=2)
        cursor = connection.execute(
            "SELECT strFilename, lastPlayed FROM files "
            "WHERE playCount >= 1 AND lastPlayed IS NOT NULL "
            "AND strFilename LIKE ? ORDER BY lastPlayed DESC LIMIT ?",
            ('%plugin.video.watchnixtoons2%actionResolve%', int(limit)))
        result = []
        for filename, played in cursor.fetchall():
            if not recent_timestamp(played, now):
                continue
            event = parse_watched_url(filename)
            if event:
                event['last_played'] = played
                result.append(event)
        return result
    finally:
        if connection:
            connection.close()
