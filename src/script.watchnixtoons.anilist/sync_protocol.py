"""Pure, conservative cross-device state rules. Never treats a timestamp as an episode count.

Stable episode IDs are derived from WatchNixtoons2's *source episode path*, not
stream/CDN URLs or potentially misleading anime titles. All watched tick sets
only grow; deliberately rewound positions may go backwards in time-in-video.
"""
import re
import math
from urllib.parse import parse_qs, unquote, urlparse

MAX_EPISODES = 4000
MAX_RESUMES = 500


class SyncStateError(ValueError):
    pass


def episode_id(plugin_url):
    """Stable exact WNT2 episode key; preserve dub/sub edition differences."""
    if not isinstance(plugin_url, str) or len(plugin_url) > 4096:
        return None
    parsed = urlparse(plugin_url)
    if parsed.scheme != 'plugin' or parsed.netloc not in (
            'plugin.video.watchnixtoons2', 'plugin.video.watchnixtoons2.kodi19'):
        return None
    query = parse_qs(parsed.query)
    if query.get('action', [''])[0] != 'actionResolve' or len(query.get('url', [])) != 1:
        return None
    source = query['url'][0]
    for _ in range(2):
        source = unquote(source)
    target = urlparse(source)
    # URL pages may have an HTTP site hostname; ignore domain changes.
    path = target.path.lower().rstrip('/')
    if not path or len(path) > 400 or '\\' in path or '..' in path:
        return None
    # Reject nonsensical strings and impossible paths.
    if not re.fullmatch(r'/[a-z0-9/._%~-]+', path):
        return None
    from watched_db import parse_watched_url
    if not parse_watched_url(plugin_url):
        return None
    return path


def validate_position(position, total):
    try:
        position, total = float(position), float(total)
    except (ValueError, TypeError):
        return None
    # Bound durations (4h), avoid NaN/inf and near-completed positions.
    if not (math.isfinite(position) and math.isfinite(total) and
            30 <= position < total * .95 and 60 <= total <= 14400):
        return None
    return {'position': round(position, 1), 'total': round(total, 1)}


def event_rank(event):
    if not isinstance(event, dict):
        return (0, '', 0)
    try:
        stamp = float(event.get('at') or 0)
        counter = int(event.get('counter') or 0)
        if not (math.isfinite(stamp) and 0 <= stamp < 4102444800 and 0 <= counter < 2**63):
            return (0, '', 0)
    except (ValueError, TypeError):
        return (0, '', 0)
    return (stamp, str(event.get('device') or '')[:64], counter)


def validated_state(value):
    """Reject malicious or malformed remote documents before any local changes."""
    if not isinstance(value, dict) or value.get('schema') != 1:
        raise SyncStateError('Unsupported sync document format')
    watched, resumes = value.get('watched'), value.get('resumes')
    if not isinstance(watched, dict) or not isinstance(resumes, dict):
        raise SyncStateError('Malformed sync document')
    if len(watched) > MAX_EPISODES or len(resumes) > MAX_RESUMES:
        raise SyncStateError('Remote data exceeds safety limits')
    for key in watched:
        if not isinstance(key, str) or len(key) > 400 or not key.startswith('/'):
            raise SyncStateError('Invalid watched identity')
    for key, item in resumes.items():
        if key not in watched and (not isinstance(key, str) or len(key) > 400 or not key.startswith('/')):
            raise SyncStateError('Invalid resume identity')
        if not isinstance(item, dict) or validate_position(item.get('position'), item.get('total')) is None:
            raise SyncStateError('Invalid remote resume point')
        if event_rank(item.get('event'))[0] <= 0:
            raise SyncStateError('Invalid resume event')
    return value


def blank_state():
    return {'schema': 1, 'watched': {}, 'resumes': {}}


def merge_state(a, b):
    """Commutative union for watched flags, newest-event-wins for resumes.

    Completed flags suppress old resumes. A deliberate rewatch must explicitly
    set rewatch=True and only changes a *resume*, never a watched flag.
    """
    a, b = validated_state(a), validated_state(b)
    watched = {**a['watched'], **b['watched']}
    resumes = {}
    for key in set(a['resumes']) | set(b['resumes']):
        choices = [s['resumes'][key] for s in (a,b) if key in s['resumes']]
        newest = max(choices, key=lambda item: event_rank(item['event']))
        if key in watched and not newest.get('rewatch', False):
            continue
        resumes[key] = newest
    return validated_state({'schema': 1, 'watched': watched, 'resumes': resumes})


def add_watched(state, ids):
    state = validated_state(state)
    out = {'schema': 1, 'watched': dict(state['watched']), 'resumes': dict(state['resumes'])}
    for key in ids:
        if key is not None and isinstance(key, str) and key.startswith('/') and len(key) <= 400:
            out['watched'][key] = True
            if key in out['resumes'] and not out['resumes'][key].get('rewatch'):
                del out['resumes'][key]
    return validated_state(out)


def add_resume(state, key, position, total, event, rewatch=False):
    current = validated_state(state)
    if not isinstance(key, str) or not key.startswith('/') or len(key) > 400:
        raise SyncStateError('Invalid episode key')
    position = validate_position(position, total)
    if not position or event_rank(event)[0] <= 0:
        raise SyncStateError('Invalid viewing position')
    if key in current['watched'] and not rewatch:
        return current  # never resurrect finished episodes silently
    item = {**position, 'event': event, 'rewatch': bool(rewatch)}
    out = {'schema': 1, 'watched': dict(current['watched']), 'resumes': dict(current['resumes'])}
    old = out['resumes'].get(key)
    if old is None or event_rank(item['event']) > event_rank(old['event']):
        out['resumes'][key] = item
    return validated_state(out)


def incoming_resume(local_position, incoming, watched=False, rewatch=False):
    """Return a safe Kodi resume bookmark, or None; no forced play or seeks."""
    if watched and not rewatch:
        return None
    if not isinstance(incoming, dict):
        return None
    good = validate_position(incoming.get('position'), incoming.get('total'))
    if not good:
        return None
    if watched and not incoming.get('rewatch'):
        return None
    if local_position and local_position > 30 and not rewatch:
        # Do not replace a meaningful local position of unknown provenance.
        return None
    return good
