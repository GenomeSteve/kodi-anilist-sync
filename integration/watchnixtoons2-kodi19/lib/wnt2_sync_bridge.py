"""Optional, local-only WatchNixtoons2 v0.3 Kodi 21 episode-list bridge.

The source synchroniser saves a validated, token-free private_snapshot.json.
This adapter is called only while the provider builds an episode listing.
It does not fetch site directories, call GitHub or alter Kodi's database.
Not a replacement streaming add-on; integrate into a *matched* WNT2 build.
"""
import json
import math
import os
import re
import sqlite3
from urllib.parse import parse_qs, quote, unquote, urlparse

MAX_CACHE_BYTES = 250000
VALID_PATH = re.compile(r"/[a-z0-9/._%~-]{1,400}\Z")
ALLOWED_ADDONS = ("plugin.video.watchnixtoons2", "plugin.video.watchnixtoons2.kodi19")


def episode_key(plugin_url):
    """Exact path identity, including sub/dub, matching sync_protocol.episode_id."""
    if not isinstance(plugin_url, str) or len(plugin_url) > 4096:
        return None
    uri = urlparse(plugin_url)
    if uri.scheme != "plugin" or uri.netloc not in ALLOWED_ADDONS:
        return None
    query = parse_qs(uri.query)
    if query.get("action") != ["actionResolve"] or len(query.get("url", [])) != 1:
        return None
    source = query["url"][0]
    for _ in range(2):
        source = unquote(source)
    path = urlparse(source).path.lower().rstrip("/")
    if not path or ".." in path or "\\" in path or not VALID_PATH.fullmatch(path):
        return None
    # Avoid ambiguous WNT2 page paths without an exact episode number.
    if not re.search(r"(?:^|[-_])(?:episode|ep)[-_]?\d{1,4}(?=$|[-_])|s\d{1,2}e\d{1,4}", path):
        return None
    return path


def valid_point(item):
    if not isinstance(item, dict):
        return None
    try:
        pos, total = float(item.get("position")), float(item.get("total"))
        event = item.get("event") or {}
        stamp = float(event.get("at", 0))
    except (ValueError, TypeError, AttributeError):
        return None
    if not (math.isfinite(pos) and math.isfinite(total) and math.isfinite(stamp)):
        return None
    if not (30 <= pos < 0.95 * total and 60 <= total <= 14400 and 0 < stamp < 4102444800):
        return None
    return pos, total, stamp


def read_snapshot(path):
    """Read the last verified token-free state (no network or credentials)."""
    try:
        if os.stat(path).st_size > MAX_CACHE_BYTES:
            return {"watched": {}, "resumes": {}}
        with open(path, "r", encoding="utf-8") as stream:
            value = json.load(stream)
        if value.get("schema") != 1:
            raise ValueError("Wrong schema")
        watched, resumes = value["watched"], value["resumes"]
        if not isinstance(watched, dict) or not isinstance(resumes, dict):
            raise ValueError("Wrong types")
        if len(watched) > 4000 or len(resumes) > 500:
            raise ValueError("Oversize state")
        # Only strictly validated state is passed to the list-item decorator.
        safe_watched = {k: True for k, v in watched.items()
                        if isinstance(k, str) and k.startswith("/") and v is True}
        safe_resumes = {k: v for k, v in resumes.items()
                        if isinstance(k, str) and k.startswith("/") and valid_point(v)}
        return {"watched": safe_watched, "resumes": safe_resumes}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {"watched": {}, "resumes": {}}


def local_kodi_metadata(db_path):
    """Read-only local playcounts and bookmarks; local unwatched history wins ties."""
    result = {}
    if not db_path:
        return result
    db = None
    try:
        uri = "file:%s?mode=ro" % quote(os.path.abspath(db_path), safe="/")
        db = sqlite3.connect(uri, uri=True, timeout=2)
        db.execute("PRAGMA query_only=ON")
        sql = ("SELECT f.strFilename, COALESCE(f.playCount,0), "
               "b.timeInSeconds,b.totalTimeInSeconds "
               "FROM files AS f LEFT JOIN bookmark AS b "
               "ON b.idFile=f.idFile AND b.type=1 "
               "WHERE f.strFilename LIKE ? LIMIT 25001")
        rows = db.execute(sql, ("%plugin.video.watchnixtoons2%actionResolve%",)).fetchall()
        if len(rows) > 25000:
            return {}
        for url, count, pos, total in rows:
            key = episode_key(url)
            if key:
                result[key] = {"playcount": int(count or 0),
                               "position": float(pos or 0),
                               "total": float(total or 0)}
    except (sqlite3.Error, OSError, ValueError, TypeError):
        return {}  # Fail closed; upstream list items still work unmodified.
    finally:
        if db is not None:
            db.close()
    return result


def load():
    """Once per WNT2 episode page; never on each ListItem."""
    try:
        import xbmcaddon
        import xbmcvfs
        profile = xbmcvfs.translatePath(
            xbmcaddon.Addon("script.watchnixtoons.anilist").getAddonInfo("profile"))
        state = read_snapshot(os.path.join(profile, "private_snapshot.json"))
        _, dbs = xbmcvfs.listdir("special://database")
        dbfiles = [s for s in dbs if re.fullmatch(r"MyVideos\d+\.db", s)]
        dbfiles.sort(key=lambda s: int(re.search(r"\d+", s).group()), reverse=True)
        path = xbmcvfs.translatePath("special://database/" + dbfiles[0]) if dbfiles else None
        state["local"] = local_kodi_metadata(path)
        with open(os.path.join(profile, "background.json"), "r", encoding="utf-8") as handle:
            observed = json.load(handle).get("observed", {})
        state["observed"] = observed if isinstance(observed, dict) else {}
        return state
    except (ImportError, OSError, TypeError, ValueError, KeyError, AttributeError):
        return {"watched": {}, "resumes": {}, "local": {}, "observed": {}}


def decorate(item, plugin_url, state):
    """Apply exact watched and resume metadata before Kodi renders the list."""
    key = episode_key(plugin_url)
    if not key or not state:
        return item
    local = state.get("local", {}).get(key) or {}
    if local.get("playcount", 0) > 0 or key in state.get("watched", {}):
        item.getVideoInfoTag().setPlaycount(1)
        return item
    point = state.get("resumes", {}).get(key)
    native_pos = float(local.get("position") or 0)
    native_total = float(local.get("total") or 0)
    if native_pos > 30 and native_total > native_pos:
        previous = state.get("observed", {}).get(key) or {}
        previous_at = float(previous.get("at", 0) or 0) if isinstance(previous, dict) else 0
        remote = valid_point(point)
        # If local bookmark age isn't proven older, never overwrite it.
        if not remote or previous_at <= 0 or previous_at >= remote[2]:
            item.getVideoInfoTag().setResumePoint(native_pos, native_total)
            return item
    remote = valid_point(point)
    if remote:
        item.getVideoInfoTag().setResumePoint(remote[0], remote[1])
    return item
