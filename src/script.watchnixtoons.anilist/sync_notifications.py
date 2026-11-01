"""Non-intrusive Kodi notifications for confirmed outbound synchronisation.

GitHub uploads still run during playback for cross-device resilience. Toasts
are buffered and coalesced until the player is idle, not emitted each minute.
No data or credentials are sent anywhere by this module.
"""
import re
import threading
import time

MAX_TOASTS = 3
IDLE_GRACE_SECONDS = 8


def _label(value):
    if not isinstance(value, str):
        return "Episode"
    if value.startswith("/"):
        # Preserve exact dub/sub and season details for recognisable source keys.
        if not re.fullmatch(r"/[a-z0-9/._%~-]{1,400}", value):
            return "Episode"
        value = value.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").title()
    value = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
    return value[:95].strip() or "Episode"


def _enabled(addon):
    try:
        return addon.getSetting("sync_notifications") != "false"
    except (AttributeError, KeyError, TypeError):
        return True  # Existing installs and older test profiles default to enabled.


class NotificationBuffer:
    """Thread-safe coalescer shared by the AniList service and GitHub worker."""

    def __init__(self):
        self.lock = threading.Lock()
        # (destination, episode label) => progress/watched; watched wins.
        self.pending = {}
        self.last_playing_at = None

    def queue(self, destination, updates):
        with self.lock:
            for kind, title in updates:
                if kind not in ("progress", "watched"):
                    continue
                name = _label(title)
                key = (destination, name)
                previous = self.pending.get(key)
                if previous != "watched":
                    self.pending[key] = kind

    def drain(self, now, is_playing):
        """Only release toasts after continuous idle for a brief grace period."""
        with self.lock:
            if is_playing:
                self.last_playing_at = now
                return []
            if self.last_playing_at is not None and now - self.last_playing_at < IDLE_GRACE_SECONDS:
                return []
            pending = [(destination, kind, name)
                       for (destination, name), kind in self.pending.items()]
            self.pending.clear()
            return pending

    def clear(self):
        with self.lock:
            self.pending.clear()


_BUFFER = NotificationBuffer()


def notify_sync(addon, destination, updates):
    """Queue only confirmed outgoing ('progress'|'watched', source/title) events.

    The service's periodic flush controls when the user actually sees them.
    Never hold back or retry the underlying GitHub/AniList upload.
    """
    if not updates:
        return
    if not _enabled(addon):
        _BUFFER.clear()
        return
    _BUFFER.queue(destination, updates)


def flush_notifications(addon, is_playing=False, now=None):
    """Call on the normal Kodi service loop, including when there are no uploads.

    A transient buffering gap must not release toasts over the active video.
    The 8-second idle grace also coalesces adjacent progress and watched saves.
    """
    if not _enabled(addon):
        _BUFFER.clear()
        return
    stamp = time.monotonic() if now is None else now
    ready = _BUFFER.drain(stamp, is_playing)
    if not ready:
        return
    grouped = {}
    for destination, kind, name in ready:
        grouped.setdefault(destination, []).append((kind, name))
    try:
        import xbmcgui
        dialog = xbmcgui.Dialog()
        for destination, updates in grouped.items():
            for kind, name in updates[:MAX_TOASTS]:
                message = ("Progress for " if kind == "progress" else "Watched status for ") + name + " synced"
                dialog.notification("AniList Sync: " + destination, message, time=5000, sound=False)
            if len(updates) > MAX_TOASTS:
                dialog.notification("AniList Sync: " + destination,
                                    "%d more episode updates synced" % (len(updates) - MAX_TOASTS),
                                    time=5000, sound=False)
    except Exception:
        # Non-critical UI failures must never cause an upload retry.
        return
