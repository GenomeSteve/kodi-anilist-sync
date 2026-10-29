"""Pure helpers shared by the user interface and Kodi background service."""
import re
import unicodedata
from urllib.parse import parse_qs, urlparse


def normalise(value):
    value = unicodedata.normalize('NFKC', value or '').casefold()
    value = value.replace('&', ' and ')
    value = re.sub(r'\[/?(?:b|i|color[^\]]*)\]', '', value)
    value = re.sub(r'\b(english\s+)?(?:subbed|dubbed|dub|sub)\b', ' ', value)
    value = re.sub(r'\bseason\s+\d+\b', ' ', value)
    value = re.sub(r'\b(?:part|cour)\s+\d+\b', ' ', value)
    value = re.sub(r'[^\w\s]', ' ', value, flags=re.UNICODE)
    return ' '.join(value.split()).strip()


def mapping_key(title, season):
    return '%s|s%s' % (normalise(title), max(1, int(season or 1)))


def source_matches(show, recent_title):
    a = normalise(show)
    b = normalise(recent_title)
    if not a or not b:
        return False
    if a == b:
        return True
    # Only permit a suffix/prefix difference consisting of at most 2 words;
    # helps with 'Series - The Animation' without matching unrelated shows.
    sa, sb = a.split(), b.split()
    shorter, longer = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    return (len(shorter) >= 2 and len(longer) - len(shorter) <= 2
            and (longer[:len(shorter)] == shorter))


def parse_token(raw):
    text = (raw or '').strip()
    if 'access_token=' in text:
        parsed = urlparse(text)
        text = parse_qs(parsed.fragment or parsed.query).get('access_token', [''])[0]
    return text.strip()


def exact_candidate(title, season, episode, results):
    """Only automatically select a single exact match for a first-season title.

    A site 'Season 2' is not necessarily AniList's second season; never guess.
    """
    if season != 1:
        return None
    wanted = normalise(title)
    exact = []
    for item in results:
        if not isinstance(item, dict) or not item.get('id'):
            continue
        names = list((item.get('title') or {}).values()) + (item.get('synonyms') or [])
        if wanted and wanted in {normalise(s) for s in names if isinstance(s, str)}:
            if item.get('episodes') is not None and episode > item['episodes']:
                continue
            exact.append(item)
    return exact[0] if len(exact) == 1 else None


def desired_progress(existing, new_episode, known_episode_count, media_status):
    """Returns (progress, status) or None when no changes are necessary.

    Never reduce progress, and preserve completed/dropped entries if the progress
    is not greater. Only mark completed when AniList says the anime is finished.
    """
    current = int((existing or {}).get('progress') or 0)
    if new_episode <= current or new_episode < 1:
        return None
    if known_episode_count is not None and new_episode > int(known_episode_count):
        return None
    status = 'COMPLETED' if (known_episode_count and new_episode >= known_episode_count
                             and media_status == 'FINISHED') else 'CURRENT'
    return new_episode, status
