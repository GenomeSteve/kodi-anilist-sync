"""Optional, interactive-only historical watched import.

No service entrypoint imports this module. Kodi MyVideos is queried read-only,
and no AniList mutation happens without an explicit per-series confirmation.
"""
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from core import mapping_key
from watched_db import parse_watched_url

MAX_ROWS = 25000


class HistoryError(Exception):
    """History scan is incomplete or cannot be safely interpreted."""


def locate_myvideos(names):
    """Pick Kodi's newest schema version, not arbitrary directory order."""
    candidates = [name for name in names if name.startswith('MyVideos') and name.endswith('.db')
                  and name[len('MyVideos'):-3].isdigit()]
    return max(candidates, key=lambda name: int(name[len('MyVideos'):-3])) if candidates else None


def read_history(database_path, limit=MAX_ROWS):
    """Scan historical watched episodes; never read unwatched or other add-ons.

    Returns a dictionary grouped by the existing live-sync mapping key. Fails
    closed when the record limit is exceeded, to avoid a partial import.
    """
    if not database_path:
        raise HistoryError('No Kodi video database found.')
    path = str(Path(database_path).resolve())
    uri = 'file:%s?mode=ro' % quote(path, safe='/')
    grouped = {}
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=3)) as conn:
            conn.execute('PRAGMA query_only=ON')
            cursor = conn.execute(
                'SELECT strFilename FROM files WHERE playCount >= 1 AND strFilename LIKE ? '
                'ORDER BY idFile ASC LIMIT ?',
                ('%plugin.video.watchnixtoons2%actionResolve%', int(limit) + 1))
            rows = cursor.fetchall()
        if len(rows) > limit:
            raise HistoryError('Too many history records to safely scan; no import performed.')
        for (filename,) in rows:
            parsed = parse_watched_url(filename)
            if not parsed:
                continue
            title, season, episode = parsed['title'], parsed['season'], parsed['episode']
            key = mapping_key(title, season)
            if key not in grouped:
                grouped[key] = {'key': key, 'title': title, 'season': season, 'episodes': set()}
            grouped[key]['episodes'].add(episode)
    except (sqlite3.Error, OSError) as exc:
        raise HistoryError('Unable to read Kodi video history (%s).' % type(exc).__name__) from None
    return {key: {**value, 'episodes': sorted(value['episodes'])}
            for key, value in sorted(grouped.items())}


def make_plan(episodes, offset, current, total=None):
    """Conservatively extend *only contiguous* AniList progress.

    The first acceptable episode is current + 1; a watched episode 12 never
    implies episodes 1–11 were watched. Kodi and AniList are never changed by
    calculating a plan. Offset is the already defined season mapping offset.
    """
    try:
        offset, current = int(offset), int(current)
        if offset < 0 or current < 0:
            raise ValueError('Negative offset/progress')
        count = int(total) if total is not None else None
        if count is not None and count < 1:
            raise ValueError('Invalid anime episode count')
        watched = set()
        for ep in episodes:
            ep = int(ep)
            if ep < 1:
                raise ValueError('Invalid source episode')
            mapped = ep - offset
            if mapped > 0:
                watched.add(mapped)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HistoryError('Episode or mapping values are invalid: %s' % type(exc).__name__) from None
    if count is not None and any(ep > count for ep in watched):
        return {'before': current, 'after': current, 'reason': 'Episode numbers exceed AniList season length',
                'evidence': sorted(watched), 'changed': False}
    target = current
    # Even with missing older Kodi records, continuing an existing AniList
    # progress is safe if the following episodes were individually ticked.
    while target + 1 in watched:
        target += 1
    reason = ('Ready to import' if target > current else
              'No consecutive watched episode following AniList progress')
    return {'before': current, 'after': target, 'reason': reason,
            'evidence': sorted(watched), 'changed': target > current}


def import_confirmed(group, mapping, anime, token, consent, save_fn):
    """One series, at most one AniList write. Explicit consent is mandatory.

    Both the preview and write use freshly fetched AniList details supplied by
    the caller; the caller must fetch again after confirmation to avoid stale
    progress. Caller supplies save_fn for unit-test isolation.
    """
    if not consent:
        return {'outcome': 'cancelled'}
    if not mapping or mapping.get('ignore') or not mapping.get('id'):
        return {'outcome': 'skipped', 'reason': 'No approved AniList mapping'}
    if int(anime.get('id') or 0) != int(mapping['id']):
        return {'outcome': 'skipped', 'reason': 'AniList identity changed'}
    from core import desired_progress
    existing = anime.get('mediaListEntry') or {}
    plan = make_plan(group['episodes'], mapping.get('offset', 0), existing.get('progress') or 0,
                     anime.get('episodes'))
    if not plan['changed']:
        return {'outcome': 'skipped', 'reason': plan['reason']}
    update = desired_progress(existing, plan['after'], anime.get('episodes'), anime.get('status'))
    if update is None:
        return {'outcome': 'skipped', 'reason': 'Existing AniList progress is higher'}
    # Prefer existing list status to avoid turning PAUSED/DROPPED into CURRENT.
    # Only mark completed if full known episode count and FINISHED.
    status = update[1]
    if status != 'COMPLETED' and existing.get('status') in ('PAUSED', 'DROPPED', 'REPEATING'):
        status = existing['status']
    result = save_fn(int(anime['id']), existing.get('id'), update[0], status, token)
    if int(result.get('progress') or 0) < plan['after']:
        raise HistoryError('AniList did not confirm the requested progress.')
    return {'outcome': 'updated', 'before': plan['before'], 'after': plan['after']}
